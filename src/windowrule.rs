//! A Hyprland window rule so Moonlight windows open tiled. Omarchy's default
//! opens them fullscreen; a later anonymous rule in the user's own config wins.
use crate::desktop;
use anyhow::{Context, Result, bail};
use clap::Subcommand;
use serde_json::{Value, json};
use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf};

#[derive(Subcommand)]
pub enum Action {
    /// Report whether Moonlight windows are set to open tiled.
    Status,
    /// Add a rule to the user's Hyprland config so Moonlight windows open tiled.
    Install,
    /// Remove only the rule this app added.
    Remove,
}
const BEGIN: &str =
    "-- remote-desktops: begin (managed; change with `remote-desktops window-rule`)";
const END: &str = "-- remote-desktops: end";
fn rule() -> String {
    format!(
        "hl.window_rule({{ match = {{ class = \"{}\" }}, fullscreen = false }})",
        desktop::CLASS
    )
}
pub fn config() -> Result<PathBuf> {
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .unwrap_or(
            PathBuf::from(std::env::var_os("HOME").context("HOME is required")?).join(".config"),
        );
    Ok(base.join("hypr/hyprland.lua"))
}
/// The text without the managed block, and whether a block was present.
fn strip(text: &str) -> (String, bool) {
    let mut out = String::new();
    let mut inside = false;
    let mut found = false;
    for line in text.split_inclusive('\n') {
        let bare = line.trim_end_matches(['\n', '\r']);
        if !inside && bare == BEGIN {
            inside = true;
            found = true;
            // The block is appended after one blank separator line.
            if out.ends_with("\n\n") {
                out.pop();
            }
            continue;
        }
        if inside {
            if bare == END {
                inside = false;
            }
            continue;
        }
        out.push_str(line);
    }
    (out, found)
}
/// A rule the user wrote by hand, outside the managed block.
fn manual(text: &str) -> bool {
    strip(text).0.lines().any(|line| {
        let line = line.trim_start();
        !line.starts_with("--")
            && line.contains(desktop::CLASS)
            && line.contains("fullscreen = false")
    })
}
fn status(path: &PathBuf, text: Option<&str>) -> Value {
    json!({"path":path,"available":text.is_some(),
        "installed":text.is_some_and(|t| strip(t).1),"manual":text.is_some_and(manual)})
}
fn read(path: &PathBuf) -> Result<Option<String>> {
    match fs::symlink_metadata(path) {
        Ok(m) if m.is_file() => Ok(Some(fs::read_to_string(path)?)),
        Ok(_) => bail!("refusing to edit {}: not a regular file", path.display()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e.into()),
    }
}
fn write(path: &PathBuf, text: &str) -> Result<()> {
    let mode = fs::metadata(path)?.permissions().mode();
    let tmp = path.with_extension(format!(
        "lua.remote-desktops-{}",
        uuid::Uuid::new_v4().simple()
    ));
    let result = (|| {
        fs::write(&tmp, text)?;
        fs::set_permissions(&tmp, fs::Permissions::from_mode(mode))?;
        fs::rename(&tmp, path)
    })();
    let _ = fs::remove_file(&tmp);
    Ok(result?)
}
/// Apply a config text, then make sure Hyprland still accepts its config;
/// otherwise put the previous text back so a broken config never persists.
async fn apply(path: &PathBuf, previous: &str, next: &str) -> Result<()> {
    let before = desktop::control(&["configerrors"]).await.context(
        "Hyprland is not running; the rule can only be changed inside a Hyprland session",
    )?;
    write(path, next)?;
    let _ = desktop::control(&["reload"]).await;
    let after = desktop::control(&["configerrors"])
        .await
        .unwrap_or_default();
    if after.trim() != before.trim() && !after.trim().is_empty() {
        write(path, previous)?;
        let _ = desktop::control(&["reload"]).await;
        bail!(
            "Hyprland rejected the change, so it was undone: {}",
            after.trim()
        );
    }
    Ok(())
}
pub async fn run(action: &Action) -> Result<Value> {
    let path = config()?;
    let current = read(&path)?;
    if let Action::Status = action {
        return Ok(status(&path, current.as_deref()));
    }
    let text = current.with_context(|| {
        format!(
            "Hyprland's Lua config was not found at {}; this needs Hyprland 0.55 or later",
            path.display()
        )
    })?;
    let (rest, had) = strip(&text);
    match action {
        Action::Install => {
            let backup = path.with_extension("lua.remote-desktops.bak");
            if !backup.exists() {
                fs::write(&backup, &text)?;
            }
            let mut next = rest;
            if !next.ends_with('\n') && !next.is_empty() {
                next.push('\n');
            }
            next.push_str(&format!("\n{BEGIN}\n{}\n{END}\n", rule()));
            apply(&path, &text, &next).await?;
        }
        Action::Remove => {
            if had {
                apply(&path, &text, &rest).await?;
            }
        }
        Action::Status => unreachable!(),
    }
    let text = read(&path)?;
    Ok(status(&path, text.as_deref()))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn managed_block_is_added_once_and_removed_exactly() {
        let original = "dofile(\"boot.lua\")\n\nhl.config({})\n";
        let installed = format!("{original}\n{BEGIN}\n{}\n{END}\n", rule());
        let (rest, had) = strip(&installed);
        assert!(had);
        assert_eq!(rest, original);
        assert!(!strip(original).1);
        // Text after the block is preserved; an unterminated block eats nothing after it.
        let trailing = format!("{installed}o.window(\"x\", {{}})\n");
        assert_eq!(
            strip(&trailing).0,
            format!("{original}o.window(\"x\", {{}})\n")
        );
        assert!(!manual(&installed));
        assert!(manual(
            "o.window(\"com.moonlight_stream.Moonlight\", { fullscreen = false })\n"
        ));
        assert!(!manual(
            "-- o.window(\"com.moonlight_stream.Moonlight\", { fullscreen = false })\n"
        ));
        assert!(!manual(
            "o.window(\"com.moonlight_stream.Moonlight\", { fullscreen = true })\n"
        ));
        let s = status(&PathBuf::from("/x"), Some(&installed));
        assert_eq!(s["installed"], true);
        assert_eq!(status(&PathBuf::from("/x"), None)["available"], false);
    }
}
