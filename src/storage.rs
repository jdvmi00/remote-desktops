use anyhow::{Context, Result, bail};
use fs2::FileExt;
use serde::{Serialize, de::DeserializeOwned};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
};

#[derive(Clone)]
pub struct Paths {
    pub state: PathBuf,
    pub runtime: PathBuf,
    pub config: PathBuf,
}

impl Paths {
    pub fn new() -> Result<Self> {
        let home = std::env::var_os("HOME").context("HOME is required")?;
        let base = |var: &str, fallback: &str| {
            std::env::var_os(var)
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from(&home).join(fallback))
        };
        Ok(Self {
            state: base("XDG_STATE_HOME", ".local/state").join("remote-desktops"),
            runtime: std::env::var_os("XDG_RUNTIME_DIR")
                .map(PathBuf::from)
                .context("XDG_RUNTIME_DIR is required")?
                .join("remote-desktops"),
            config: base("XDG_CONFIG_HOME", ".config").join("remote-desktops/computers.json"),
        })
    }
    pub fn session(&self, name: &str) -> PathBuf {
        self.state.join("sessions").join(name)
    }
    pub fn socket(&self) -> PathBuf {
        self.runtime.join("control.sock")
    }
    pub fn events(&self) -> PathBuf {
        self.runtime.join("events.sock")
    }
    pub fn legacy(&self) -> PathBuf {
        self.state.parent().unwrap().join("hypertile/streams")
    }
    pub fn init(&self) -> Result<()> {
        private_dir(&self.state)?;
        private_dir(&self.runtime)?;
        private_dir(&self.state.join("sessions"))
    }
}

pub fn valid_id(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name.as_bytes()[0].is_ascii_alphanumeric()
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
pub fn private_dir(path: &Path) -> Result<()> {
    fs::create_dir_all(path)?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
    Ok(())
}
pub fn lock(path: &Path, nonblocking: bool) -> Result<File> {
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .mode(0o600)
        .open(path)?;
    if nonblocking {
        file.try_lock_exclusive()?;
    } else {
        FileExt::lock_exclusive(&file)?;
    }
    Ok(file)
}
pub fn lock_contended(error: &anyhow::Error) -> bool {
    error
        .downcast_ref::<std::io::Error>()
        .is_some_and(|error| error.kind() == std::io::ErrorKind::WouldBlock)
}
pub fn read<T: DeserializeOwned>(path: &Path) -> Result<T> {
    serde_json::from_slice(&fs::read(path).with_context(|| format!("read {}", path.display()))?)
        .context("invalid state JSON")
}
pub fn write<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    write_bytes(path, &bytes)
}
pub fn write_bytes(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path.parent().context("state file needs a parent")?;
    let tmp = parent.join(format!(".write-{}", uuid::Uuid::new_v4()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&tmp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        fs::rename(&tmp, path)?;
        File::open(parent)?.sync_all()?;
        Ok(())
    })();
    let _ = fs::remove_file(tmp);
    result
}
pub fn check_legacy(paths: &Paths, pairing: &str) -> Result<()> {
    let path = paths.legacy().join("state.json");
    if !path.exists() {
        return Ok(());
    }
    let value: serde_json::Value = read(&path).context("cannot verify Hypertile handoff")?;
    if value["version"] != 1 {
        bail!("unsupported Hypertile state; explicit handoff required");
    }
    let records = value["computers"]
        .as_object()
        .context("invalid Hypertile state")?;
    for record in records.values() {
        if record["config"]["pairing_uuid"]
            .as_str()
            .is_some_and(|id| id.eq_ignore_ascii_case(pairing))
            && (record["desired"] == true
                || record["journal"].as_object().is_some_and(|j| !j.is_empty()))
        {
            bail!("handoff-required: disconnect and finish recovery in Hypertile first");
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ids_cannot_escape_state_root() {
        for name in ["../a", "", "-x", "a/b", "a;cmd"] {
            assert!(!valid_id(name));
        }
        assert!(valid_id("work-laptop"));
    }
    #[test]
    fn atomic_file_is_private_and_replaced() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("state.json");
        write(&p, &serde_json::json!({"version":1})).unwrap();
        write(&p, &serde_json::json!({"version":2})).unwrap();
        assert_eq!(read::<serde_json::Value>(&p).unwrap()["version"], 2);
        assert_eq!(fs::metadata(p).unwrap().permissions().mode() & 0o777, 0o600);
    }
}
