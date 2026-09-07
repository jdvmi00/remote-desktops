use crate::{
    desktop::{self, Window},
    host,
    storage::{self, Paths},
    supervisor::{self, Job},
};
use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    os::{
        fd::AsRawFd,
        unix::{fs::PermissionsExt, process::CommandExt},
    },
    process::Stdio,
    sync::{Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    net::{UnixDatagram, UnixListener, UnixStream},
    process::Command,
    sync::watch,
};

pub fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Session {
    pub version: u32,
    #[serde(default)]
    pub incarnation: String,
    pub computer: String,
    pub profile: String,
    pub config: Value,
    pub settings: Value,
    pub desired: bool,
    pub phase: String,
    pub generation: u64,
    pub token: Option<String>,
    pub reconnect: bool,
    #[serde(default)]
    pub release: bool,
    pub error: Option<String>,
    pub argv: Vec<String>,
    pub client_version: String,
    pub attempts: u32,
    pub next_retry: u64,
    pub closing_at: Option<u64>,
    pub launched_at: u64,
    pub window: Option<Window>,
    #[serde(default)]
    pub initialized_window: Option<String>,
    pub evidence: Value,
    /// Concrete stream size for this launch when the profile fits the window.
    #[serde(default)]
    pub resolution: Option<String>,
    /// Window sizes last observed per monitor; the prediction for the next launch.
    #[serde(default)]
    pub learned: BTreeMap<String, String>,
    /// Workspace to return the window to after a refit restart moved it.
    #[serde(default)]
    pub refit_workspace: Option<i64>,
}
impl Session {
    fn new(computer: &str, profile: &str, config: Value, settings: Value) -> Self {
        Self {
            version: 1,
            incarnation: uuid::Uuid::new_v4().to_string(),
            computer: computer.into(),
            profile: profile.into(),
            config,
            settings,
            desired: true,
            phase: "preflight".into(),
            generation: 1,
            token: None,
            reconnect: false,
            release: false,
            error: None,
            argv: vec![],
            client_version: "unknown".into(),
            attempts: 0,
            next_retry: 0,
            closing_at: None,
            launched_at: 0,
            window: None,
            initialized_window: None,
            evidence: json!({}),
            resolution: None,
            learned: BTreeMap::new(),
            refit_workspace: None,
        }
    }
    fn fits_window(&self) -> bool {
        self.settings["stream_resolution"] == "auto"
            || self.settings["display"]["adapter"] == "sunshine"
    }
}
pub struct Manager {
    pub paths: Paths,
    // Resolved once at startup: a rebuilt binary leaves /proc/self/exe
    // pointing at a deleted file, which would make every launch fail.
    executable: std::path::PathBuf,
    sessions: Mutex<BTreeMap<String, Session>>,
    wakes: Mutex<BTreeMap<String, watch::Sender<u64>>>,
    windows: watch::Receiver<Vec<Window>>,
}
impl Manager {
    fn get(&self, name: &str) -> Result<Session> {
        self.sessions
            .lock()
            .unwrap()
            .get(name)
            .cloned()
            .context("computer has no session")
    }
    async fn update(&self, name: &str, change: impl FnOnce(&mut Session)) -> Result<Session> {
        let incarnation = self.get(name)?.incarnation;
        loop {
            {
                // Acquire the gate only while the current directory is protected
                // from forget/recreate. Never wait for it under the global mutex.
                let mut sessions = self.sessions.lock().unwrap();
                let record = sessions.get_mut(name).context("computer has no session")?;
                if record.incarnation != incarnation {
                    bail!("session changed while waiting; retry the command");
                }
                match storage::lock(&self.paths.session(name).join("gate.lock"), true) {
                    Ok(_gate) => {
                        let mut updated = record.clone();
                        change(&mut updated);
                        if updated != *record {
                            storage::write(
                                &self.paths.session(name).join("session.json"),
                                &updated,
                            )?;
                            *record = updated.clone();
                        }
                        return Ok(updated);
                    }
                    Err(error) if storage::lock_contended(&error) => {}
                    Err(error) => return Err(error),
                }
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    }
    fn wake(&self, name: &str) {
        if let Some(wake) = self.wakes.lock().unwrap().get(name) {
            wake.send_modify(|n| *n = n.wrapping_add(1));
        }
    }
    fn job(&self, r: &Session) -> Job {
        r.token
            .as_ref()
            .map(|t| supervisor::read_job(&self.paths.session(&r.computer), t))
            .unwrap_or_default()
    }
    fn public(&self, r: &Session) -> Value {
        let job = self.job(r);
        let recovery_result =
            storage::read::<Value>(&self.paths.session(&r.computer).join("recovery.json"))
                .and_then(|record| {
                    host::journal_pending(&record)?;
                    Ok(record)
                });
        let recovery_error = recovery_result.as_ref().err().map(ToString::to_string);
        let recovery = recovery_result.unwrap_or(Value::Null);
        let pending = if recovery_error.is_some() {
            Value::Null
        } else {
            json!(
                recovery["journal"]
                    .as_object()
                    .is_some_and(|j| !j.is_empty())
            )
        };
        let observed = &recovery["resolved"]["host_display"];
        let verified = r.desired
            && observed["verified"] == true
            && observed["checked_at"]
                .as_u64()
                .is_some_and(|at| now().saturating_sub(at) <= 20);
        let refit_available = r.desired
            && supervisor::alive(&job)
            && r.window.is_some()
            && r.fits_window()
            && (r.settings["display"]["adapter"] == "sunshine"
                || (r.settings["display"]["adapter"] == "virtual" && verified));
        json!({"computer":r.computer,"profile":r.profile,"desired":r.desired,"phase":r.phase,"error":r.error,
            "generation":r.generation,"pid":if supervisor::alive(&job) {job.pid} else {None},"window":r.window,
            "evidence":r.evidence,"recovery_pending":pending,"recovery_error":recovery_error,
            "resolved":recovery["resolved"],"launcher":crate::launcher::identity(&r.computer,&r.config),
            "client_version":r.client_version,"launched_at":r.launched_at,"attempts":r.attempts,"next_retry":r.next_retry,
            "refit_available":refit_available,
            "refit_reason":if refit_available { "" } else { "Choose Sunshine matching, or verify the host when using verified matching." },
            "host_display":if verified { observed.clone() } else { json!({"verified":false}) },
            "fit_window":r.fits_window(),"resolution":r.resolution.clone().or_else(|| r.settings["stream_resolution"].as_str().map(String::from))})
    }
    pub async fn command(self: &Arc<Self>, request: Value) -> Result<Value> {
        let action = request["command"].as_str().context("missing command")?;
        let name = request["computer"].as_str().unwrap_or("");
        if action == "status" {
            if !name.is_empty() {
                return Ok(self.public(&self.get(name)?));
            }
            return Ok(
                json!({"version":1,"computers":self.sessions.lock().unwrap().values().map(|r|self.public(r)).collect::<Vec<_>>()}),
            );
        }
        if action == "refit" {
            // Match the stream to the window now and restart at that size. This is
            // the only thing that fits to the window; a plain connect launches at
            // the last known size. Named, or the focused Moonlight window when not.
            let target = if name.is_empty() {
                self.focused_session()
                    .await
                    .context("no focused remote desktop to refit")?
            } else {
                name.to_string()
            };
            let r = self.get(&target)?;
            if !r.desired || !r.fits_window() {
                bail!("refit applies to a connected fit-the-window desktop");
            }
            if r.settings["display"]["adapter"] != "virtual"
                && r.settings["display"]["adapter"] != "sunshine"
            {
                bail!("refit-unavailable: configure host display matching first");
            }
            if r.settings["display"]["adapter"] == "virtual" {
                host::operation(&self.paths.session(&target).join("recovery.json"), "health")
                    .await?;
            }
            let r = self.get(&target)?;
            if !r.desired {
                bail!("refit-cancelled: the desktop was disconnected");
            }
            if self.public(&r)["refit_available"] != true {
                bail!("refit-unavailable: host display matching has not been verified");
            }
            let window = r.window.clone().context("no window to fit yet")?;
            let monitors = desktop::monitors()
                .await
                .context("fit-unavailable: fitting the window needs Hyprland")?;
            let monitor = monitors
                .iter()
                .find(|m| m.id == window.monitor)
                .or_else(|| monitors.iter().find(|m| m.focused))
                .context("could not read the window's monitor")?;
            let observed = desktop::physical(&window.size, monitor.scale)
                .context("the window is too small to stream")?;
            self.update(&target, |r| {
                r.resolution = Some(observed.clone());
                r.learned.insert(
                    desktop::fit_key(&monitor.name, window.workspace),
                    observed.clone(),
                );
                r.reconnect = true;
                r.phase = "reconnecting".into();
                r.refit_workspace = Some(window.workspace);
            })
            .await?;
            eprintln!("{target}: refitting the stream to {observed}");
            self.wake(&target);
            return Ok(self.public(&self.get(&target)?));
        }
        if !storage::valid_id(name) {
            bail!("invalid computer ID");
        }
        if action == "forget" {
            // Only a fully settled session may be dropped; a pending recovery
            // journal or live client keeps its owner record.
            let mut sessions = self.sessions.lock().unwrap();
            let r = sessions.get(name).context("computer has no session")?;
            if r.desired || supervisor::alive(&self.job(r)) {
                bail!("Disconnect this computer before removing it.");
            }
            retire_session(&self.paths, name)?;
            sessions.remove(name);
            self.wakes.lock().unwrap().remove(name);
            return Ok(json!({"forgotten":true,"computer":name}));
        }
        if action == "connect" {
            // Validation/SSH work never holds the global state lock.
            let computers =
                host::call(json!({"operation":"validate","config":self.paths.config})).await?;
            let config = computers
                .get(name)
                .context("unknown computer; configure computers.json")?
                .clone();
            let profiles = config["profiles"].as_object().context("missing profiles")?;
            let profile = request["profile"]
                .as_str()
                .or_else(|| config["default_profile"].as_str())
                .unwrap_or_else(|| {
                    if profiles.contains_key("desktop") {
                        "desktop"
                    } else {
                        profiles.keys().next().unwrap()
                    }
                })
                .to_owned();
            let settings = profiles.get(&profile).context("unknown profile")?.clone();
            storage::check_legacy(
                &self.paths,
                config["pairing_uuid"]
                    .as_str()
                    .context("missing pairing identity")?,
            )?;
            let existing = self.sessions.lock().unwrap().get(name).cloned();
            if let Some(old) = &existing
                && old.desired
            {
                if old.profile != profile {
                    bail!("disconnect before changing profile");
                }
                if let Some(window) = &old.window {
                    desktop::action(window, "focus").await?;
                }
                return Ok(self.public(old));
            }
            let directory = self.paths.session(name);
            let mut sessions = self.sessions.lock().unwrap();
            storage::private_dir(&directory)?;
            let _gate = storage::lock(&directory.join("gate.lock"), true)
                .context("client launch is still settling; try connecting again")?;
            // Another concurrent connect may have completed while validation ran.
            if let Some(old) = sessions.get(name) {
                if old.desired {
                    if old.profile != profile {
                        bail!("disconnect before changing profile");
                    }
                    return Ok(self.public(old));
                }
                if !matches!(old.phase.as_str(), "idle" | "attention")
                    || supervisor::alive(&self.job(old))
                {
                    bail!("disconnect/recovery still in progress");
                }
                if host::pending(&directory.join("recovery.json"))? {
                    bail!("restore-pending: restore or explicitly release first");
                }
            }
            // Pairing identity, not the display name, is the ownership key.
            for (other, r) in sessions.iter() {
                if other != name
                    && r.config["pairing_uuid"].as_str().is_some_and(|id| {
                        id.eq_ignore_ascii_case(config["pairing_uuid"].as_str().unwrap())
                    })
                    && (r.desired
                        || supervisor::alive(&self.job(r))
                        || host::pending(&self.paths.session(other).join("recovery.json"))?)
                {
                    bail!("paired computer already owned by {other}");
                }
            }
            let mut record = Session::new(name, &profile, config, settings);
            record.generation = sessions.get(name).map_or(1, |r| r.generation + 1);
            record.learned = sessions
                .get(name)
                .map(|r| r.learned.clone())
                .unwrap_or_default();
            // Recovery baseline precedes launch intent. Never overwrite a
            // pending journal or an old helper's in-flight write.
            let _recovery_lock = storage::lock(&directory.join("recovery.lock"), true)
                .context("host operation still running")?;
            storage::write(
                &directory.join("recovery.json"),
                &json!({"config":record.config,"settings":record.settings,"journal":{}}),
            )?;
            storage::write(&directory.join("session.json"), &record)?;
            sessions.insert(name.into(), record.clone());
            drop(sessions);
            self.start(name);
            self.wake(name);
            return Ok(self.public(&record));
        }
        let old = self.get(name)?;
        if action == "focus" {
            desktop::action(old.window.as_ref().context("no ready window")?, "focus").await?;
            return Ok(self.public(&old));
        }
        if action == "release" {
            if request["keep_host_settings"] != true {
                bail!("release requires --keep-host-settings");
            }
            if old.desired
                || supervisor::alive(&self.job(&old))
                || !matches!(old.phase.as_str(), "idle" | "attention" | "restore-pending")
            {
                bail!("disconnect and wait before releasing recovery");
            }
            // The actor serializes release with any outstanding host recovery.
            self.update(name, |r| {
                r.phase = "release-pending".into();
                r.release = true;
                r.generation += 1;
            })
            .await?;
        } else if action == "disconnect" || action == "restore" {
            self.update(name, |r| {
                r.desired = false;
                r.reconnect = false;
                r.phase = "stopping".into();
                r.generation += 1;
                r.error = None;
                r.next_retry = 0;
            })
            .await?;
        } else if action == "reconnect" {
            if !old.desired || !supervisor::alive(&self.job(&old)) {
                bail!("connect this computer first");
            }
            if !old.reconnect {
                self.update(name, |r| {
                    r.reconnect = true;
                    r.phase = "reconnecting".into();
                    r.generation += 1;
                    r.error = None;
                })
                .await?;
            }
        } else {
            bail!("unknown command");
        }
        self.wake(name);
        Ok(self.public(&self.get(name)?))
    }
    async fn focused_session(&self) -> Option<String> {
        let pid = desktop::active_pid().await.ok().flatten()?;
        self.sessions
            .lock()
            .unwrap()
            .iter()
            .find(|(_, r)| r.window.as_ref().is_some_and(|w| w.pid == pid))
            .map(|(name, _)| name.clone())
    }
    fn start(self: &Arc<Self>, name: &str) {
        let mut wakes = self.wakes.lock().unwrap();
        if wakes.contains_key(name) {
            return;
        }
        let (tx, rx) = watch::channel(0);
        wakes.insert(name.into(), tx);
        let manager = self.clone();
        let name = name.to_owned();
        tokio::spawn(async move {
            manager.worker(name, rx).await;
        });
    }
    async fn worker(self: Arc<Self>, name: String, mut wake: watch::Receiver<u64>) {
        let mut windows = self.windows.clone();
        let mut health_due = 0;
        loop {
            // A forgotten session drops its wake sender; stop before touching
            // any record a later connect may create under the same name.
            if wake.has_changed().is_err() {
                return;
            }
            let result = self.step(&name, &mut health_due).await;
            if wake.has_changed().is_err() {
                return;
            }
            let delay = match result {
                Ok(delay) => delay,
                Err(error) => {
                    // Keep the cause chain: "launch supervisor" alone hides the reason.
                    let message = format!("{error:#}");
                    let _ = self
                        .update(&name, |r| {
                            if message.contains("host-unreachable")
                                && r.desired
                                && r.token.is_none()
                                && r.attempts < 3
                            {
                                r.attempts += 1;
                                r.next_retry = now() + [2, 5, 15][(r.attempts - 1) as usize];
                                r.phase = "preflight".into();
                            } else {
                                r.desired = false;
                                r.reconnect = false;
                                r.phase = "stopping".into();
                            }
                            r.error = Some(message);
                        })
                        .await;
                    Duration::from_secs(1)
                }
            };
            // No periodic work for idle sessions. The desktop channel closes
            // outside Hyprland; disable that select arm to avoid a busy loop.
            let observing = self
                .get(&name)
                .is_ok_and(|r| r.desired && r.token.is_some());
            tokio::select! {
                changed=wake.changed()=>{ if changed.is_err() { return; } },
                _=windows.changed(), if observing && windows.has_changed().is_ok()=>{},
                _=tokio::time::sleep(delay)=>{},
            }
        }
    }
    async fn step(&self, name: &str, health_due: &mut u64) -> Result<Duration> {
        let directory = self.paths.session(name);
        let recovery = directory.join("recovery.json");
        let mut r = self.get(name)?;
        let job = self.job(&r);
        let alive = supervisor::alive(&job);
        if !r.desired || r.reconnect {
            if alive {
                let closing = r.closing_at.unwrap_or_else(now);
                if r.closing_at.is_none() {
                    self.update(name, |r| r.closing_at = Some(closing)).await?;
                    if let Some(window) = &r.window {
                        let _ = desktop::action(window, "close").await;
                    }
                }
                supervisor::signal(
                    job.pid.unwrap(),
                    &job.token,
                    now().saturating_sub(closing) >= 5,
                )?;
                return Ok(Duration::from_secs(1));
            }
            // An already spawned supervisor may still be inside its launch
            // gate. It rechecks durable desired intent before publishing a PID.
            if job.supervisor != 0 && supervisor::owned(job.supervisor, &job.token) && !job.ended {
                return Ok(Duration::from_secs(1));
            }
            if r.reconnect && r.desired {
                self.update(name, |r| {
                    r.token = None;
                    r.window = None;
                    r.reconnect = false;
                    r.closing_at = None;
                    r.phase = "preflight".into();
                })
                .await?;
                return Ok(Duration::ZERO);
            }
            if r.release {
                host::call(
                    json!({"operation":"release","path":recovery,"keep_host_settings":true}),
                )
                .await?;
                self.update(name, |r| {
                    r.phase = "idle".into();
                    r.release = false;
                    r.error = None;
                    r.window = None;
                    r.token = None;
                })
                .await?;
                return Ok(Duration::from_secs(86400));
            }
            if host::pending(&recovery)? {
                match host::operation(&recovery, "restore").await {
                    Ok(value) if value["complete"] == true => {}
                    result => {
                        self.update(name, |r| {
                            r.phase = "restore-pending".into();
                            r.window = None;
                            if let Err(e) = result {
                                r.error = Some(e.to_string());
                            }
                        })
                        .await?;
                        return Ok(Duration::from_secs(10));
                    }
                }
            }
            self.update(name, |r| {
                r.phase = if r.error.is_some() {
                    "attention"
                } else {
                    "idle"
                }
                .into();
                r.token = None;
                r.window = None;
                r.closing_at = None;
            })
            .await?;
            return Ok(Duration::from_secs(86400));
        }
        if r.token.is_none() {
            if r.next_retry > now() {
                return Ok(Duration::from_secs(r.next_retry - now()));
            }
            // Refuse an existing unmanaged window before touching host displays.
            let owned_pids: Vec<u32> = self
                .sessions
                .lock()
                .unwrap()
                .values()
                .map(|record| self.job(record))
                .filter(supervisor::alive)
                .filter_map(|job| job.pid)
                .collect();
            // A window whose process has already exited is a stale snapshot
            // entry, not a live view; the compositor drops it moments later.
            if self.windows.borrow().iter().any(|w| {
                w.class == desktop::CLASS
                    && Some(w.title.as_str()) == r.config["title"].as_str()
                    && !owned_pids.contains(&w.pid)
                    && std::path::Path::new(&format!("/proc/{}", w.pid)).exists()
            }) {
                bail!("unmanaged-stream: close the existing Moonlight view first");
            }
            let resolution = if r.fits_window() {
                // Launch at the last known size: a refit target already decided
                // this launch, otherwise the size last fitted for this monitor and
                // workspace, otherwise the saved initial size. Refit is the only
                // thing that matches the window; a connect never restarts to fit.
                match r.resolution.clone() {
                    Some(size) => Some(size),
                    None => {
                        let initial = r.settings["display"]["initial_resolution"]
                            .as_str()
                            .or_else(|| {
                                r.settings["stream_resolution"]
                                    .as_str()
                                    .filter(|size| *size != "auto")
                            })
                            .unwrap_or("1920x1080");
                        let (key, size) = match desktop::predict(&r.learned, initial).await {
                            Ok(prediction) => prediction,
                            Err(_) if r.settings["display"]["adapter"] == "sunshine" => {
                                ("saved resolution".into(), initial.to_string())
                            }
                            Err(error) => {
                                return Err(error)
                                    .context("fit-unavailable: fitting the window needs Hyprland");
                            }
                        };
                        eprintln!("{name}: launching {key} at last known {size}");
                        Some(size)
                    }
                }
            } else {
                None
            };
            r = self
                .update(name, |r| {
                    r.phase = "preflight".into();
                    r.resolution = resolution;
                })
                .await?;
            let info = host::call(
                json!({"operation":"probe","path":recovery,"stream_resolution":r.resolution}),
            )
            .await?;
            if !self.get(name)?.desired {
                return Ok(Duration::ZERO);
            }
            self.update(name, |r| r.phase = "preparing".into()).await?;
            host::operation(&recovery, "prepare").await?;
            if !self.get(name)?.desired {
                return Ok(Duration::ZERO);
            }
            r = self
                .update(name, |r| {
                    r.argv = serde_json::from_value(info["argv"].clone()).unwrap_or_default();
                    r.client_version = info["resolved"]["client_version"]
                        .as_str()
                        .unwrap_or("unknown")
                        .into();
                    r.token = Some(uuid::Uuid::new_v4().simple().to_string());
                    r.phase = "connecting".into();
                    r.launched_at = now();
                    r.error = None;
                })
                .await?;
            let mut command = Command::new(&self.executable);
            command
                .args(["supervise", "--directory"])
                .arg(&directory)
                .arg("--token")
                .arg(r.token.as_ref().unwrap())
                .arg("--runtime")
                .arg(&self.paths.runtime)
                .env(supervisor::TOKEN, r.token.as_ref().unwrap())
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            command.as_std_mut().process_group(0);
            let mut child = command.spawn().context("launch supervisor")?;
            tokio::spawn(async move {
                let _ = child.wait().await;
            });
            *health_due = now() + 10;
            return Ok(Duration::from_secs(1));
        }
        if job.ended || (!alive && now().saturating_sub(r.launched_at) > 15) {
            if job.evidence["terminated"] == -100 && r.attempts < 3 {
                self.update(name, |r| {
                    r.token = None;
                    r.window = None;
                    r.attempts += 1;
                    r.next_retry = now() + [2, 5, 15][(r.attempts - 1) as usize];
                    r.phase = "preflight".into();
                })
                .await?;
            } else {
                self.update(name, |r| {
                    r.desired = false;
                    r.phase = "stopping".into();
                    r.evidence = job.evidence.clone();
                    if !(job.success || job.evidence["quit"] == true) {
                        r.error = Some("stream-exited: reconnect after recovery".into());
                    }
                })
                .await?;
            }
            return Ok(Duration::ZERO);
        }
        if alive {
            let window = self
                .windows
                .borrow()
                .iter()
                .find(|w| {
                    Some(w.pid) == job.pid
                        && w.class == desktop::CLASS
                        && Some(w.title.as_str()) == r.config["title"].as_str()
                })
                .cloned();
            if let Some(w) = &window {
                let key = format!("{}:{}:{}", job.token, w.pid, w.stable_id);
                if r.initialized_window.as_ref() != Some(&key) {
                    // Consume startup policy durably before dispatch: a crash
                    // must not cause a restart to undo a later user choice.
                    r = self
                        .update(name, |r| r.initialized_window = Some(key))
                        .await?;
                    if let Err(e) = desktop::initialize(w, name).await {
                        self.update(name, |r| {
                            r.error = Some(format!("window initialization: {e}"))
                        })
                        .await?;
                    }
                    // A refit restart may reopen the window on the active
                    // workspace; return it to where the user had put it.
                    if let Some(ws) = r.refit_workspace {
                        if w.workspace != ws {
                            let _ = desktop::action(w, &format!("workspace:{ws}")).await;
                        }
                        r = self.update(name, |r| r.refit_workspace = None).await?;
                    }
                }
            }
            let changed_visibility = window.as_ref().map(|w| (&w.stable_id, w.pid, w.visible))
                != r.window.as_ref().map(|w| (&w.stable_id, w.pid, w.visible));
            if changed_visibility && let Some(w) = &window {
                let policy = r.settings["keep_awake"].as_str().unwrap_or("visible");
                let inhibit = policy == "always" || (policy == "visible" && w.visible);
                let _ = desktop::action(w, if inhibit { "inhibit" } else { "uninhibit" }).await;
            }
            // Observed geometry is never fed back into placement. It only sizes
            // the stream, once, for profiles that fit the window.
            if window != r.window || r.evidence != job.evidence || r.phase == "connecting" {
                r = self
                    .update(name, |r| {
                        r.window = window;
                        r.evidence = job.evidence.clone();
                        r.phase = if r.window.is_some() {
                            "window-ready"
                        } else {
                            "running"
                        }
                        .into();
                    })
                    .await?;
            }
            let delay = Duration::from_secs(10);
            if *health_due <= now()
                && r.settings["display"]["adapter"] != "external"
                && r.settings["display"]["adapter"] != "sunshine"
                && !r.settings["display"].is_null()
            {
                *health_due = now() + 10;
                match host::operation(&recovery, "health").await {
                    Ok(value) if value["reconnect"] == true => {
                        self.update(name, |r| {
                            if r.desired {
                                r.reconnect = true;
                                r.phase = "reconnecting".into();
                            }
                        })
                        .await?;
                        return Ok(Duration::ZERO);
                    }
                    Ok(value) => {
                        self.update(name, |r| {
                            r.error = if value["degraded"] == true {
                                Some("display-mode-changed: host settings preserved".into())
                            } else {
                                None
                            }
                        })
                        .await?;
                    }
                    Err(e)
                        if (e.to_string().contains("host-unreachable")
                            || e.to_string().contains("TimeoutExpired")) =>
                    {
                        self.update(name, |r| r.error = Some(e.to_string())).await?;
                    }
                    Err(e) => return Err(e),
                }
            }
            return Ok(delay);
        }
        Ok(Duration::from_secs(10))
    }
}

/// Retire only a durably settled directory. Callers hold the daemon's session
/// map mutex or its exclusive writer lock, serializing this rename with connect.
pub fn retire_session(paths: &Paths, name: &str) -> Result<()> {
    let directory = paths.session(name);
    let _gate = storage::lock(&directory.join("gate.lock"), true)
        .context("client launch is still settling; try removing again")?;
    let _recovery = storage::lock(&directory.join("recovery.lock"), true)
        .context("host operation still running; try removing again")?;
    let record: Session = storage::read(&directory.join("session.json"))?;
    if record.version != 1 || record.computer != name {
        bail!("unsupported session state; session preserved");
    }
    let job = record
        .token
        .as_ref()
        .map(|token| supervisor::read_job(&directory, token))
        .unwrap_or_default();
    if record.desired || supervisor::alive(&job) || supervisor::owned(job.supervisor, &job.token) {
        bail!("Disconnect this computer and wait before removing it.");
    }
    let recovery = directory.join("recovery.json");
    if !recovery.exists() || host::pending(&recovery)? {
        bail!("restore-pending: verify and restore the host display before removing this computer");
    }
    if !matches!(record.phase.as_str(), "idle" | "attention") {
        bail!(
            "This computer is still finishing its last session. Wait until it is idle before removing it."
        );
    }
    let retired = paths
        .state
        .join(format!(".forgotten-{}", uuid::Uuid::new_v4()));
    fs::rename(&directory, &retired)
        .context("could not retire session; its record was preserved")?;
    // The atomic rename is the lifecycle transition. Cleanup can never delete
    // a subsequent session using the same computer ID.
    if let Err(error) = fs::remove_dir_all(&retired) {
        eprintln!(
            "could not clean retired session {}: {error}",
            retired.display()
        );
    }
    Ok(())
}

pub async fn serve(paths: Paths) -> Result<()> {
    paths.init()?;
    let _writer =
        storage::lock(&paths.state.join("writer.lock"), true).context("daemon already running")?;
    let legacy = if paths.legacy().exists() {
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(paths.legacy().join("writer.lock"))?;
        fs2::FileExt::try_lock_shared(&file).context(
            "handoff-required: stop Hypertile's stream controller before starting Remote Desktops",
        )?;
        // Descendant supervisors/clients retain this same lock across daemon
        // restarts so the old controller cannot race a still-running view.
        let fd = file.as_raw_fd();
        let result = unsafe { libc::fcntl(fd, libc::F_SETFD, 0) };
        if result < 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        Some(file)
    } else {
        None
    };
    let _legacy = legacy;
    let _ = fs::remove_file(paths.socket());
    let _ = fs::remove_file(paths.events());
    let listener = UnixListener::bind(paths.socket())?;
    let events = UnixDatagram::bind(paths.events())?;
    fs::set_permissions(paths.socket(), fs::Permissions::from_mode(0o600))?;
    fs::set_permissions(paths.events(), fs::Permissions::from_mode(0o600))?;
    let mut sessions = BTreeMap::new();
    for entry in fs::read_dir(paths.state.join("sessions"))? {
        let entry = entry?;
        if !entry.file_type()?.is_dir() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_string();
        if !storage::valid_id(&name) {
            bail!("invalid session directory");
        }
        let path = entry.path().join("session.json");
        if !path.exists() {
            continue;
        }
        let mut r: Session = storage::read(&path)?;
        if r.version != 1 || r.computer != name {
            bail!("unsupported session state");
        }
        // Adopt windows from the pre-launcher schema without changing an
        // already-running window's fullscreen state during upgrade.
        if r.initialized_window.is_none()
            && let (Some(w), Some(token)) = (&r.window, &r.token)
        {
            r.initialized_window = Some(format!("{token}:{}:{}", w.pid, w.stable_id));
        }
        sessions.insert(name, r);
    }
    let manager = Arc::new(Manager {
        paths: paths.clone(),
        executable: std::env::current_exe()?,
        sessions: Mutex::new(sessions),
        wakes: Mutex::new(BTreeMap::new()),
        windows: desktop::observe().await?,
    });
    let names = manager
        .sessions
        .lock()
        .unwrap()
        .keys()
        .cloned()
        .collect::<Vec<_>>();
    for name in names {
        manager.start(&name);
    }
    let mut buffer = [0u8; 128];
    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    loop {
        tokio::select! {
            _=term.recv()=>break,
            _=tokio::signal::ctrl_c()=>break,
            event=events.recv(&mut buffer)=>{if let Ok(size)=event&& let Ok(name)=std::str::from_utf8(&buffer[..size]) {manager.wake(name);}},
            connection=listener.accept()=>{
                let (stream,_)=connection?;let manager=manager.clone();
                tokio::spawn(async move {let _=tokio::time::timeout(Duration::from_secs(30),handle(stream,manager)).await;});
            }
        }
    }
    let _ = fs::remove_file(paths.socket());
    let _ = fs::remove_file(paths.events());
    Ok(())
}
async fn handle(stream: UnixStream, manager: Arc<Manager>) -> Result<()> {
    let (reader, mut writer) = stream.into_split();
    let mut data = String::new();
    BufReader::new(reader)
        .take(65_537)
        .read_line(&mut data)
        .await?;
    if data.len() > 65_536 || !data.ends_with('\n') {
        bail!("invalid or oversized request");
    }
    let response = match serde_json::from_str::<Value>(&data) {
        Ok(request) => match manager.command(request).await {
            Ok(result) => json!({"ok":true,"result":result}),
            Err(e) => json!({"ok":false,"error":e.to_string()}),
        },
        Err(_) => json!({"ok":false,"error":"invalid JSON"}),
    };
    writer.write_all(&serde_json::to_vec(&response)?).await?;
    writer.write_all(b"\n").await?;
    Ok(())
}
pub async fn request(paths: &Paths, payload: &Value) -> Result<Value> {
    let mut stream = UnixStream::connect(paths.socket())
        .await
        .context("daemon unavailable; start remote-desktops daemon")?;
    stream.write_all(&serde_json::to_vec(payload)?).await?;
    stream.write_all(b"\n").await?;
    let mut text = String::new();
    tokio::time::timeout(
        Duration::from_secs(30),
        BufReader::new(stream).take(2_000_001).read_line(&mut text),
    )
    .await??;
    if text.len() > 2_000_000 {
        bail!("response too large");
    }
    let reply: Value = serde_json::from_str(&text)?;
    if reply["ok"] != true {
        bail!("{}", reply["error"].as_str().unwrap_or("request failed"));
    }
    Ok(reply["result"].clone())
}
