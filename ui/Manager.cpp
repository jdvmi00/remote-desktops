#include "Manager.h"
#include <QClipboard>
#include <QGuiApplication>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QPointer>
#include <QRegularExpression>
#include <utility>

Manager::Manager(QString backend, QString socket, bool demo, QObject *parent)
    : QObject(parent), m_backend(std::move(backend)), m_socketPath(std::move(socket)), m_demo(demo) {
    m_poll.setInterval(2000);
    connect(&m_poll, &QTimer::timeout, this, &Manager::poll);
    if (m_demo) {
        m_catalog = QJsonDocument::fromJson(R"([
          {"computer":"studio","name":"Studio Mac","host":"studio.example.net","platform":"macos","default_profile":"desktop","profiles":["desktop","presentation"]},
          {"computer":"work","name":"Work laptop","host":"work.example.net","platform":"windows","default_profile":"desktop","profiles":["desktop"]},
          {"computer":"lab","name":"Linux workstation","host":"lab.example.net","platform":"linux","default_profile":"desktop","profiles":["desktop"]}
        ])").array();
        m_sessions = QJsonDocument::fromJson(R"([{"computer":"studio","profile":"desktop","phase":"window-ready","desired":true,"window":{"address":"demo"}},{"computer":"work","phase":"idle","desired":false},{"computer":"lab","phase":"idle","desired":false}])").array();
        m_available = true; m_loading = false;
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
        out.append(item.toVariantMap());
    }
    return out;
}
void Manager::publish() { emit changed(); }
void Manager::clearNotice() { m_notice.clear(); publish(); }
void Manager::setActive(bool active) {
    m_active = active;
    if (m_demo) return;
    if (active) { m_poll.start(); poll(); } else m_poll.stop();
}
void Manager::refresh() {
    if (m_demo) { publish(); return; }
    loadCatalog(); poll();
}
void Manager::process(QStringList arguments, std::function<void(bool, QByteArray)> complete) {
    auto *job = new QProcess(this);
    auto *deadline = new QTimer(job);
    deadline->setSingleShot(true);
    auto output = std::make_shared<QByteArray>();
    auto failure = std::make_shared<QByteArray>();
    auto done = std::make_shared<bool>(false);
    auto finish = [job, deadline, complete, done](bool ok, QByteArray data) {
        if (std::exchange(*done, true)) return;
        deadline->stop(); complete(ok, data); job->deleteLater();
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
        finish(ok, ok ? *output : (failure->isEmpty() ? QByteArray("The request failed. Refresh to check the current state.") : *failure));
    });
    connect(deadline, &QTimer::timeout, this, [job, finish] {
        job->kill(); finish(false, "The request timed out. Its outcome may still be pending; refresh before retrying.");
    });
    job->start(m_backend, arguments);
    deadline->start(60000);
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
    static const QSet<QString> allowed{"connect", "disconnect", "reconnect", "restore", "focus", "launcher"};
    if (!allowed.contains(action) || m_busy.contains(computer)) return;
    bool known = false;
    for (const auto &entry : computers()) if (entry.toMap()["computer"].toString() == computer) known = true;
    if (!known) return;
    if (m_demo) {
        m_busy.insert(computer); publish();
        QTimer::singleShot(650, this, [this, computer, action, profile] {
            for (qsizetype i = 0; i < m_sessions.size(); ++i) if (m_sessions[i].toObject()["computer"].toString() == computer) {
                auto s = m_sessions[i].toObject();
                if (action != "focus" && action != "launcher") {
                    bool connected = action == "connect" || action == "reconnect";
                    s["phase"] = connected ? "window-ready" : "idle"; s["desired"] = connected;
                    s["window"] = connected ? QJsonValue(QJsonObject{{"address", "demo"}}) : QJsonValue();
                    s["error"] = QJsonValue(); s["recovery_pending"] = false;
                    if (!profile.isEmpty()) s["profile"] = profile;
                    m_sessions[i] = s;
                }
            }
            m_busy.remove(computer); m_notice = "Preview only — no real computer was changed."; publish();
        });
        return;
    }
    QStringList args{"--json"};
    if (action == "launcher") args << "launcher" << "install" << computer;
    else args << action << computer;
    if (action == "connect" && !profile.isEmpty()) args << "--profile" << profile;
    m_busy.insert(computer); m_notice.clear(); publish();
    process(args, [this, computer, action](bool ok, QByteArray data) {
        m_busy.remove(computer);
        m_notice = ok ? (action == "launcher" ? "Launcher added. Find this computer in your app launcher and Scenes." : "Request accepted. Connection status will update shortly.")
                      : QString::fromUtf8(data).trimmed();
        poll(); publish();
    });
}
void Manager::copy(QString text) { QGuiApplication::clipboard()->setText(text); }
void Manager::demoState(QString phase) {
    if (!m_demo) return;
    if (phase == "empty") { m_catalog = {}; m_sessions = {}; publish(); return; }
    if (phase == "unavailable") { m_available = false; publish(); return; }
    if (m_sessions.isEmpty()) return;
    auto s = m_sessions[0].toObject();
    s["phase"] = phase; s["desired"] = phase == "window-ready" || phase == "preflight";
    s["window"] = phase == "window-ready" ? QJsonValue(QJsonObject{{"address", "demo"}}) : QJsonValue();
    s["recovery_pending"] = phase == "restore-pending";
    s["error"] = phase == "restore-pending" ? "The host is unreachable. Its original display settings are saved; restore when it is reachable again." : "";
    m_sessions[0] = s; publish();
}
