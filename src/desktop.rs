use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::BTreeMap, path::PathBuf, process::Stdio, time::Duration};
use tokio::{
    io::{AsyncBufReadExt, BufReader},
    net::UnixStream,
    process::Command,
    sync::watch,
};

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Window {
    pub address: String,
    pub pid: u32,
    pub stable_id: String,
    pub class: String,
    pub title: String,
    pub visible: bool,
    pub size: Vec<i64>,
    #[serde(default = "no_monitor")]
    pub monitor: i64,
    #[serde(default = "no_monitor")]
    pub workspace: i64,
    /// Hyprland fullscreen mode: 0 none, 1 maximized, 2 fullscreen, 3 both.
    #[serde(default)]
    pub fullscreen: i64,
}
fn no_monitor() -> i64 {
    -1
}
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Monitor {
    pub id: i64,
    pub name: String,
    pub width: f64,
    pub height: f64,
    pub scale: f64,
    pub focused: bool,
    /// The workspace currently shown on this monitor, part of the fit-memory key.
    pub active_workspace: i64,
}
/// Key under which a fitted window size is remembered: a new window lands on the
/// focused monitor's active workspace, and the tile there is stable per layout.
pub fn fit_key(monitor: &str, workspace: i64) -> String {
    format!("{monitor}:{workspace}")
}
pub const CLASS: &str = "com.moonlight_stream.Moonlight";
/// Qt sets the desktop file name. Moonlight 6.2's SDL window does not: it
/// `qputenv`s `SDL_VIDEO_WAYLAND_WMCLASS` after sdl2-compat has already copied
/// the process environment, so the stream surface falls back to the executable
/// name (`moonlight` or `moonlight-qt`).
pub fn stream_class(class: &str) -> bool {
    matches!(
        class,
        CLASS | "com.moonlight_stream.Moonlight.desktop" | "moonlight" | "moonlight-qt"
    )
}
fn command() -> Command {
    let mut cmd = Command::new("hyprctl");
    if let Ok(instance) = std::env::var("HYPRLAND_INSTANCE_SIGNATURE") {
        cmd.args(["-i", &instance]);
    }
    cmd.stdin(Stdio::null())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    cmd
}
async fn snapshot() -> Result<Vec<Window>> {
    let output = tokio::time::timeout(
        Duration::from_secs(3),
        command().args(["-j", "clients"]).output(),
    )
    .await??;
    if !output.status.success() {
        bail!("Hyprland unavailable");
    }
    let values: Vec<Value> = serde_json::from_slice(&output.stdout)?;
    Ok(values
        .into_iter()
        .filter(|w| w["mapped"] == true && w["hidden"] != true)
        .filter_map(|w| {
            Some(Window {
                address: w["address"].as_str()?.into(),
                pid: w["pid"].as_u64()?.try_into().ok()?,
                stable_id: w["stableId"].as_str()?.into(),
                class: w["class"].as_str()?.into(),
                title: w["title"].as_str()?.into(),
                visible: w["visible"] == true,
                size: serde_json::from_value(w["size"].clone()).unwrap_or_default(),
                monitor: w["monitor"].as_i64().unwrap_or(-1),
                workspace: w["workspace"]["id"].as_i64().unwrap_or(-1),
                fullscreen: w["fullscreen"].as_i64().unwrap_or(0),
            })
        })
        .collect())
}
/// Run hyprctl and return its text output.
pub async fn control(args: &[&str]) -> Result<String> {
    let output =
        tokio::time::timeout(Duration::from_secs(5), command().args(args).output()).await??;
    if !output.status.success() {
        bail!("Hyprland unavailable");
    }
    Ok(String::from_utf8_lossy(&output.stdout).into_owned())
}
async fn query(args: &[&str]) -> Result<Value> {
    let output =
        tokio::time::timeout(Duration::from_secs(3), command().args(args).output()).await??;
    if !output.status.success() {
        bail!("Hyprland unavailable");
    }
    Ok(serde_json::from_slice(&output.stdout)?)
}
/// The pid of the currently focused window, if any.
pub async fn active_pid() -> Result<Option<u32>> {
    let value = query(&["-j", "activewindow"]).await?;
    Ok(value["pid"]
        .as_u64()
        .and_then(|p| u32::try_from(p).ok())
        .filter(|p| *p != 0))
}
pub async fn monitors() -> Result<Vec<Monitor>> {
    let values = query(&["-j", "monitors"]).await?;
    let monitors: Vec<Monitor> = values
        .as_array()
        .context("invalid monitor list")?
        .iter()
        .filter_map(|m| {
            Some(Monitor {
                id: m["id"].as_i64()?,
                name: m["name"].as_str()?.into(),
                width: m["width"].as_f64()?,
                height: m["height"].as_f64()?,
                scale: m["scale"].as_f64().filter(|s| *s > 0.0)?,
                focused: m["focused"] == true,
                active_workspace: m["activeWorkspace"]["id"].as_i64().unwrap_or(-1),
            })
        })
        .collect();
    if monitors.is_empty() {
        bail!("no Hyprland monitors");
    }
    Ok(monitors)
}
/// Full physical resolution of the focused monitor, without subtracting bars or gaps.
pub async fn full_monitor_resolution() -> Result<String> {
    let values = query(&["-j", "monitors"]).await?;
    let monitor = values
        .as_array()
        .context("invalid monitor list")?
        .iter()
        .find(|m| m["focused"] == true)
        .context("no focused monitor")?;
    monitor_resolution(monitor)
}
fn monitor_resolution(monitor: &Value) -> Result<String> {
    let mut width = monitor["width"].as_i64().context("invalid monitor width")?;
    let mut height = monitor["height"]
        .as_i64()
        .context("invalid monitor height")?;
    if monitor["transform"].as_i64().unwrap_or(0) % 2 != 0 {
        std::mem::swap(&mut width, &mut height);
    }
    if !(240..=16384).contains(&width) || !(240..=16384).contains(&height) {
        bail!("monitor resolution outside supported range");
    }
    physical(&[width, height], 1.0).context("invalid monitor resolution")
}

