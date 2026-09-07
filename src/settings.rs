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
    /// List computers seen on Tailscale and the local network.
    Discover,
    /// Pair a host through Moonlight; JSON {"host","pin"} arrives on stdin.
    Pair,
    /// Read a host's displays over SSH for a JSON draft on stdin; changes nothing.
    Inspect,
    /// Install the Windows display helper for a JSON draft on stdin.
    InstallHelper,
}
fn read_stdin() -> Result<Value> {
    let mut input = String::new();
    io::stdin().take(65537).read_to_string(&mut input)?;
    if input.len() > 65536 {
        bail!("settings request too large");
    }
    serde_json::from_str(&input).context("invalid settings JSON")
}
// Host inspection needs the pairing identity and SSH details. An existing
// computer supplies them from its saved configuration; a draft may override
// the editable fields but never the identity of a saved computer.
fn subject(value: &Value, draft: &Value) -> Result<Value> {
    let id = draft["computer"].as_str().context("missing computer ID")?;
    if !storage::valid_id(id) {
        bail!("invalid computer ID");
    }
    let mut computer = value["computers"]
        .get(id)
        .cloned()
        .unwrap_or_else(|| json!({}));
    if computer.get("pairing_uuid").is_none() {
        computer["pairing_uuid"] = draft["pairing_uuid"].clone();
    }
    for key in ["host", "platform", "adapter", "display"] {
        if draft.get(key).is_some() {
            computer[key] = draft[key].clone();
        }
    }
    if let Some(ssh) = draft.get("ssh") {
        computer["ssh"] = ssh.clone();
    }
    if computer["pairing_uuid"].as_str().is_none() {
        bail!("choose a paired computer");
    }
    Ok(computer)
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
    crate::server::retire_session(paths, computer)
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
    let mut ssh = serde_json::Map::new();
    for key in ["user", "control_path", "alias"] {
        if let Some(v) = c["ssh"].get(key) {
            ssh.insert(key.into(), v.clone());
        }
    }
    json!({"computer":id,"revision":rev,"name":c["name"].as_str().unwrap_or_else(|| c["title"].as_str().unwrap_or(id).trim_end_matches(" - Moonlight")),
        "host":c["host"],"platform":c["platform"].as_str().unwrap_or("unknown"),"ssh":ssh,
        "display":p.get("display").cloned().unwrap_or_else(|| json!({"adapter":"external"})),
        "profile":profile,"profiles":c["profiles"],"stream_resolution":p["stream_resolution"],
        "fps":p.get("fps").unwrap_or(&json!(60)),"bitrate":p.get("bitrate").unwrap_or(&json!(60000)),
        "codec":p.get("codec").unwrap_or(&json!("HEVC")),"input":p.get("input").unwrap_or(&json!("absolute")),
        "audio":p.get("audio").unwrap_or(&json!("focus"))})
}
// Only the common stream settings and display recovery settings cross the UI
// boundary; other profile fields are preserved by the merge below.
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
                    "display",
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
    // Optional and defaulted, so a draft that omits it saves a valid boolean.
    computer["profiles"][profile]["follow_window"] =
        json!(draft["follow_window"].as_bool().unwrap_or(false));
    // SSH identity fields and the default profile's display recovery are
    // editable; drafts without them leave the saved values untouched.
    if let Some(ssh) = draft.get("ssh").and_then(Value::as_object) {
        let mut kept = computer["ssh"].as_object().cloned().unwrap_or_default();
        for key in ["user", "control_path", "alias"] {
            match ssh.get(key) {
                Some(Value::String(s)) if !s.is_empty() => {
                    kept.insert(key.into(), json!(s));
                }
                _ => {
                    kept.remove(key);
                }
            }
        }
        if kept.is_empty() {
            computer.as_object_mut().unwrap().remove("ssh");
        } else {
            computer["ssh"] = Value::Object(kept);
        }
    }
    if let Some(display) = draft.get("display").and_then(Value::as_object) {
        let adapter = display
            .get("adapter")
            .and_then(Value::as_str)
            .unwrap_or("external");
        let mut next = serde_json::Map::new();
        next.insert("adapter".into(), json!(adapter));
        if adapter != "external" {
            for key in [
                "uuid",
                "follow_main",
                "require_ac",
                "mode",
                "device_id",
                "output",
                "sync_modes",
                "settings",
                "initial_resolution",
            ] {
                if let Some(v) = display.get(key)
                    && !v.is_null()
                {
                    next.insert(key.into(), v.clone());
                }
            }
        }
        computer["profiles"][profile]["display"] = Value::Object(next);
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
        Action::Discover => {
            let mut found = host::call(json!({"operation":"discover"})).await?;
            for item in found["candidates"]
                .as_array_mut()
                .context("invalid discovery list")?
            {
                let paired = item["pairing_uuid"].as_str().map(str::to_owned);
                item["configured"] = json!(paired.as_deref().is_some_and(|p| {
                    value["computers"].as_object().unwrap().values().any(|c| {
                        c["pairing_uuid"]
                            .as_str()
                            .is_some_and(|a| a.eq_ignore_ascii_case(p))
                    })
                }));
            }
            Ok(json!({"revision":revision(&value),"candidates":found["candidates"]}))
        }
        Action::Pair => {
            let request = read_stdin()?;
            let paired =
                host::call(json!({"operation":"pair","host":request["host"],"pin":request["pin"]}))
                    .await?;
            Ok(json!({"revision":revision(&value),"paired":paired}))
        }
        Action::Inspect => {
            let draft = read_stdin()?;
            let computer = subject(&value, &draft)?;
            host::call(json!({"operation":"inspect","computer":computer})).await
        }
        Action::InstallHelper => {
            let draft = read_stdin()?;
            let computer = subject(&value, &draft)?;
            host::call(json!({"operation":"install-helper","computer":computer,"device_id":draft["device_id"]})).await
        }
        Action::Test | Action::Save => {
            let draft = read_stdin()?;
            let next = candidate(paths, value, &draft).await?;
            if matches!(action, Action::Test) {
                // The probe is read-only. With a managed adapter it also proves
                // SSH and the chosen display without touching host settings.
                let c = &next["computers"][draft["computer"].as_str().unwrap()];
                let probe = host::call(json!({"operation":"setup-probe","computer":c})).await?;
                Ok(
                    json!({"tested":true,"restoration":probe["restoration"],"display":probe["display"],
                        "message":"Moonlight authenticated and found Desktop. Video and input are checked when you connect."}),
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

#[cfg(test)]
mod inspection_tests {
    use super::*;

    #[test]
    fn subject_preserves_virtual_inspection_settings_and_saved_identity() {
        let draft = json!({
            "computer": "work-pc", "platform": "windows", "adapter": "virtual",
            "display": {"adapter": "virtual", "settings": "D:\\VDD\\vdd_settings.xml"},
            "ssh": {"alias": "work-pc"}, "pairing_uuid": "draft-identity"
        });
        for value in [
            json!({"computers": {}}),
            json!({"computers": {"work-pc": {"pairing_uuid": "saved-identity"}}}),
        ] {
            let computer = subject(&value, &draft).unwrap();
            assert_eq!(computer["adapter"], "virtual");
            assert_eq!(computer["display"], draft["display"]);
            assert_eq!(computer["ssh"], draft["ssh"]);
            assert_eq!(
                computer["pairing_uuid"],
                value["computers"]["work-pc"]
                    .get("pairing_uuid")
                    .unwrap_or(&draft["pairing_uuid"])
                    .clone()
            );
        }
    }
}
