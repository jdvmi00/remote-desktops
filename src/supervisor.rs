use crate::{server::Session, storage};
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    fs::{self, File},
    io::{BufRead, BufReader, Read},
    os::{
        fd::{AsRawFd, FromRawFd, OwnedFd},
        unix::net::{UnixDatagram, UnixStream},
    },
    path::Path,
    process::{Command, Stdio},
};

pub const TOKEN: &str = "REMOTE_DESKTOPS_TOKEN";
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Job {
    pub token: String,
    pub supervisor: u32,
    pub pid: Option<u32>,
    pub ended: bool,
    pub success: bool,
    pub evidence: Value,
}
pub fn owned(pid: u32, token: &str) -> bool {
    if pid == 0 || token.len() != 32 {
        return false;
    }
    let path = format!("/proc/{pid}");
    let expected = format!("{TOKEN}={token}");
    fs::read(format!("{path}/environ"))
        .is_ok_and(|v| v.split(|b| *b == 0).any(|v| v == expected.as_bytes()))
        && fs::read_to_string(format!("{path}/stat")).is_ok_and(|v| !v.contains(") Z "))
}
pub fn signal(pid: u32, token: &str, force: bool) -> Result<()> {
    // pidfd pins the process identity before checking its environment, so PID
    // reuse between the check and signal cannot target an unrelated process.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if fd < 0 {
        return Ok(());
    }
    let file = unsafe { File::from_raw_fd(fd as i32) };
    if owned(pid, token) {
        let result = unsafe {
            libc::syscall(
                libc::SYS_pidfd_send_signal,
                file.as_raw_fd(),
                if force { libc::SIGKILL } else { libc::SIGTERM },
                std::ptr::null::<libc::siginfo_t>(),
                0,
            )
        };
        if result < 0 {
            let e = std::io::Error::last_os_error();
            if e.raw_os_error() != Some(libc::ESRCH) {
                return Err(e.into());
            }
        }
    }
    Ok(())
}
pub fn read_job(directory: &Path, token: &str) -> Job {
    storage::read(&directory.join(format!("job-{token}.json"))).unwrap_or_default()
}
pub fn alive(job: &Job) -> bool {
    job.pid.is_some_and(|pid| owned(pid, &job.token))
}
fn publish(directory: &Path, runtime: &Path, name: &str, job: &Job) -> Result<()> {
    storage::write(&directory.join(format!("job-{}.json", job.token)), job)?;
    if let Ok(socket) = UnixDatagram::unbound() {
        let _ = socket.send_to(name.as_bytes(), runtime.join("events.sock"));
    }
    Ok(())
}
pub fn log_event(line: &str) -> Option<Value> {
    if line.contains("://") || line.len() > 4096 {
        return None;
    }
    if line.contains("Quit event received") {
        return Some(json!({"quit":true}));
    }
    if let Some((_, tail)) = line.split_once("Connection terminated: ")
        && let Some(code) = tail
            .split_whitespace()
            .next()
            .and_then(|s| s.parse::<i32>().ok())
    {
        return Some(json!({"terminated":code}));
    }
    if let Some((_, tail)) = line.split_once("Video stream is ")
        && let Some(size) = tail.split_whitespace().next()
    {
        let values: Vec<u32> = size.split('x').filter_map(|n| n.parse().ok()).collect();
        if values.len() == 3 && values[0] <= 16384 && values[1] <= 16384 && values[2] <= 1000 {
            return Some(
                json!({"negotiated_video":{"width":values[0],"height":values[1],"fps":values[2]}}),
            );
        }
    }
    if line.contains("No video received from host") {
        return Some(json!({"error":"no-video"}));
    }
    None
}
pub fn run(directory: &Path, token: &str, runtime: &Path) -> Result<()> {
    let _job_lock = storage::lock(&directory.join(format!("job-{token}.lock")), true)?;
    let gate = storage::lock(&directory.join("gate.lock"), false)?;
    let record: Session = storage::read(&directory.join("session.json"))?;
    if !record.desired || record.token.as_deref() != Some(token) {
        return Ok(());
    }
    let name = directory
        .file_name()
        .context("session directory missing name")?
        .to_string_lossy();
    let mut job = Job {
        token: token.into(),
        supervisor: std::process::id(),
        evidence: json!({"video_ready":"unverified"}),
        ..Default::default()
    };
    publish(directory, runtime, &name, &job)?;
    let (reader, writer) = UnixStream::pair()?;
    let writer: File = OwnedFd::from(writer).into();
    let program = record.argv.first().context("missing client command")?;
    let mut command = Command::new(program);
    command
        .args(&record.argv[1..])
        .env(TOKEN, token)
        .stdin(Stdio::null())
        .stdout(writer.try_clone()?)
        .stderr(writer);
    let child = command.spawn();
    let mut child = match child {
        Ok(c) => c,
        Err(error) => {
            job.ended = true;
            job.evidence["error"] = json!("client-launch-failed");
            publish(directory, runtime, &name, &job)?;
            return Err(error.into());
        }
    };
    job.pid = Some(child.id());
    publish(directory, runtime, &name, &job)?;
    drop(gate);
    let supported = record.client_version.starts_with("6.1.");
    job.evidence["parser"] = json!(if supported {
        "moonlight-qt-6.1"
    } else {
        "unsupported-version"
    });
    let shutdown = reader.try_clone()?;
    let log_directory = directory.to_path_buf();
    let log_runtime = runtime.to_path_buf();
    let log_name = name.to_string();
    let logger = std::thread::spawn(move || -> Result<Job> {
        let directory = log_directory.as_path();
        let runtime = log_runtime.as_path();
        let name = log_name;
        let mut reader = BufReader::new(reader);
        loop {
            let mut bytes = Vec::new();
            let count = reader.by_ref().take(4096).read_until(b'\n', &mut bytes)?;
            if count == 0 {
                break;
            }
            if !bytes.ends_with(b"\n") {
                // Drain oversized/untrusted lines without accumulating their text.
                while !bytes.ends_with(b"\n") {
                    bytes.clear();
                    if reader.by_ref().take(4096).read_until(b'\n', &mut bytes)? == 0 {
                        break;
                    }
                }
                continue;
            }
            if supported && let Some(event) = log_event(&String::from_utf8_lossy(&bytes)) {
                for (key, value) in event.as_object().unwrap() {
                    job.evidence[key] = value.clone();
                }
                publish(directory, runtime, &name, &job)?;
            }
        }
        Ok(job)
    });
    let success = child.wait()?.success();
    // A helper may retain the output pipe after Moonlight exits. Client exit,
    // not logger EOF, determines session completion.
    let _ = shutdown.shutdown(std::net::Shutdown::Read);
    let mut job = logger
        .join()
        .map_err(|_| anyhow::anyhow!("logger failed"))??;
    job.success = success;
    job.ended = true;
    publish(directory, runtime, &name, &job)?;
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn logs_keep_only_typed_evidence() {
        assert_eq!(
            log_event("Video stream is 2560x1440x60 (format 0x100)").unwrap()["negotiated_video"]["fps"],
            60
        );
        assert!(log_event("Video stream is 2560x1440x60 https://host/?secret=SECRET").is_none());
        assert!(log_event("GET https://host/launch?rikey=SECRET").is_none());
        assert_eq!(
            log_event("Connection terminated: -100").unwrap()["terminated"],
            -100
        );
    }
    #[test]
    fn unrelated_process_is_never_owned() {
        assert!(!owned(
            std::process::id(),
            "00000000000000000000000000000000"
        ));
    }
}
