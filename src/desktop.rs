use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{path::PathBuf, process::Stdio, time::Duration};
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
            })
        })
        .collect())
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
        _ => bail!("unsupported window action"),
    };
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
