#include "Manager.h"
#include <QClipboard>
#include <QDateTime>
#include <QGuiApplication>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QPointer>
#include <QFileInfo>
#include <QStandardPaths>
#include <utility>

namespace {
qint64 now() { return QDateTime::currentSecsSinceEpoch(); }
}
Manager::Manager(QString backend, QString socket, bool demo, QObject *parent)
    : QObject(parent), m_backend(std::move(backend)), m_socketPath(std::move(socket)), m_demo(demo) {
    m_poll.setInterval(2000);
    connect(&m_poll, &QTimer::timeout, this, &Manager::poll);
    // Pairing happens in Moonlight; the manager only offers to open it.
    m_moonlight = QStandardPaths::findExecutable("moonlight");
    if (m_moonlight.isEmpty()) m_moonlight = QStandardPaths::findExecutable("moonlight-qt");
    if (m_demo) {
        m_catalog = QJsonDocument::fromJson(R"([
          {"computer":"studio","name":"Studio Mac","host":"studio.example.net","platform":"macos","default_profile":"desktop","profiles":["desktop","presentation"]},
          {"computer":"work","name":"Work laptop","host":"work.example.net","platform":"windows","default_profile":"desktop","profiles":["desktop"]},
          {"computer":"lab","name":"Linux workstation","host":"lab.example.net","platform":"linux","default_profile":"desktop","profiles":["desktop"]}
        ])").array();
        m_sessions = QJsonDocument::fromJson(R"([{"computer":"studio","profile":"desktop","phase":"window-ready","desired":true,"window":{"address":"demo"},"client_version":"6.1.0","evidence":{"negotiated_video":{"width":2560,"height":1440,"fps":60}}},{"computer":"work","phase":"idle","desired":false},{"computer":"lab","phase":"idle","desired":false}])").array();
        auto studio = m_sessions[0].toObject();
        studio["launched_at"] = now() - 754;
        m_sessions[0] = studio;
        m_available = true; m_loading = false;
        m_windowRule = QJsonObject{{"available", true}, {"installed", false}, {"manual", false}};
    } else {
        QTimer::singleShot(0, this, &Manager::refresh);
        m_poll.start();
    }
}
QVariantList Manager::computers() const {
    QVariantList out;
    QJsonArray all = m_catalog;
    // Recovery records remain accessible even after a computer is removed from config.
    for (const auto &session : m_sessions) {
        bool found = false;
        for (const auto &entry : all) if (entry.toObject()["computer"] == session.toObject()["computer"]) found = true;
        if (!found) all.append(QJsonObject{{"computer", session.toObject()["computer"]}, {"name", session.toObject()["computer"]}, {"profiles", QJsonArray{}}, {"unconfigured", true}});
    }
    for (const auto &entry : all) {
        auto item = entry.toObject();
        item["phase"] = "idle"; item["desired"] = false;
        for (const auto &session : m_sessions) if (session.toObject()["computer"] == item["computer"]) {
            const auto record = session.toObject();
            for (auto i = record.begin(); i != record.end(); ++i) item[i.key()] = i.value();
        }
        item["busy"] = m_busy.contains(item["computer"].toString());
        item["stale"] = !m_available;
        // The launcher entry is a file the backend writes; its presence is the whole state.
        const auto desktopEntry = QStandardPaths::writableLocation(QStandardPaths::ApplicationsLocation) + "/remote-desktops-" + item["computer"].toString() + ".desktop";
        item["launcher_installed"] = m_demo ? m_demoLaunchers.contains(item["computer"].toString()) : QFileInfo::exists(desktopEntry);
        out.append(item.toVariantMap());
    }
    return out;
}
QString Manager::label(const QString &computer) const {
    for (const auto &entry : m_catalog) if (entry.toObject()["computer"].toString() == computer) {
        const auto name = entry.toObject()["name"].toString();
        if (!name.isEmpty()) return name;
    }
    return computer;
}
void Manager::publish() { emit changed(); }
void Manager::clearNotice() { m_notice.clear(); m_noticeError = false; publish(); }
void Manager::notify(QString text, bool error) { m_notice = std::move(text); m_noticeError = error; publish(); }
void Manager::setActive(bool active) {
    m_active = active;
    if (m_demo) return;
    if (active) { m_poll.start(); poll(); } else m_poll.stop();
}
void Manager::refresh() {
    if (m_demo) { publish(); return; }
    loadCatalog(); loadWindowRule(); poll();
}
QVariantMap Manager::windowRule() const {
    auto out = m_windowRule.toVariantMap();
    out["busy"] = m_windowRuleBusy;
    return out;
}
void Manager::loadWindowRule() {
    process({"--json", "window-rule", "status"}, [this](bool ok, QByteArray bytes) {
        const auto doc = QJsonDocument::fromJson(bytes);
        m_windowRule = ok && doc.isObject() ? doc.object() : QJsonObject{{"available", false}};
        publish();
    });
}
void Manager::setWindowRule(bool tiled) {
    if (m_windowRuleBusy) return;
    m_windowRuleBusy = true; m_notice.clear(); m_noticeError = false; publish();
    if (m_demo) {
        QTimer::singleShot(350, this, [this, tiled] {
            m_windowRuleBusy = false; m_windowRule["installed"] = tiled;
            m_notice = tiled ? "Remote desktops will open tiled in the preview." : "Preview rule removed.";
            publish();
        });
        return;
    }
    process({"--json", "window-rule", tiled ? "install" : "remove"}, [this, tiled](bool ok, QByteArray bytes) {
        m_windowRuleBusy = false;
        const auto doc = QJsonDocument::fromJson(bytes);
        if (ok && doc.isObject()) {
            m_windowRule = doc.object();
            m_notice = tiled ? "Remote desktops now open tiled. Already open windows keep their state." : "Moonlight windows follow the desktop's default rule again.";
        } else { m_notice = QString::fromUtf8(bytes).trimmed(); m_noticeError = true; }
        publish();
    });
}
void Manager::process(QStringList arguments, std::function<void(bool, QByteArray)> complete, QByteArray input, int deadline) {
    auto *job = new QProcess(this);
    auto *timer = new QTimer(job);
    timer->setSingleShot(true);
    auto output = std::make_shared<QByteArray>();
    auto failure = std::make_shared<QByteArray>();
    auto done = std::make_shared<bool>(false);
    auto finish = [job, timer, complete, done](bool ok, QByteArray data) {
        if (std::exchange(*done, true)) return;
        timer->stop(); complete(ok, data); job->deleteLater();
    };
    connect(job, &QProcess::readyReadStandardOutput, this, [job, output, finish] {
        *output += job->readAllStandardOutput();
        if (output->size() > 2000000) { job->kill(); finish(false, "Response exceeded the size limit. Refresh to check the current state."); }
    });
    connect(job, &QProcess::readyReadStandardError, this, [job, failure] { *failure = (*failure + job->readAllStandardError()).left(8192); });
    connect(job, &QProcess::errorOccurred, this, [finish](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) finish(false, "The Remote Desktops backend could not start. Check the app installation and try again.");
    });
    connect(job, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
            [output, failure, finish](int code, QProcess::ExitStatus status) {
        const bool ok = code == 0 && status == QProcess::NormalExit;
        QByteArray message = failure->trimmed();
        // The CLI prefixes its own name; the manager already provides that context.
        if (message.startsWith("remote-desktops: ")) message = message.mid(17);
        finish(ok, ok ? *output : (message.isEmpty() ? QByteArray("The request failed. Refresh to check the current state.") : message));
    });
    connect(timer, &QTimer::timeout, this, [job, finish] {
        job->kill(); finish(false, "The request timed out. Its outcome may still be pending; refresh before retrying.");
    });
    connect(job, &QProcess::started, this, [job, input] { job->write(input); job->closeWriteChannel(); });
    job->start(m_backend, arguments);
    timer->start(deadline);
}
void Manager::loadCatalog() {
    if (m_catalogLoading) return;
    m_catalogLoading = true;
    process({"--json", "computers"}, [this](bool ok, QByteArray bytes) {
        m_catalogLoading = false; m_loading = false;
        QJsonParseError parse;
        auto doc = QJsonDocument::fromJson(bytes, &parse);
        if (!ok || parse.error != QJsonParseError::NoError || !doc.isArray()) {
            m_error = ok ? "Computer settings could not be read. Check the configuration and refresh." : QString::fromUtf8(bytes).trimmed();
        } else {
            m_catalog = doc.array(); m_error.clear();
        }
        publish();
    });
}
void Manager::poll() {
    if (m_demo || m_socket || !m_active) return;
    auto *socket = new QLocalSocket(this);
    m_socket = socket;
    auto bytes = std::make_shared<QByteArray>();
    auto done = std::make_shared<bool>(false);
    auto changed = std::make_shared<bool>(false);
    auto finish = [this, socket, done, changed](bool ok) {
        if (std::exchange(*done, true)) return;
        bool update = m_available != ok || *changed;
        m_available = ok; m_socket = nullptr;
        socket->abort(); socket->deleteLater();
        if (update) publish();
    };
    connect(socket, &QLocalSocket::connected, this, [socket] { socket->write("{\"command\":\"status\"}\n"); });
    connect(socket, &QLocalSocket::readyRead, this, [this, socket, bytes, finish, changed] {
        *bytes += socket->readAll();
        if (bytes->size() > 2000000) { finish(false); return; }
        if (!bytes->contains('\n')) return;
        QJsonParseError error;
        auto reply = QJsonDocument::fromJson(bytes->left(bytes->indexOf('\n')), &error).object();
        bool ok = error.error == QJsonParseError::NoError && reply["ok"].toBool()
            && reply["result"].toObject()["computers"].isArray();
        if (ok) {
            auto sessions = reply["result"].toObject()["computers"].toArray();
            *changed = sessions != m_sessions; m_sessions = sessions;
        }
        finish(ok);
    });
    connect(socket, &QLocalSocket::errorOccurred, this, [finish](QLocalSocket::LocalSocketError) { finish(false); });
    connect(socket, &QLocalSocket::disconnected, this, [finish] { finish(false); });
    QTimer::singleShot(1500, socket, [finish] { finish(false); });
    socket->connectToServer(m_socketPath);
}
void Manager::act(QString computer, QString action, QString profile) {
    static const QSet<QString> allowed{"connect", "disconnect", "reconnect", "refit", "restore", "focus", "launcher", "launcher-remove"};
    if (!allowed.contains(action) || m_busy.contains(computer)) return;
    bool known = false;
    for (const auto &entry : computers()) if (entry.toMap()["computer"].toString() == computer) known = true;
    if (!known) return;
    if (m_demo) {
        // The preview walks through the same intermediate phases a real
        // session reports, so transitional states can be seen and tested.
        auto set = [this, computer](std::function<void(QJsonObject &)> change) {
            for (qsizetype i = 0; i < m_sessions.size(); ++i) if (m_sessions[i].toObject()["computer"].toString() == computer) {
                auto s = m_sessions[i].toObject(); change(s); m_sessions[i] = s;
            }
        };
        m_busy.insert(computer); m_notice.clear(); m_noticeError = false; publish();
        QTimer::singleShot(350, this, [this, computer, action, profile, set] {
            m_busy.remove(computer);
            if (action == "refit") { m_notice = label(computer) + " would refit to its window in the preview."; publish(); return; }
            if (action == "focus" || action == "launcher" || action == "launcher-remove") {
                if (action == "launcher") m_demoLaunchers.insert(computer);
                if (action == "launcher-remove") m_demoLaunchers.remove(computer);
                m_notice = action == "launcher" ? label(computer) + " was added to the preview launcher." : action == "launcher-remove" ? label(computer) + " was removed from the preview launcher." : "Preview only — the desktop window would be focused.";
                publish(); return;
            }
            const bool connecting = action == "connect" || action == "reconnect";
            set([&](QJsonObject &s) {
                s["phase"] = action == "connect" ? "connecting" : action == "reconnect" ? "reconnecting" : action == "restore" ? "restoring" : "stopping";
                s["desired"] = connecting; s["window"] = QJsonValue(); s["error"] = QJsonValue();
                if (!profile.isEmpty()) s["profile"] = profile;
            });
            publish();
            QTimer::singleShot(900, this, [this, connecting, set] {
                set([&](QJsonObject &s) {
                    s["phase"] = connecting ? "window-ready" : "idle";
                    s["window"] = connecting ? QJsonValue(QJsonObject{{"address", "demo"}}) : QJsonValue();
                    s["recovery_pending"] = false; s["error"] = QJsonValue();
                    if (connecting) { s["launched_at"] = now(); s["client_version"] = "6.1.0"; }
                    else s.remove("launched_at");
                });
                publish();
            });
        });
        return;
    }
    QStringList args{"--json"};
    if (action == "launcher") args << "launcher" << "install" << computer;
    else if (action == "launcher-remove") args << "launcher" << "remove" << computer;
    else args << action << computer;
    if (action == "connect" && !profile.isEmpty()) args << "--profile" << profile;
    m_busy.insert(computer); m_notice.clear(); m_noticeError = false; publish();
    process(args, [this, computer, action](bool ok, QByteArray data) {
        m_busy.remove(computer);
        // Accepted connection commands are visible through status itself;
        // only results with no other visible effect are announced.
        if (!ok) { m_notice = QString::fromUtf8(data).trimmed(); m_noticeError = true; }
        else if (action == "launcher") m_notice = label(computer) + " was added to your app launcher.";
        else if (action == "launcher-remove") m_notice = label(computer) + " was removed from your app launcher.";
        poll(); publish();
    });
}
void Manager::remove(QString computer) {
    if (m_busy.contains(computer)) return;
    const QString name = label(computer);
    auto forget = [this, computer] {
        for (qsizetype i = m_catalog.size() - 1; i >= 0; --i) if (m_catalog[i].toObject()["computer"].toString() == computer) m_catalog.removeAt(i);
        for (qsizetype i = m_sessions.size() - 1; i >= 0; --i) if (m_sessions[i].toObject()["computer"].toString() == computer) m_sessions.removeAt(i);
        m_demoDrafts.remove(computer);
    };
    m_busy.insert(computer); m_notice.clear(); m_noticeError = false; publish();
    if (m_demo) {
        QTimer::singleShot(400, this, [this, computer, name, forget] {
            m_busy.remove(computer); forget();
            m_notice = name + " was removed from the preview."; publish();
        });
        return;
    }
    process({"--json", "settings", "remove", computer}, [this, computer, name, forget](bool ok, QByteArray data) {
        m_busy.remove(computer);
        if (ok) { forget(); m_notice = name + " was removed."; }
        else { m_notice = QString::fromUtf8(data).trimmed(); m_noticeError = true; }
        loadCatalog(); poll(); publish();
    });
}
void Manager::startService() {
    if (m_serviceBusy) return;
    if (m_demo) { m_available = true; m_notice = "Preview only — the service is simulated."; m_noticeError = false; publish(); return; }
    m_serviceBusy = true; m_notice.clear(); m_noticeError = false; publish();
    process({"--json", "start"}, [this](bool ok, QByteArray data) {
        m_serviceBusy = false;
        if (!ok) { m_notice = QString::fromUtf8(data).trimmed(); m_noticeError = true; }
        poll(); publish();
    });
}
void Manager::openMoonlight() {
    if (m_demo) { m_notice = "Preview only — Moonlight would open for pairing."; m_noticeError = false; publish(); return; }
    if (m_moonlight.isEmpty() || !QProcess::startDetached(m_moonlight, {})) {
        m_notice = "Moonlight could not be started. Open it from your app launcher to pair a computer."; m_noticeError = true; publish();
    }
}
void Manager::copy(QString text) { QGuiApplication::clipboard()->setText(text); }
void Manager::demoState(QString phase) {
    if (!m_demo) return;
    if (phase == "empty") { m_catalog = {}; m_sessions = {}; publish(); return; }
    if (phase == "unavailable") { m_available = false; publish(); return; }
    if (phase == "many") {
        for (int i = 1; i <= 9; ++i) {
            const QString id = QString("extra-%1").arg(i);
            m_catalog.append(QJsonObject{{"computer", id}, {"name", QString("Office desk %1").arg(i)}, {"host", id + ".example.net"}, {"platform", "linux"}, {"default_profile", "desktop"}, {"profiles", QJsonArray{"desktop"}}});
            m_sessions.append(QJsonObject{{"computer", id}, {"phase", "idle"}, {"desired", false}});
        }
        publish(); return;
    }
    if (phase == "unconfigured") {
        m_sessions.append(QJsonObject{{"computer", "old-desk"}, {"phase", "restore-pending"}, {"desired", false}, {"recovery_pending", true},
            {"error", "host-unreachable: the host did not answer. Its original display settings are saved."}});
        publish(); return;
    }
    if (m_sessions.isEmpty()) return;
    auto s = m_sessions[0].toObject();
    s["phase"] = phase; s["desired"] = phase == "window-ready" || phase == "preflight" || phase == "connecting" || phase == "running";
    s["window"] = phase == "window-ready" ? QJsonValue(QJsonObject{{"address", "demo"}}) : QJsonValue();
    s["recovery_pending"] = phase == "restore-pending";
    s["error"] = phase == "restore-pending" ? "The host is unreachable. Its original display settings are saved; restore when it is reachable again."
               : phase == "attention" ? "host-unreachable: Sunshine did not answer on studio.example.net:47989" : "";
    if (phase == "running") { s["launched_at"] = now() - 41; s["client_version"] = "6.1.0"; s.remove("evidence"); }
    else if (phase != "window-ready") { s.remove("launched_at"); s.remove("evidence"); }
    if (phase == "preflight") { s["attempts"] = 2; s["next_retry"] = now() + 5; s["error"] = "host-unreachable: Sunshine did not answer; retrying"; }
    m_sessions[0] = s; publish();
}

