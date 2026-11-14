use anyhow::{Context, Result, bail};
use serde_json::Value;
use std::{
    path::{Path, PathBuf},
    process::Stdio,
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    process::Command,
};

mod embedded {
    include!(concat!(env!("OUT_DIR"), "/helpers.rs"));
}
/// Directory holding the `remote_desktops` Python package. The helpers are
/// built into this binary and unpacked once per build, so an installed copy
/// never runs whatever a source checkout currently contains.
/// `REMOTE_DESKTOPS_HELPERS` points development and tests at a live tree.
pub fn helpers() -> Result<PathBuf> {
    if let Some(path) = std::env::var_os("REMOTE_DESKTOPS_HELPERS") {
        return Ok(PathBuf::from(path));
    }
    unpack(&crate::storage::Paths::new()?.runtime)
}
fn unpack(runtime: &Path) -> Result<PathBuf> {
    let target = runtime.join(format!("helpers-{}", embedded::ID));
    if target.join(".complete").exists() {
        return Ok(target);
    }
    crate::storage::private_dir(runtime)?;
    // Write a private staging copy and rename it into place: a concurrent
    // command sees either no snapshot or a complete one.
    let staging = runtime.join(format!(".helpers-{}", uuid::Uuid::new_v4()));
    let result = (|| -> Result<()> {
        for (name, bytes) in embedded::FILES {
            let path = staging.join(name);
            std::fs::create_dir_all(path.parent().context("helper file needs a parent")?)?;
            std::fs::write(path, bytes)?;
        }
        std::fs::write(staging.join(".complete"), embedded::ID)?;
        match std::fs::rename(&staging, &target) {
            // Another command finished the same snapshot first.
            Err(_) if target.join(".complete").exists() => Ok(()),
            // A directory without the marker is not a snapshot; replace it.
            Err(_) => {
                std::fs::remove_dir_all(&target)?;
                Ok(std::fs::rename(&staging, &target)?)
            }
            Ok(()) => Ok(()),
        }
    })();
    let _ = std::fs::remove_dir_all(&staging);
    result.context("unpack host helpers")?;
    Ok(target)
}
pub async fn call(request: Value) -> Result<Value> {
    let helpers = helpers()?;
    let mut child = Command::new("python3")
        .args(["-m", "remote_desktops.worker"])
        .current_dir(&helpers)
        .env("PYTHONPATH", &helpers)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        // Do not kill an in-flight host write if its caller is cancelled. The
        // helper owns a recovery-file lock and journals every mutation.
        .kill_on_drop(false)
        .spawn()
        .context("start host recovery helper")?;
    let mut input = child.stdin.take().unwrap();
    input.write_all(&serde_json::to_vec(&request)?).await?;
    drop(input);
    let mut output = Vec::new();
    // The Python transport has per-operation timeouts. Allow enough time for
    // a complete multi-step recovery; never discard a journal on timeout.
    tokio::time::timeout(
        Duration::from_secs(240),
        child
            .stdout
            .take()
            .unwrap()
            .take(2_000_001)
            .read_to_end(&mut output),
    )
    .await
    .context("host operation outcome uncertain; recovery retained")??;
    if output.len() > 2_000_000 {
        bail!("host response too large");
    }
    let status = child.wait().await?;
    if !status.success() {
        bail!("host helper exited; recovery retained");
    }
    let reply: Value = serde_json::from_slice(&output).context("invalid host helper reply")?;
    if reply["ok"] != true {
        bail!(
            "{}",
            reply["error"].as_str().unwrap_or("host operation failed")
        );
    }
    Ok(reply["result"].clone())
}
pub async fn operation(path: &Path, name: &str) -> Result<Value> {
    call(serde_json::json!({"operation":name,"path":path})).await
}
pub fn pending(path: &Path) -> Result<bool> {
    let record: Value = crate::storage::read(path)?;
    journal_pending(&record)
}
pub fn journal_pending(record: &Value) -> Result<bool> {
    Ok(!record["journal"]
        .as_object()
        .context("invalid recovery journal; recovery retained")?
        .is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn helpers_unpack_once_into_a_snapshot_named_after_their_content() {
        let runtime = tempfile::tempdir().unwrap();
        let first = unpack(runtime.path()).unwrap();
        assert_eq!(
            first.file_name().unwrap().to_string_lossy(),
            format!("helpers-{}", embedded::ID)
        );
        let worker = first.join("remote_desktops/worker.py");
        let source = concat!(env!("CARGO_MANIFEST_DIR"), "/remote_desktops/worker.py");
        assert_eq!(
            std::fs::read(&worker).unwrap(),
            std::fs::read(source).unwrap()
        );
        assert!(first.join("remote_desktops/windows/Guard.ps1").exists());
        // A directory without the marker is replaced by a real snapshot.
        let broken = tempfile::tempdir().unwrap();
        std::fs::create_dir(broken.path().join(format!("helpers-{}", embedded::ID))).unwrap();
        let repaired = unpack(broken.path()).unwrap();
        assert!(repaired.join("remote_desktops/worker.py").exists());
        // A complete snapshot is reused as it is, never rewritten.
        std::fs::write(&worker, "# marker").unwrap();
        assert_eq!(unpack(runtime.path()).unwrap(), first);
        assert_eq!(std::fs::read_to_string(&worker).unwrap(), "# marker");
        let staging: Vec<_> = std::fs::read_dir(runtime.path())
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .filter(|name| name.to_string_lossy().starts_with(".helpers-"))
            .collect();
        assert!(staging.is_empty());
    }
}
