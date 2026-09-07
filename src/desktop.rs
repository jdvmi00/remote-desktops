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
    // Hyprland's clients JSON uses hexadecimal text (e.g. "180000e1"),
    // while hl.get_windows() exposes the same stable_id as a Lua number.
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
pub async fn initialize(window: &Window, computer: &str) -> Result<()> {
    let tag = lua_string(&format!("+remote-desktops-{computer}"));
    dispatch_checked(
        window,
        &format!("hl.dsp.window.tag({{window='address:'..w.address,tag={tag}}})"),
    )
    .await?;
    dispatch_checked(window, "hl.dsp.window.fullscreen_state({window='address:'..w.address,internal=0,client=0,action='set'})").await
}
async fn dispatch_checked(window: &Window, dispatch: &str) -> Result<()> {
    // Revalidate all identity fields inside the compositor, atomically with
    // the dispatch. Never act on a recycled address based on a cached snapshot.
    let code = format!(
        "for _,w in ipairs(hl.get_windows()) do if w.address=={} and w.pid=={} and w.stable_id=={} and w.class=={} and w.title=={} then local r=hl.dispatch({dispatch}); if type(r)=='table' and r.error then error(r.error) end; return true end end; error('remote window identity changed')",
        lua_string(&window.address),
        window.pid,
        lua_window_id(&window.stable_id)?,
        lua_string(&window.class),
        lua_string(&window.title)
    );
    let result = tokio::time::timeout(
        Duration::from_secs(3),
        command().args(["eval", &code]).output(),
    )
    .await
    .context("window action timed out")??;
    if !result.status.success()
        || String::from_utf8_lossy(&result.stdout)
            .to_lowercase()
            .contains("error")
    {
        bail!("window action failed: window may have closed");
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
}