void Manager::setup(QString action, QVariantMap draft) {
    static const QSet<QString> actions{"catalog", "get", "test", "save", "discover", "pair", "inspect", "install-helper"};
    if (m_setupBusy || !actions.contains(action)) return;
    m_setupBusy = true; publish();
    auto complete = [this, action, draft](bool ok, QByteArray data) {
        m_setupBusy = false;
        QJsonParseError error;
        auto document = QJsonDocument::fromJson(data, &error);
        const bool valid = ok && error.error == QJsonParseError::NoError && document.isObject();
        if (valid && action == "save" && !m_demo) {
            auto entry = QJsonObject::fromVariantMap(draft);
            entry["default_profile"] = entry["profile"];
            entry["profiles"] = QJsonArray{entry["profile"]};
            bool found = false;
            for (qsizetype i = 0; i < m_catalog.size(); ++i) if (m_catalog[i].toObject()["computer"] == entry["computer"]) {
                auto old = m_catalog[i].toObject();
                for (const auto &key : {"name", "host", "platform", "default_profile"}) old[key] = entry[key];
                m_catalog[i] = old; found = true;
            }
            if (!found) m_catalog.append(entry);
            m_notice = entry["name"].toString() + " was saved. Disconnect, then Connect to apply changes. Reconnect keeps the current session settings."; m_noticeError = false;
        }
        emit setupFinished(action, valid, valid ? document.object().toVariantMap() : QVariantMap{},
                           valid ? QString{} : ok ? "The backend returned invalid settings." : QString::fromUtf8(data).trimmed());
        if (valid && action == "save") refresh();
        publish();
    };
    if (m_demo) {
        const int delay = action == "test" || action == "inspect" ? 1100 : action == "pair" ? 2600 : action == "install-helper" ? 1600 : 300;
        QTimer::singleShot(delay, this, [this, action, draft, complete] {
            QJsonObject result;
            const QJsonObject home{{"pairing_uuid", "11111111-2222-3333-4444-555555555555"}, {"name", "Home workstation"}, {"host", "home.example.net"}, {"configured", m_demoDrafts.contains("home-workstation-11111111")}};
            const QJsonObject garage{{"pairing_uuid", "22222222-3333-4444-5555-666666666666"}, {"name", "Garage PC"}, {"host", "garage.tail-example.ts.net"}, {"configured", m_demoDrafts.contains("garage-pc-22222222")}};
            if (action == "catalog") {
                QJsonArray paired{home};
                if (m_demoPaired.contains("garage")) paired.append(garage);
                result = QJsonObject{{"revision", "preview"}, {"paired", paired}};
            } else if (action == "discover") {
                result = QJsonObject{{"revision", "preview"}, {"candidates", QJsonArray{
                    QJsonObject{{"name", "Garage PC"}, {"host", "garage.tail-example.ts.net"}, {"platform", "windows"}, {"source", "tailscale"}, {"online", true}, {"pairing_uuid", m_demoPaired.contains("garage") ? QJsonValue("22222222-3333-4444-5555-666666666666") : QJsonValue()}, {"configured", m_demoDrafts.contains("garage-pc-22222222")}, {"addresses", QJsonArray{"garage.tail-example.ts.net", "100.64.0.9"}}},
                    QJsonObject{{"name", "Home workstation"}, {"host", "home.example.net"}, {"platform", "linux"}, {"source", "lan"}, {"online", true}, {"pairing_uuid", "11111111-2222-3333-4444-555555555555"}, {"configured", m_demoDrafts.contains("home-workstation-11111111")}, {"addresses", QJsonArray{"home.example.net", "192.168.1.20"}}},
                    QJsonObject{{"name", "Mac mini"}, {"host", "mini.tail-example.ts.net"}, {"platform", "macos"}, {"source", "tailscale"}, {"online", false}, {"pairing_uuid", QJsonValue()}, {"configured", false}, {"addresses", QJsonArray{"mini.tail-example.ts.net"}}}}}};
            } else if (action == "pair") {
                if (draft["pin"].toString() == "0000") { complete(false, "pairing-failed: Failed to pair: incorrect PIN"); return; }
                m_demoPaired.insert("garage");
                result = QJsonObject{{"revision", "preview"}, {"paired", QJsonObject{{"paired", true}, {"pairing_uuid", "22222222-3333-4444-5555-666666666666"}, {"name", "Garage PC"}, {"host", draft["host"].toString()}}}};
            } else if (action == "inspect") {
                if (draft["platform"].toString() == "windows" && draft["adapter"].toString() == "virtual") {
                    result = QJsonObject{{"platform", "windows"}, {"virtual", QJsonObject{
                        {"sunshine_output", "{ABCDEF01-1111-2222-3333-444444444444}"}, {"dd_resolution_option", "auto"},
                        {"modes", QJsonArray{"1920x1080", "2560x1440"}}, {"driver_pipe", true}}}};
                } else if (draft["platform"].toString() == "windows") {
                    result = QJsonObject{{"platform", "windows"}, {"sunshine_output", "{ABCDEF01-1111-2222-3333-444444444444}"},
                        {"helper", QJsonObject{{"installed", m_demoHelpers.contains(draft["computer"].toString())}, {"phase", "idle"}}},
                        {"displays", QJsonArray{QJsonObject{{"id", "\\\\?\\DISPLAY#MTT1337#5&2c4d1f3&0&UID4352#{e6f07b5f}"}, {"name", "Virtual display"}, {"active", false}, {"available", true}, {"internal", false}, {"hardware", "MTT1337"}, {"width", 2560}, {"height", 1440}},
                                               QJsonObject{{"id", "\\\\?\\DISPLAY#BOE0A1B#4&1&0&UID256#{e6f07b5f}"}, {"name", "Built-in panel"}, {"active", true}, {"available", true}, {"internal", true}, {"hardware", "BOE0A1B"}, {"width", 1920}, {"height", 1200}}}}};
                } else {
                    const QJsonArray modes{QJsonObject{{"resolution", "2560x1440"}, {"hidpi", true}, {"refresh", 60}}, QJsonObject{{"resolution", "3840x2160"}, {"hidpi", false}, {"refresh", 60}}, QJsonObject{{"resolution", "1920x1080"}, {"hidpi", true}, {"refresh", 60}}};
                    result = QJsonObject{{"platform", "macos"}, {"betterdisplay", true}, {"ac_power", true}, {"lid_closed", false},
                        {"displays", QJsonArray{QJsonObject{{"uuid", "AAAAAAAA-1111-2222-3333-444444444444"}, {"name", "Studio Display"}, {"main", true}, {"builtin", false}, {"current", modes[0]}, {"modes", modes}},
                                               QJsonObject{{"uuid", "BBBBBBBB-1111-2222-3333-444444444444"}, {"name", "Built-in Retina Display"}, {"main", false}, {"builtin", true}, {"current", QJsonObject{{"resolution", "1728x1117"}, {"hidpi", true}, {"refresh", 120}}}, {"modes", QJsonArray{QJsonObject{{"resolution", "1728x1117"}, {"hidpi", true}, {"refresh", 120}}}}}}}};
                }
            } else if (action == "install-helper") {
                m_demoHelpers.insert(draft["computer"].toString());
                result = QJsonObject{{"ok", true}};
            } else if (action == "get") {
                auto id = draft["computer"].toString();
                if (m_demoDrafts.contains(id)) result = QJsonObject::fromVariantMap(m_demoDrafts[id]);
                else for (const auto &entry : m_catalog) if (entry.toObject()["computer"].toString() == id) {
                    result = entry.toObject(); result["profile"] = "desktop"; result["revision"] = "preview";
                    result["stream_resolution"] = "1920x1080"; result["fps"] = 60; result["bitrate"] = 30000;
                    result["codec"] = "auto"; result["input"] = "absolute"; result["audio"] = "focus";
                    result["profiles"] = QJsonObject{{"desktop", QJsonObject{{"stream_resolution", "1920x1080"}, {"fps", 60}, {"bitrate", 30000}}}};
                }
            } else if (action == "test") {
                result["tested"] = true;
                const auto adapter = draft["display"].toMap()["adapter"].toString();
                result["restoration"] = adapter.isEmpty() || adapter == "external" ? "externally-managed" : "managed";
            } else {
                auto saved = draft; saved.remove("pairing_uuid");
                saved["profiles"] = QVariantMap{{draft["profile"].toString(), draft}};
                m_demoDrafts[draft["computer"].toString()] = saved;
                auto entry = QJsonObject::fromVariantMap(draft);
                entry["default_profile"] = entry["profile"]; entry["profiles"] = QJsonArray{entry["profile"]};
                bool found = false;
                for (qsizetype i=0; i<m_catalog.size(); ++i) if (m_catalog[i].toObject()["computer"] == entry["computer"]) { m_catalog[i] = entry; found = true; }
                if (!found) { m_catalog.append(entry); m_sessions.append(QJsonObject{{"computer", entry["computer"]}, {"phase", "idle"}, {"desired", false}}); }
                result["saved"] = true; result["computer"] = entry["computer"];
                m_notice = entry["name"].toString() + " was saved in the preview."; m_noticeError = false;
            }
            complete(true, QJsonDocument(result).toJson(QJsonDocument::Compact));
        });
        return;
    }
    QStringList arguments{"--json", "settings", action};
    if (action == "get") arguments << draft["computer"].toString();
    // Pairing waits for a PIN typed on the host; installation and probes run over SSH.
    const int deadline = action == "pair" || action == "install-helper" ? 150000 : action == "inspect" || action == "test" ? 100000 : 60000;
    process(arguments, complete, QJsonDocument(QJsonObject::fromVariantMap(draft)).toJson(QJsonDocument::Compact), deadline);
}