/// Physical pixels of a logical size, rounded to the even dimensions encoders need.
pub fn physical(size: &[i64], scale: f64) -> Option<String> {
    let [w, h] = [size.first()?, size.get(1)?].map(|v| ((*v as f64 * scale).round() as i64) & !1);
    if w < 240 || h < 240 {
        return None;
    }
    Some(format!("{w}x{h}"))
}
/// The size to launch a fit stream at: the exact size last fitted for this
/// monitor and workspace, or the monitor's full size as a first guess that the
/// one-time correction then trims to the real window. Returns the memory key.
pub async fn predict(
    learned: &BTreeMap<String, String>,
    initial: &str,
) -> Result<(String, String)> {
    let monitors = monitors().await?;
    let monitor = monitors.iter().find(|m| m.focused).unwrap_or(&monitors[0]);
    let key = fit_key(&monitor.name, monitor.active_workspace);
    if let Some(known) = learned.get(&key) {
        return Ok((key, known.clone()));
    }
    Ok((key, initial.to_string()))
}
pub async fn observe() -> Result<watch::Receiver<Vec<Window>>> {
    let (tx, rx) = watch::channel(Vec::new());
    let Some(instance) = std::env::var_os("HYPRLAND_INSTANCE_SIGNATURE") else {
        return Ok(rx);
    };
    let Some(runtime) = std::env::var_os("XDG_RUNTIME_DIR") else {
        return Ok(rx);
    };
    let socket = PathBuf::from(runtime)
        .join("hypr")
        .join(instance)
        .join(".socket2.sock");
    // Existing windows must be known before accepting connect requests.
    tx.send_replace(snapshot().await?);
    tokio::spawn(async move {
        loop {
            if let Ok(stream) = UnixStream::connect(&socket).await {
                // Subscribe before reading to avoid missing a window opened
                // between the initial snapshot and event subscription.
                if let Ok(windows) = snapshot().await {
                    tx.send_replace(windows);
                }
                let mut lines = BufReader::new(stream).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    let event = line.split(">>").next().unwrap_or("");
                    if [
                        "openwindow",
                        "closewindow",
                        "movewindow",
                        "movewindowv2",
                        "activewindow",
                        "activewindowv2",
                        "workspace",
                        "workspacev2",
                        "fullscreen",
                        "windowtitle",
                        "windowtitlev2",
                        "changefloatingmode",
                    ]
                    .contains(&event)
                    {
                        tokio::time::sleep(Duration::from_millis(50)).await;
                        // Coalesce a bounded burst into one snapshot. No
                        // per-window or per-frame compositor subprocesses.
                        for _ in 0..128 {
                            if !matches!(
                                tokio::time::timeout(Duration::from_millis(1), lines.next_line())
                                    .await,
                                Ok(Ok(Some(_)))
                            ) {
                                break;
                            }
                        }
                        if let Ok(windows) = snapshot().await {
                            tx.send_if_modified(|old| {
                                if *old == windows {
                                    false
                                } else {
                                    *old = windows;
                                    true
                                }
                            });
                        }
                    }
                }
            }
            if let Ok(windows) = snapshot().await {
                tx.send_replace(windows);
            }
            tokio::time::sleep(Duration::from_secs(15)).await;
        }
    });
    Ok(rx)
}
fn lua_string(value: &str) -> String {
    format!(
        "\"{}\"",
        value
            .bytes()
            .map(|b| format!("\\{b:03}"))
            .collect::<String>()
    )
}
fn lua_window_id(value: &str) -> Result<u64> {
    // Hyprland's clients JSON uses hexadecimal text (e.g. "180000e1").
    // hl.get_windows() exposes stable_id as a Lua number in 0.56 and as that
    // same hexadecimal text in 0.57; `identity_check` accepts both.
    u64::from_str_radix(value, 16).context("invalid Hyprland stable window ID")
}
pub async fn action(window: &Window, action: &str) -> Result<()> {
    let dispatch = match action {
        "focus" => "hl.dsp.focus({window='address:'..w.address})",
        "close" => "hl.dsp.window.close({window='address:'..w.address})",
        "inhibit" => {
            "hl.dsp.window.set_prop({window='address:'..w.address,prop='idle_inhibit',value='always'})"
        }
        "uninhibit" => {
            "hl.dsp.window.set_prop({window='address:'..w.address,prop='idle_inhibit',value='none'})"
        }
        action if action.starts_with("workspace:") => {
            // Return the window to the workspace it was on before a refit restart.
            let id: i64 = action[10..].parse().context("invalid workspace id")?;
            return dispatch_checked(
                window,
                &format!("hl.dsp.window.move({{window='address:'..w.address,workspace={id},follow=false}})"),
            )
            .await;
        }
        _ => bail!("unsupported window action"),
    };
    dispatch_checked(window, dispatch).await
}
pub fn identity_lost(error: &anyhow::Error) -> bool {
    error.to_string().contains("window identity changed")
}
/// Tag the window and, when `fullscreen` is set, apply that mode once.
/// `None` leaves the compositor's current fullscreen state alone.
pub async fn initialize(window: &Window, computer: &str, fullscreen: Option<bool>) -> Result<()> {
    let tag = lua_string(&format!("+remote-desktops-{computer}"));
    dispatch_checked(
        window,
        &format!("hl.dsp.window.tag({{window='address:'..w.address,tag={tag}}})"),
    )
    .await?;
    if let Some(fullscreen) = fullscreen {
        let mode = if fullscreen { 2 } else { 0 };
        dispatch_checked(window, &format!("hl.dsp.window.fullscreen_state({{window='address:'..w.address,internal={mode},client={mode},action='set'}})")).await?;
    }
    Ok(())
}
/// Lua that runs `dispatch` only on the window whose every identity field
/// still matches. Comparing a 0.57 string stable_id with a number is always
/// false in Lua, which made every live window look replaced and left the
/// stream window unadopted; normalize it to a number first.
fn identity_check(window: &Window, dispatch: &str) -> Result<String> {
    Ok(format!(
        "for _,w in ipairs(hl.get_windows()) do if w.address=={} and w.pid=={} and (type(w.stable_id)=='string' and tonumber(w.stable_id,16) or w.stable_id)=={} and w.class=={} and w.title=={} then local r=hl.dispatch({dispatch}); if type(r)=='table' and r.error then error(r.error) end; return true end end; error('remote window identity changed')",
        lua_string(&window.address),
        window.pid,
        lua_window_id(&window.stable_id)?,
        lua_string(&window.class),
        lua_string(&window.title)
    ))
}
async fn dispatch_checked(window: &Window, dispatch: &str) -> Result<()> {
    // Revalidate all identity fields inside the compositor, atomically with
    // the dispatch. Never act on a recycled address based on a cached snapshot.
    let code = identity_check(window, dispatch)?;
    let result = tokio::time::timeout(
        Duration::from_secs(3),
        command()
            .stderr(Stdio::piped())
            .args(["eval", &code])
            .output(),
    )
    .await
    .context("window action timed out")??;
    let stdout = String::from_utf8_lossy(&result.stdout);
    let stderr = String::from_utf8_lossy(&result.stderr);
    let text = format!("{stdout}{stderr}");
    if text.to_lowercase().contains("window identity changed") {
        bail!("window identity changed");
    }
    if !result.status.success() || text.to_lowercase().contains("error") {
        let detail = text
            .lines()
            .map(str::trim)
            .rfind(|line| !line.is_empty())
            .unwrap_or("compositor rejected the action");
        let detail: String = detail.chars().take(240).collect();
        bail!("compositor rejected the window action: {detail}");
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn physical_size_rounds_to_even_and_applies_scale() {
        assert_eq!(physical(&[1201, 801], 1.0).as_deref(), Some("1200x800"));
        assert_eq!(physical(&[1200, 800], 1.25).as_deref(), Some("1500x1000"));
        assert_eq!(physical(&[100, 800], 1.0), None);
        assert_eq!(physical(&[1200], 1.0), None);
        assert_eq!(fit_key("DP-1", 4), "DP-1:4");
    }
    #[test]
    fn full_monitor_uses_physical_pixels_and_rotation() {
        let mut m = serde_json::json!({"width":6144,"height":2560,"scale":2.0,"transform":0});
        assert_eq!(monitor_resolution(&m).unwrap(), "6144x2560");
        m["transform"] = serde_json::json!(1);
        assert_eq!(monitor_resolution(&m).unwrap(), "2560x6144");
        m["width"] = serde_json::json!(0);
        assert!(monitor_resolution(&m).is_err());
    }
    #[test]
    fn stream_class_accepts_qt_and_sdl_app_ids() {
        assert!(stream_class(CLASS));
        assert!(stream_class("moonlight"));
        assert!(stream_class("moonlight-qt"));
        assert!(!stream_class("kitty"));
        assert!(!stream_class(""));
    }
    #[test]
    fn lua_strings_never_interpolate_code() {
        assert_eq!(lua_string("'\n"), "\"\\039\\010\"");
    }
    #[test]
    fn compositor_json_ids_match_lua_numeric_ids() {
        assert_eq!(lua_window_id("180000e1").unwrap(), 402653409);
        assert_eq!(lua_window_id("123").unwrap(), 291);
        assert!(lua_window_id("not-an-id").is_err());
        assert!(lua_window_id("1; error('injected')").is_err());
    }
    /// Run the identity check against a fake `hl` whose single window has the
    /// given Lua `stable_id` literal. Returns the interpreter's output.
    fn run_identity_check(stable_id: &str) -> (bool, String) {
        let window = Window {
            address: "0x5633ed22be10".into(),
            pid: 35612,
            stable_id: "18000095".into(),
            class: CLASS.into(),
            title: "MacBook - Moonlight".into(),
            ..Default::default()
        };
        let check = identity_check(&window, "{tag='+remote-desktops-macbook'}").unwrap();
        let script = format!(
            "hl={{get_windows=function() return {{{{address='0x5633ed22be10',pid=35612,stable_id={stable_id},class='{CLASS}',title='MacBook - Moonlight'}}}} end, dispatch=function(a) print('dispatched '..a.tag) end}}\n\
             local ok,err=pcall(function() {check} end)\n\
             if not ok then print(err) os.exit(1) end"
        );
        // CI installs lua5.4; Hyprland itself links a system Lua.
        let output = ["lua5.4", "lua", "lua5.5"]
            .iter()
            .find_map(|lua| {
                std::process::Command::new(lua)
                    .args(["-e", &script])
                    .output()
                    .ok()
            })
            .expect("a Lua interpreter (lua5.4) is required to test compositor scripts");
        (
            output.status.success(),
            String::from_utf8_lossy(&output.stdout).into_owned(),
        )
    }
    #[test]
    fn identity_check_accepts_hyprland_0_57_string_stable_ids() {
        // Hyprland 0.57.1 returns stable_id as hex text, the same as clients JSON.
        let (ok, text) = run_identity_check("'18000095'");
        assert!(ok, "{text}");
        assert!(
            text.contains("dispatched +remote-desktops-macbook"),
            "{text}"
        );
    }
    #[test]
    fn identity_check_accepts_hyprland_0_56_numeric_stable_ids() {
        let (ok, text) = run_identity_check("0x18000095");
        assert!(ok, "{text}");
        assert!(
            text.contains("dispatched +remote-desktops-macbook"),
            "{text}"
        );
    }
    #[test]
    fn identity_check_rejects_a_replaced_window() {
        let (ok, text) = run_identity_check("'18000096'");
        assert!(!ok);
        assert!(text.contains("remote window identity changed"), "{text}");
        assert!(!text.contains("dispatched"), "{text}");
    }
}
