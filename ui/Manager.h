#pragma once
#include <QObject>
#include <QJsonArray>
#include <QJsonObject>
#include <QProcess>
#include <QLocalSocket>
#include <QTimer>
#include <QVariantList>
#include <QSet>
#include <functional>
#include <memory>

class Manager : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantList computers READ computers NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
    Q_PROPERTY(QString notice READ notice NOTIFY changed)
    Q_PROPERTY(bool loading READ loading NOTIFY changed)
    Q_PROPERTY(bool available READ available NOTIFY changed)
    Q_PROPERTY(bool setupBusy READ setupBusy NOTIFY changed)
    Q_PROPERTY(bool demo READ demo CONSTANT)
public:
    explicit Manager(QString backend, QString socket, bool demo = false, QObject *parent = nullptr);
    QVariantList computers() const;
    QString error() const { return m_error; }
    QString notice() const { return m_notice; }
    bool loading() const { return m_loading; }
    bool available() const { return m_available; }
    bool setupBusy() const { return m_setupBusy; }
    Q_INVOKABLE void setup(QString action, QVariantMap draft = {});
    bool demo() const { return m_demo; }
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void setActive(bool active);
    Q_INVOKABLE void act(QString computer, QString action, QString profile = {});
    Q_INVOKABLE void copy(QString text);
    Q_INVOKABLE void clearNotice();
    Q_INVOKABLE void demoState(QString phase);
    void poll();
signals:
    void changed();
    void setupFinished(QString action, bool ok, QVariantMap result, QString error);
private:
    void publish();
    void loadCatalog();
    void process(QStringList arguments, std::function<void(bool, QByteArray)> complete, QByteArray input = {});
    QString m_backend, m_socketPath, m_error, m_notice;
    bool m_demo, m_loading = true, m_available = false, m_active = true, m_catalogLoading = false;
    QJsonArray m_catalog, m_sessions;
    QSet<QString> m_busy;
    bool m_setupBusy = false;
    QMap<QString, QVariantMap> m_demoDrafts;
    QTimer m_poll;
    QLocalSocket *m_socket = nullptr;
};
