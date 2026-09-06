use crate::{
    desktop, host,
    storage::{self, Paths},
};
use anyhow::{Context, Result, bail};
use clap::Subcommand;
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
};

#[derive(Subcommand)]
pub enum Action {
    /// List configured computers and exact window matching metadata.
    List,
    /// Install or update a per-computer desktop entry in the user's launcher.
    Install { computer: String },
    /// Remove only the desktop entry generated for this computer.
    Remove { computer: String },
}
pub fn identity(name: &str, config: &Value) -> Value {
    json!({"desktop_id":format!("remote-desktops-{name}.desktop"),
        "match":{"class":desktop::CLASS,"title":config["title"],"tag":format!("remote-desktops-{name}")}})
}
fn applications() -> Result<PathBuf> {
    Ok(std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .unwrap_or(
            PathBuf::from(std::env::var_os("HOME").context("HOME is required")?)
                .join(".local/share"),
        )
        .join("applications"))
}
fn value(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}
fn exec_arg(s: &str) -> Result<String> {
    if s.chars().any(char::is_control) {
        bail!("launcher argument contains a control character");
    }
    let mut quoted = String::from("\"");
    for c in s.chars() {
        match c {
            '%' => quoted.push_str("%%"),
            '\\' | '"' | '$' | '`' => {
                quoted.push('\\');
                quoted.push(c);
            }
            _ => quoted.push(c),
        }
    }
    quoted.push('"');
    // Desktop string escaping is applied before Exec argument unquoting.
    Ok(value(&quoted))
}
fn entry(binary: &Path, name: &str, config: &Value) -> Result<String> {
    let title = config["title"].as_str().context("missing window title")?;
    let label = config["name"]
        .as_str()
        .unwrap_or_else(|| title.strip_suffix(" - Moonlight").unwrap_or(title));
    let executable = exec_arg(binary.to_str().context("executable path is not UTF-8")?)?;
    let computer = exec_arg(name)?;
    Ok(format!(
        "[Desktop Entry]\nType=Application\nName={} (Remote Desktop)\nComment=Open this computer with Remote Desktops\nExec={executable} open {computer}\nIcon=computer\nTerminal=false\nStartupNotify=false\nCategories=Network;RemoteAccess;\nKeywords=Remote;Desktop;Moonlight;\nX-RemoteDesktops-Managed=true\nX-RemoteDesktops-Computer={name}\nX-RemoteDesktops-WindowClass={}\nX-RemoteDesktops-WindowTitle={}\n",
        value(label),
        desktop::CLASS,
        value(title)
    ))
    // No StartupWMClass: Moonlight hardcodes a shared Wayland app ID. Claiming
    // a distinct WM class here would misrepresent actual window identity.
}
fn owned(path: &Path, name: &str) -> Result<bool> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(m) => m,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(e) => return Err(e.into()),
    };
    if !metadata.is_file() {
        bail!("refusing to replace a non-file launcher");
    }
    let text = fs::read_to_string(path)?;
    if !text.lines().any(|s| s == "X-RemoteDesktops-Managed=true")
        || !text
            .lines()
            .any(|s| s == format!("X-RemoteDesktops-Computer={name}"))
    {
        bail!("launcher path belongs to another application; preserving it");
    }
    Ok(true)
}
pub async fn run(paths: &Paths, action: &Action) -> Result<Value> {
    let directory = applications()?;
    if let Action::Remove { computer } = action {
        if !storage::valid_id(computer) {
            bail!("invalid computer ID");
        }
        let path = directory.join(format!("remote-desktops-{computer}.desktop"));
        paths.init()?;
        let _lock = storage::lock(&paths.state.join("launchers.lock"), false)?;
        let removed = owned(&path, computer)?;
        if removed {
            fs::remove_file(&path)?;
        }
        return Ok(json!({"removed":removed,"path":path}));
    }
    let computers = host::call(json!({"operation":"validate","config":paths.config})).await?;
    if let Action::Install { computer } = action {
        if !storage::valid_id(computer) {
            bail!("invalid computer ID");
        }
        let config = computers.get(computer).context("unknown computer")?;
        fs::create_dir_all(&directory)?;
        let path = directory.join(format!("remote-desktops-{computer}.desktop"));
        // Serialize our own installers; never chmod the shared applications dir.
        paths.init()?;
        let _lock = storage::lock(&paths.state.join("launchers.lock"), false)?;
        owned(&path, computer)?;
        storage::write_bytes(
            &path,
            entry(&std::env::current_exe()?, computer, config)?.as_bytes(),
        )?;
        return Ok(json!({"installed":path,"launcher":identity(computer,config)}));
    }
    Ok(
        json!({"computers":computers.as_object().context("invalid computers")?.iter()
        .map(|(name,c)|json!({"computer":name,"launcher":identity(name,c),"installed":directory.join(format!("remote-desktops-{name}.desktop")).is_file()})).collect::<Vec<_>>()}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn desktop_exec_preserves_reserved_characters_without_a_shell() {
        assert_eq!(exec_arg("a b%f").unwrap(), "\"a b%%f\"");
        assert_eq!(exec_arg("$`").unwrap(), "\"\\\\$\\\\`\"");
        assert!(exec_arg("bad\ncommand").is_err());
    }
    #[test]
    fn unrelated_entries_and_symlinks_are_preserved() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("app.desktop");
        fs::write(&path, "[Desktop Entry]\nName=Someone else\n").unwrap();
        assert!(owned(&path, "test").is_err());
        let link = dir.path().join("link.desktop");
        std::os::unix::fs::symlink(&path, &link).unwrap();
        assert!(owned(&link, "test").is_err());
        assert!(fs::read_to_string(path).unwrap().contains("Someone else"));
    }
}
