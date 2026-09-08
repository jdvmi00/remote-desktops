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
    Q_PROPERTY(bool noticeError READ noticeError NOTIFY changed)
    Q_PROPERTY(bool loading READ loading NOTIFY changed)
    Q_PROPERTY(bool available READ available NOTIFY changed)
    Q_PROPERTY(bool setupBusy READ setupBusy NOTIFY changed)
    Q_PROPERTY(bool serviceBusy READ serviceBusy NOTIFY changed)
    Q_PROPERTY(bool moonlightAvailable READ moonlightAvailable CONSTANT)
    Q_PROPERTY(bool demo READ demo CONSTANT)
    Q_PROPERTY(QVariantMap keyboard READ keyboard NOTIFY changed)
    Q_PROPERTY(bool keyboardBusy READ keyboardBusy NOTIFY changed)
    Q_PROPERTY(QVariantMap windowRule READ windowRule NOTIFY changed)
public:
    explicit Manager(QString backend, QString socket, bool demo = false, QObject *parent = nullptr);
    QVariantList computers() const;
    QString error() const { return m_error; }
    QString notice() const { return m_notice; }
    bool noticeError() const { return m_noticeError; }
    bool loading() const { return m_loading; }
    bool available() const { return m_available; }
    bool setupBusy() const { return m_setupBusy; }
    bool serviceBusy() const { return m_serviceBusy; }
    bool moonlightAvailable() const { return !m_moonlight.isEmpty(); }
    Q_INVOKABLE void setup(QString action, QVariantMap draft = {});
    bool demo() const { return m_demo; }
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void setActive(bool active);
    Q_INVOKABLE void act(QString computer, QString action, QString profile = {});
    Q_INVOKABLE void remove(QString computer);
    Q_INVOKABLE void startService();
    Q_INVOKABLE void openMoonlight();
    Q_INVOKABLE void copy(QString text);
    Q_INVOKABLE void notify(QString text, bool error = false);
    Q_INVOKABLE void clearNotice();
    Q_INVOKABLE void demoState(QString phase);
    QVariantMap keyboard() const { return m_keyboard.toVariantMap(); }
    bool keyboardBusy() const { return m_keyboardBusy; }
    Q_INVOKABLE void loadKeyboard();
    Q_INVOKABLE void saveKeyboard(QVariantMap draft);
    QVariantMap windowRule() const;
    Q_INVOKABLE void setWindowRule(bool tiled);
    void poll();
signals:
    void changed();
    void keyboardFinished(bool ok, QString error);
    void setupFinished(QString action, bool ok, QVariantMap result, QString error);
private:
    void publish();
    void loadCatalog();
    void loadWindowRule();
    QString label(const QString &computer) const;
    void process(QStringList arguments, std::function<void(bool, QByteArray)> complete, QByteArray input = {}, int deadline = 60000);
    QString m_backend, m_socketPath, m_error, m_notice, m_moonlight;
    bool m_demo, m_loading = true, m_available = false, m_active = true, m_catalogLoading = false;
    bool m_noticeError = false, m_setupBusy = false, m_serviceBusy = false, m_windowRuleBusy = false;
    QJsonObject m_windowRule, m_keyboard;
    bool m_keyboardBusy = false;
    QJsonArray m_catalog, m_sessions;
    QSet<QString> m_busy;
    QMap<QString, QVariantMap> m_demoDrafts;
    QSet<QString> m_demoPaired, m_demoHelpers, m_demoLaunchers;
    QTimer m_poll;
    QLocalSocket *m_socket = nullptr;
};
