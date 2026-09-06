//! Configuration editing is independent of session intent. Active sessions retain
//! their immutable config snapshot; edits apply to the next fresh connection.
use crate::{
    host,
    storage::{self, Paths},
};
use anyhow::{Context, Result, bail};
use clap::Subcommand;
use serde_json::{Value, json};
use std::{
    collections::hash_map::DefaultHasher,
    hash::{Hash, Hasher},
    io::{self, Read},
};

#[derive(Subcommand)]
pub enum Action {
    /// Read paired Moonlight computers and an opaque configuration revision.
    Catalog,
    /// Read editable settings without SSH or display-management details.
    Get { computer: String },
    /// Check a JSON draft from stdin without starting a stream or changing a display.
    Test,
    /// Atomically save a JSON draft from stdin; existing sessions keep their snapshot.
    Save,
    /// Remove a computer, its launcher entry, and its settled session record.
    Remove { computer: String },
}
// A session record is only dropped once nothing owns it: no desired intent,
// no live client, and no pending host recovery journal.
async fn forget(paths: &Paths, computer: &str) -> Result<()> {
    let directory = paths.session(computer);
    if !directory.join("session.json").exists() {
        return Ok(());
    }
    if tokio::net::UnixStream::connect(paths.socket())
        .await
        .is_ok()
    {
        crate::server::request(paths, &json!({"command":"forget","computer":computer})).await?;
        return Ok(());
    }
    // No service answers. Holding its writer lock proves none owns the record.
    let _writer = storage::lock(&paths.state.join("writer.lock"), true)
        .context("The service is running but not responding. Try again.")?;
    let record: Value = storage::read(&directory.join("session.json"))?;
    if record["desired"] == true {
        bail!("Disconnect this computer before removing it.");
    }
    let recovery = directory.join("recovery.json");
    if recovery.exists() && host::pending(&recovery)? {
        bail!("restore-pending: restore the host display before removing this computer");
    }
    if !matches!(record["phase"].as_str(), Some("idle" | "attention")) {
        bail!(
            "This computer is still finishing its last session. Wait until it is idle before removing it."
        );
    }
    std::fs::remove_dir_all(&directory)?;
    Ok(())
}
fn load(paths: &Paths) -> Result<Value> {
    match storage::read(&paths.config) {
        Ok(v) => Ok(v),
        Err(e) if !paths.config.exists() => {
            // Do not replace a dangling symlink or an inaccessible existing file.
            if paths.config.symlink_metadata().is_ok() {
                return Err(e);
            }
            Ok(json!({"version":1,"computers":{}}))
        }
        Err(e) => Err(e),
    }
}
fn revision(value: &Value) -> String {
    let mut hash = DefaultHasher::new();
    value.to_string().hash(&mut hash);
    format!("{:016x}", hash.finish())
}
fn editable(id: &str, c: &Value, rev: &str) -> Value {
    let profile = c["default_profile"].as_str().unwrap_or_else(|| {
        if c["profiles"].get("desktop").is_some() {
            "desktop"
        } else {
            c["profiles"].as_object().unwrap().keys().next().unwrap()
        }
    });
    let p = &c["profiles"][profile];
    json!({"computer":id,"revision":rev,"name":c["name"].as_str().unwrap_or_else(|| c["title"].as_str().unwrap_or(id).trim_end_matches(" - Moonlight")),
        "host":c["host"],"platform":c["platform"].as_str().unwrap_or("unknown"),
        "profile":profile,"profiles":c["profiles"],"stream_resolution":p["stream_resolution"],
        "fps":p.get("fps").unwrap_or(&json!(60)),"bitrate":p.get("bitrate").unwrap_or(&json!(60000)),
        "codec":p.get("codec").unwrap_or(&json!("HEVC")),"input":p.get("input").unwrap_or(&json!("absolute")),
        "audio":p.get("audio").unwrap_or(&json!("focus"))})
}
// Only the common stream settings cross the UI boundary. Display adapters and
// SSH details are deliberately omitted and preserved by the merge below.
fn redact_profiles(draft: &mut Value) {
    if let Some(profiles) = draft["profiles"].as_object_mut() {
        for p in profiles.values_mut() {
            p.as_object_mut().unwrap().retain(|k, _| {
                [
                    "stream_resolution",
                    "fps",
                    "bitrate",
                    "codec",
                    "input",
                    "audio",
                ]
                .contains(&k.as_str())
            });
        }
    }
}
async fn candidate(paths: &Paths, mut value: Value, draft: &Value) -> Result<Value> {
    if draft["revision"].as_str() != Some(&revision(&value)) {
        bail!("Settings changed elsewhere. Close setup and reopen it before saving.");
    }
    let id = draft["computer"].as_str().context("missing computer ID")?;
    if !storage::valid_id(id) {
        bail!("invalid computer ID");
    }
    let profile = draft["profile"].as_str().context("missing profile")?;
    let computers = value["computers"]
        .as_object_mut()
        .context("invalid computers schema")?;
    let mut computer = if let Some(old) = computers.get(id) {
        if draft.get("pairing_uuid").is_some() {
            bail!("Computer already exists; reopen it to edit.");
        }
        if old["profiles"].get(profile).is_none() {
            bail!("unknown profile");
        }
        old.clone()
    } else {
        let pairing = draft["pairing_uuid"]
            .as_str()
            .context("choose a paired computer")?;
        let hosts = host::call(json!({"operation":"paired"})).await?;
        let known = hosts
            .as_array()
            .context("invalid pairing list")?
            .iter()
            .find(|v| v["pairing_uuid"].as_str() == Some(pairing))
            .context("Pair this computer in Moonlight, then refresh setup.")?;
        // Reusing a removed computer's identity under a new ID could create a
        // second recovery owner. Require restoring its original configuration.
        let entries = match std::fs::read_dir(paths.state.join("sessions")) {
            Ok(entries) => Some(entries),
            Err(e) if e.kind() == io::ErrorKind::NotFound => None,
            Err(e) => return Err(e.into()),
        };
        if let Some(entries) = entries {
            for entry in entries {
                let entry = entry?;
                let saved = entry.path().join("session.json");
                if saved.exists() {
                    let record: Value = storage::read(&saved)?;
                    if record["config"]["pairing_uuid"]
                        .as_str()
                        .is_some_and(|p| p.eq_ignore_ascii_case(pairing))
                    {
                        bail!(
                            "This computer has a saved session. Restore its original configuration before adding it again."
                        );
                    }
                }
            }
        }
        json!({"pairing_uuid":pairing,"title":format!("{} - Moonlight", known["name"].as_str().context("Moonlight computer needs a name")?),
            "profiles":{profile:{"display":{"adapter":"external"},"decoder":"auto"}}})
    };
    for key in ["name", "host", "platform"] {
        computer[key] = draft[key].clone();
    }
    computer["default_profile"] = json!(profile);
    for key in [
        "stream_resolution",
        "fps",
        "bitrate",
        "codec",
        "input",
        "audio",
    ] {
        computer["profiles"][profile][key] = draft[key].clone();
    }
    computers.insert(id.into(), computer);
    host::call(json!({"operation":"validate-value","value":value})).await?;
    Ok(value)
}
pub async fn run(paths: &Paths, action: &Action) -> Result<Value> {
    let value = load(paths)?;
    host::call(json!({"operation":"validate-value","value":value})).await?;
    match action {
        Action::Catalog => {
            let mut paired = host::call(json!({"operation":"paired"})).await?;
            for item in paired.as_array_mut().context("invalid pairing list")? {
                item["configured"] =
                    json!(value["computers"].as_object().unwrap().values().any(|c| {
                        c["pairing_uuid"]
                            .as_str()
                            .zip(item["pairing_uuid"].as_str())
                            .is_some_and(|(a, b)| a.eq_ignore_ascii_case(b))
                    }));
            }
            Ok(json!({"revision":revision(&value),"paired":paired}))
        }
        Action::Get { computer } => {
            let c = value["computers"]
                .get(computer)
                .context("unknown computer")?;
            let mut result = editable(computer, c, &revision(&value));
            redact_profiles(&mut result);
            Ok(result)
        }
        Action::Remove { computer } => {
            if !storage::valid_id(computer) {
                bail!("invalid computer ID");
            }
            let configured = value["computers"].get(computer).is_some();
            if !configured && !paths.session(computer).join("session.json").exists() {
                bail!("unknown computer");
            }
            forget(paths, computer).await?;
            let launcher = crate::launcher::Action::Remove {
                computer: computer.clone(),
            };
            let launcher = match crate::launcher::run(paths, &launcher).await {
                Ok(v) => v["removed"].clone(),
                // A launcher file another application owns is preserved.
                Err(e) if e.to_string().contains("another application") => json!(false),
                Err(e) => return Err(e),
            };
            if configured {
                storage::private_dir(paths.config.parent().context("missing config directory")?)?;
                let _lock = storage::lock(&paths.config.with_extension("lock"), true)
                    .context("Another settings save is in progress. Try again.")?;
                if paths
                    .config
                    .symlink_metadata()
                    .is_ok_and(|m| m.file_type().is_symlink())
                {
                    bail!("Configuration is a symbolic link. Edit its source file directly.");
                }
                let mut next = load(paths)?;
                if next["computers"]
                    .as_object_mut()
                    .context("invalid computers schema")?
                    .remove(computer)
                    .is_some()
                {
                    host::call(json!({"operation":"validate-value","value":next})).await?;
                    storage::write(&paths.config, &next)?;
                }
            }
            Ok(json!({"removed":true,"computer":computer,"launcher":launcher}))
        }
        Action::Test | Action::Save => {
            let mut input = String::new();
            io::stdin().take(65537).read_to_string(&mut input)?;
            if input.len() > 65536 {
                bail!("settings request too large");
            }
            let draft: Value = serde_json::from_str(&input).context("invalid settings JSON")?;
            let next = candidate(paths, value, &draft).await?;
            if matches!(action, Action::Test) {
                // An external adapter makes this strictly a pairing/network/app
                // check, even when the saved profile manages the host display.
                let c = &next["computers"][draft["computer"].as_str().unwrap()];
                host::call(json!({"operation":"setup-probe","computer":c})).await?;
                Ok(
                    json!({"tested":true,"message":"Moonlight authenticated and found Desktop. Video and input are checked when you connect."}),
                )
            } else {
                storage::private_dir(paths.config.parent().context("missing config directory")?)?;
                let _lock = storage::lock(&paths.config.with_extension("lock"), true)
                    .context("Another settings save is in progress. Try again.")?;
                if revision(&load(paths)?) != draft["revision"].as_str().unwrap_or("") {
                    bail!("Settings changed elsewhere. Close setup and reopen it before saving.");
                }
                if paths
                    .config
                    .symlink_metadata()
                    .is_ok_and(|m| m.file_type().is_symlink())
                {
                    bail!("Configuration is a symbolic link. Edit its source file directly.");
                }
                storage::write(&paths.config, &next)?;
                Ok(json!({"saved":true,"computer":draft["computer"]}))
            }
        }
    }
}
