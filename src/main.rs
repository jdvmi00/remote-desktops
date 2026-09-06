mod desktop;
mod host;
mod server;
mod storage;
mod supervisor;
use anyhow::{Result, bail};
use clap::{Parser, Subcommand};
use serde_json::json;
use std::{os::unix::process::CommandExt, path::PathBuf, process::Stdio, time::Duration};

#[derive(Parser)]
#[command(
    version,
    about = "Manage Moonlight remote desktops independently of window layouts"
)]
struct Cli {
    #[arg(long, global = true)]
    json: bool,
    #[command(subcommand)]
    command: Action,
}
#[derive(Subcommand)]
enum Action {
    /// Run the per-user controller; closing a CLI does not stop it.
    Daemon,
    Connect {
        computer: String,
        #[arg(long)]
        profile: Option<String>,
    },
    Disconnect {
        computer: String,
    },
    Reconnect {
        computer: String,
    },
    Restore {
        computer: String,
    },
    Release {
        computer: String,
        #[arg(long)]
        keep_host_settings: bool,
    },
    Focus {
        computer: String,
    },
    Status {
        computer: Option<String>,
    },
    Computers,
    #[command(hide = true)]
    Supervise {
        #[arg(long)]
        directory: PathBuf,
        #[arg(long)]
        token: String,
        #[arg(long)]
        runtime: PathBuf,
    },
}
fn main() {
    // All state, socket and helper-created files are private to this user.
    unsafe {
        libc::umask(0o077);
    }
    let cli = Cli::parse();
    let result = if let Action::Supervise {
        directory,
        token,
        runtime,
    } = &cli.command
    {
        supervisor::run(directory, token, runtime)
    } else {
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .unwrap()
            .block_on(run(cli))
    };
    if let Err(error) = result {
        eprintln!("remote-desktops: {error:#}");
        std::process::exit(1);
    }
}
async fn run(cli: Cli) -> Result<()> {
    let paths = storage::Paths::new()?;
    if matches!(cli.command, Action::Daemon) {
        return server::serve(paths).await;
    }
    if matches!(cli.command, Action::Computers) {
        let value = host::call(json!({"operation":"validate","config":paths.config})).await?;
        let entries=value.as_object().unwrap().iter().map(|(name,c)|json!({"computer":name,"profiles":c["profiles"].as_object().unwrap().keys().collect::<Vec<_>>()})).collect::<Vec<_>>();
        println!("{}", serde_json::to_string_pretty(&entries)?);
        return Ok(());
    }
    let payload = match &cli.command {
        Action::Connect { computer, profile } => {
            json!({"command":"connect","computer":computer,"profile":profile})
        }
        Action::Disconnect { computer } => json!({"command":"disconnect","computer":computer}),
        Action::Reconnect { computer } => json!({"command":"reconnect","computer":computer}),
        Action::Restore { computer } => json!({"command":"restore","computer":computer}),
        Action::Release {
            computer,
            keep_host_settings,
        } => {
            json!({"command":"release","computer":computer,"keep_host_settings":keep_host_settings})
        }
        Action::Focus { computer } => json!({"command":"focus","computer":computer}),
        Action::Status { computer } => json!({"command":"status","computer":computer}),
        _ => unreachable!(),
    };
    if matches!(
        cli.command,
        Action::Connect { .. }
            | Action::Disconnect { .. }
            | Action::Restore { .. }
            | Action::Reconnect { .. }
    ) && tokio::net::UnixStream::connect(paths.socket())
        .await
        .is_err()
    {
        paths.init()?;
        let log = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(paths.state.join("daemon.log"))?;
        let mut command = tokio::process::Command::new(std::env::current_exe()?);
        command
            .arg("daemon")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(log);
        command.as_std_mut().process_group(0);
        let mut child = command.spawn()?;
        let mut ready = false;
        for _ in 0..50 {
            // A concurrent CLI may win the daemon lock. Its socket is still
            // the right destination even when our own child exits first.
            let _ = child.try_wait()?;
            if tokio::net::UnixStream::connect(paths.socket())
                .await
                .is_ok()
            {
                ready = true;
                break;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        if !ready {
            bail!(
                "daemon startup timed out; see {}",
                paths.state.join("daemon.log").display()
            );
        }
    }
    let result = server::request(&paths, &payload).await?;
    if cli.json {
        println!("{}", serde_json::to_string_pretty(&result)?);
    } else if let Some(records) = result["computers"].as_array() {
        for r in records {
            println!(
                "{}\t{}\t{}",
                r["computer"].as_str().unwrap_or(""),
                r["phase"].as_str().unwrap_or(""),
                r["profile"].as_str().unwrap_or("")
            );
        }
    } else {
        println!("{}", serde_json::to_string_pretty(&result)?);
    }
    Ok(())
}
