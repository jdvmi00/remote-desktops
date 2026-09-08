//! Optional compositor integration. It changes no session or host configuration.
use crate::{desktop, storage, windowrule};
use anyhow::{Context, Result, bail};
use clap::Subcommand;
use serde_json::{Value, json};
use std::{
    collections::hash_map::DefaultHasher,
    fs,
    hash::{Hash, Hasher},
    io::{self, Read},
};

#[derive(Subcommand)]
pub enum Action {
    /// Read the shared local-command prefix and its configuration revision.
    Status,
    /// Validate and apply JSON {enabled,prefix,timeout,revision} from stdin.
    Save,
}
const BEGIN: &str = "-- remote-desktops: keyboard begin";
const END: &str = "-- remote-desktops: keyboard end";
const META: &str = "-- keyboard-settings: ";
const DESCRIPTION: &str = "Remote Desktops: local-command prefix";

fn revision(text: &str) -> String {
    let mut h = DefaultHasher::new();
    text.hash(&mut h);
    format!("{:016x}", h.finish())
}
fn strip(text: &str) -> Result<(String, Option<Value>)> {
    let mut rest = String::new();
    let mut inside = false;
    let mut settings = None;
    let mut seen = false;
    for line in text.split_inclusive('\n') {
        let bare = line.trim_end_matches(['\r', '\n']);
        if bare == BEGIN {
            if seen {
                bail!("Duplicate keyboard settings block; configuration was not changed.");
            }
            inside = true;
            seen = true;
        } else if bare == END {
            if !inside || settings.is_none() {
                bail!("Incomplete keyboard settings block; configuration was not changed.");
            }
            inside = false;
        } else if inside {
            if let Some(meta) = bare.strip_prefix(META) {
                if settings.is_some() {
                    bail!("Duplicate keyboard metadata.");
                }
                settings = Some(serde_json::from_str(meta).context("Invalid keyboard metadata")?);
            }
        } else {
            rest.push_str(line);
        }
    }
    if inside {
        bail!("Incomplete keyboard settings block; configuration was not changed.");
    }
    Ok((rest, settings))
}
fn shortcut(text: &str) -> Result<(String, u64, String)> {
    let parts: Vec<_> = text.split('+').map(|s| s.trim().to_uppercase()).collect();
    let key = parts.last().context("Choose a prefix shortcut.")?.clone();
    let mut mask = 0;
    for p in &parts[..parts.len() - 1] {
        let bit = match p.as_str() {
            "SUPER" => 64,
            "CTRL" => 4,
            "ALT" => 8,
            "SHIFT" => 1,
            _ => bail!("Use Super, Ctrl, Alt, or Shift modifiers."),
        };
        if mask & bit != 0 {
            bail!("A modifier is repeated.");
        }
        mask |= bit;
    }
    let function = key
        .strip_prefix('F')
        .and_then(|n| n.parse::<u8>().ok())
        .is_some_and(|n| (1..=12).contains(&n));
    let character = key.len() == 1 && key.bytes().all(|c| c.is_ascii_alphanumeric());
    if !(function
        || key == "PAUSE"
        || (mask != 0 && (character || key == "SPACE" || key == "ESCAPE")))
    {
        bail!("Use F1–F12, Pause, or modifiers with a letter, number, Space, or Escape.");
    }
    if function && mask & 12 == 12 {
        bail!("Ctrl+Alt with function keys is reserved for switching system consoles.");
    }
    if mask & 13 == 13 {
        bail!("Ctrl+Alt+Shift is reserved for Moonlight's own controls.");
    }
    Ok((parts.join(" + "), mask, key))
}
fn conflicts(binds: &Value, mask: u64, key: &str) -> Option<String> {
    // Reject existing bindings even when disabled; they may become active later.
    binds
        .as_array()?
        .iter()
        .find(|b| {
            b["description"] != DESCRIPTION
                && b["description"] != "Remote Desktops: cancel local command"
                && b["modmask"].as_u64() == Some(mask)
                && (b["key"]
                    .as_str()
                    .is_some_and(|k| k.eq_ignore_ascii_case(key))
                    || b["keycode"].as_u64().is_some_and(|c| {
                        c != 0 && (keycode(key).is_none() || keycode(key) == Some(c))
                    }))
        })
        .map(|b| {
            b["description"]
                .as_str()
                .filter(|s| !s.is_empty())
                .unwrap_or("an existing Hyprland shortcut")
                .to_owned()
        })
}
fn keycode(key: &str) -> Option<u64> {
    // Standard XKB physical codes for offered unmodified prefix keys.
    match key {
        "ESCAPE" => Some(9),
        "SPACE" => Some(65),
        "PAUSE" => Some(127),
        "F11" => Some(95),
        "F12" => Some(96),
        _ => key
            .strip_prefix('F')
            .and_then(|n| n.parse::<u64>().ok())
            .filter(|n| (1..=10).contains(n))
            .map(|n| 66 + n),
    }
}
fn block(settings: &Value) -> String {
    let script = include_str!("../integrations/local-command.lua").replace(
        "install(PREFIX, TIMEOUT)",
        &format!("install({}, {})", settings["prefix"], settings["timeout"]),
    );
    format!("{BEGIN}\n{META}{settings}\ndo\n{script}end\n{END}\n")
}
async fn status(text: Option<&str>) -> Result<Value> {
    let (_, saved) = strip(text.unwrap_or_default())?;
    if let Some(settings) = &saved {
        if !settings.is_object()
            || !settings["enabled"].is_boolean()
            || settings["prefix"].as_str().is_none()
            || settings["timeout"]
                .as_u64()
                .filter(|n| (2..=15).contains(n))
                .is_none()
        {
            bail!("Invalid saved keyboard settings. Check the managed keyboard block.");
        }
        shortcut(settings["prefix"].as_str().unwrap())?;
    }
    let available = text.is_some() && desktop::control(&["version"]).await.is_ok();
    let mut result = saved.unwrap_or_else(|| json!({"enabled":false,"prefix":"F12","timeout":5}));
    result["available"] = json!(available);
    result["revision"] = json!(revision(text.unwrap_or_default()));
    Ok(result)
}
pub async fn run(action: &Action) -> Result<Value> {
    let path = windowrule::config()?;
    if matches!(action, Action::Status) {
        return status(windowrule::read(&path)?.as_deref()).await;
    }
    let mut input = String::new();
    io::stdin().take(8193).read_to_string(&mut input)?;
    if input.len() > 8192 {
        bail!("Keyboard settings request too large.");
    }
    let draft: Value = serde_json::from_str(&input).context("Invalid keyboard settings JSON")?;
    let enabled = draft["enabled"]
        .as_bool()
        .context("Choose whether to enable the prefix.")?;
    let (prefix, mask, key) = shortcut(
        draft["prefix"]
            .as_str()
            .context("Choose a prefix shortcut.")?,
    )?;
    let timeout = draft["timeout"]
        .as_u64()
        .filter(|n| (2..=15).contains(n))
        .context("Cancellation timeout must be between 2 and 15 seconds.")?;
    let _lock = storage::lock(&path.with_extension("lua.remote-desktops.lock"), true)
        .context("Another desktop settings edit is in progress.")?;
    let text = windowrule::read(&path)?
        .context("This option requires a running Hyprland 0.55+ Lua session.")?;
    if draft["revision"].as_str() != Some(&revision(&text)) {
        bail!("Desktop settings changed elsewhere. Reload these settings and try again.");
    }
    let (mut next, _) = strip(&text)?;
    if enabled {
        let binds: Value = serde_json::from_str(&desktop::control(&["-j", "binds"]).await?)?;
        if let Some(description) = conflicts(&binds, 0, "ESCAPE") {
            bail!(
                "Escape is already used by {description}. The local-command prefix needs Escape for cancellation; existing shortcuts were not changed."
            );
        }
        if let Some(description) = conflicts(&binds, mask, &key) {
            bail!(
                "{prefix} is already used by {description}. Choose another prefix; existing shortcuts were not changed."
            );
        }
    }
    let settings = json!({"enabled":enabled,"prefix":prefix,"timeout":timeout});
    if !next.is_empty() && !next.ends_with('\n') {
        next.push('\n');
    }
    // Keep disabled preferences editable, but load no handlers while disabled.
    if enabled {
        next.push_str(&block(&settings));
    } else {
        next.push_str(&format!("{BEGIN}\n{META}{settings}\n{END}\n"));
    }
    let backup = path.with_extension("lua.remote-desktops-keyboard.bak");
    if !backup.exists() {
        fs::write(&backup, &text)?;
    }
    desktop::control(&[
        "eval",
        "if remote_desktops_prefix then remote_desktops_prefix.cleanup() end",
    ])
    .await?;
    windowrule::apply(&path, &text, &next).await?;
    status(Some(&next)).await
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_conflicts_and_code_injection() {
        assert_eq!(
            shortcut("super + ctrl + k").unwrap(),
            ("SUPER + CTRL + K".into(), 68, "K".into())
        );
        for invalid in [
            "",
            "A",
            "Escape",
            "F13",
            "CTRL + CTRL + X",
            "F12); os.execute('x')",
            "CTRL + ALT + SHIFT + Z",
            "CTRL + ALT + F2",
        ] {
            assert!(shortcut(invalid).is_err(), "{invalid}");
        }
        let binds = json!([{"key":"ESCAPE","modmask":64,"description":"System menu"},{"keycode":96,"modmask":0,"description":"Existing F12"}]);
        assert_eq!(
            conflicts(&binds, 64, "ESCAPE").as_deref(),
            Some("System menu")
        );
        assert!(conflicts(&binds, 0, "F12").is_some());
        assert!(conflicts(&binds, 0, "F11").is_none());
    }
    #[test]
    fn preserves_surrounding_configuration_and_rejects_broken_blocks() {
        let settings = json!({"enabled":true,"prefix":"F12","timeout":5});
        let installed = format!("before\n{}after\n", block(&settings));
        assert_eq!(
            strip(&installed).unwrap(),
            ("before\nafter\n".into(), Some(settings))
        );
        for bad in [
            format!("{BEGIN}\nuser text"),
            format!("{END}\n"),
            format!("{BEGIN}\n{END}"),
            format!("{}{}", block(&json!({})), block(&json!({}))),
        ] {
            assert!(strip(&bad).is_err());
        }
    }
}
