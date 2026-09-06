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

pub fn helpers() -> PathBuf {
    std::env::var_os("REMOTE_DESKTOPS_HELPERS")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")))
}
pub async fn call(request: Value) -> Result<Value> {
    let mut child = Command::new("python3")
        .args(["-m", "remote_desktops.worker"])
        .current_dir(helpers())
        .env("PYTHONPATH", helpers())
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
