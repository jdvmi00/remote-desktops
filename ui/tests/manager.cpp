#include "../Manager.h"
#include "../Theme.h"
#include <QtTest>
#include <QLocalServer>
#include <QTemporaryDir>
#include <QFile>
#include <QSaveFile>
#include <QJsonDocument>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QQuickItem>
#include <QQuickStyle>
#include <cmath>

class ManagerTests : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QQuickStyle::setStyle("Basic"); QGuiApplication::setQuitOnLastWindowClosed(false); }
    void realQmlSelectionActionsAndRecovery() {
        Manager m("/missing", "/missing", true);
        Theme theme("/missing/palette");
        QQmlApplicationEngine engine;
        QSignalSpy warnings(&engine, &QQmlEngine::warnings);
        engine.rootContext()->setContextProperty("manager", &m);
        engine.rootContext()->setContextProperty("theme", &theme);
        engine.load(QUrl("qrc:/qml/Main.qml"));
        QVERIFY(!engine.rootObjects().isEmpty());
        auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        QVERIFY(window);
        auto *primary = window->findChild<QObject *>("primaryAction");
        QVERIFY(primary);
        QCOMPARE(primary->property("text").toString(), QString("Open desktop"));
        auto *list = window->findChild<QQuickItem *>("computerList");
        QVERIFY(list); list->forceActiveFocus();
        QTest::keyClick(window, Qt::Key_Down);
        QCOMPARE(window->property("selectedId").toString(), QString("work"));
        QCOMPARE(primary->property("text").toString(), QString("Connect"));
        QVERIFY(QMetaObject::invokeMethod(primary, "clicked"));
        QVERIFY(!primary->property("enabled").toBool());
        QTRY_COMPARE(primary->property("text").toString(), QString("Open desktop"));
        window->setProperty("selectedId", "studio");
        m.demoState("restore-pending");
        QCOMPARE(primary->property("text").toString(), QString("Restore display"));
        QVERIFY(QMetaObject::invokeMethod(primary, "clicked"));
        QTRY_COMPARE(primary->property("text").toString(), QString("Connect"));
        auto *help = window->findChild<QObject *>("helpDialog");
        QVERIFY(help); QVERIFY(QMetaObject::invokeMethod(help, "open"));
        QTest::keyClick(window, Qt::Key_Escape);
        QTRY_VERIFY(!help->property("visible").toBool());
        // Preferences: the tiled-window rule toggles through the manager and reads back.
        auto *preferences = window->findChild<QObject *>("preferencesDialog");
        QVERIFY(preferences); QVERIFY(QMetaObject::invokeMethod(preferences, "open"));
        auto *tiled = preferences->findChild<QObject *>("tiledCheck");
        QVERIFY(tiled);
        QVERIFY(!tiled->property("checked").toBool());
        QVERIFY(tiled->property("enabled").toBool());
        tiled->setProperty("checked", true);
        QVERIFY(QMetaObject::invokeMethod(tiled, "toggled"));
        QVERIFY(m.windowRule()["busy"].toBool());
        QTRY_VERIFY(m.windowRule()["installed"].toBool());
        QVERIFY(tiled->property("checked").toBool());
        QVERIFY(m.notice().contains("tiled"));
        QTest::keyClick(window, Qt::Key_Escape);
        QTRY_VERIFY(!preferences->property("visible").toBool());
        QCOMPARE(warnings.count(), 0);
        window->close();
        QCOMPARE(m.computers()[1].toMap()["phase"].toString(), QString("window-ready"));
    }
    void guidedSetupTestGateEditAndCancel() {
        Manager m("/must-not-run", "/must-not-connect", true);
        Theme theme("/missing/palette");
        QQmlApplicationEngine engine;
        QSignalSpy warnings(&engine, &QQmlEngine::warnings);
        engine.rootContext()->setContextProperty("manager", &m);
        engine.rootContext()->setContextProperty("theme", &theme);
        engine.load(QUrl("qrc:/qml/Main.qml"));
        QVERIFY(!engine.rootObjects().isEmpty());
        auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        auto *dialog = window->findChild<QObject *>("setupDialog");
        QVERIFY(dialog);
        QVERIFY(QMetaObject::invokeMethod(dialog, "begin", Q_ARG(QVariant, QVariant(""))));
        QTRY_VERIFY(dialog->property("loaded").toBool());
        QTRY_VERIFY(!dialog->property("discovering").toBool());
        QVariantMap host{{"name", "Home workstation"}, {"host", "home.example.net"}, {"pairing_uuid", "11111111-2222-3333-4444-555555555555"}};
        QVERIFY(QMetaObject::invokeMethod(dialog, "choose", Q_ARG(QVariant, QVariant(host)), Q_ARG(QVariant, QVariant(""))));
        auto *next = dialog->findChild<QObject *>("setupNext");
        QVERIFY(next);
        QVERIFY(next->property("enabled").toBool());
        QVERIFY(QMetaObject::invokeMethod(next, "clicked"));
        QCOMPARE(dialog->property("step").toInt(), 2);
        QVERIFY(!next->property("enabled").toBool());
        QVERIFY(m.setupBusy()); // The check starts on its own when the last step opens.
        QTRY_VERIFY(next->property("enabled").toBool());
        QVERIFY(QMetaObject::invokeMethod(dialog, "set", Q_ARG(QVariant, QVariant("name")), Q_ARG(QVariant, QVariant("My home computer"))));
        QVERIFY(!next->property("enabled").toBool());
        QVERIFY(QMetaObject::invokeMethod(dialog, "check"));
        QTRY_VERIFY(next->property("enabled").toBool());
        QVERIFY(QMetaObject::invokeMethod(next, "clicked"));
        QTRY_VERIFY(!dialog->property("visible").toBool());
        QCOMPARE(m.computers().size(), 4);
        QCOMPARE(m.computers().last().toMap()["name"].toString(), QString("My home computer"));
        QVERIFY(QMetaObject::invokeMethod(dialog, "begin", Q_ARG(QVariant, QVariant("home-workstation-11111111"))));
        QTRY_VERIFY(dialog->property("loaded").toBool());
        QCOMPARE(dialog->property("step").toInt(), 1);
        QVERIFY(QMetaObject::invokeMethod(dialog, "set", Q_ARG(QVariant, QVariant("name")), Q_ARG(QVariant, QVariant("Discard me"))));
        QTest::keyClick(window, Qt::Key_Escape);
        auto *discard = dialog->findChild<QObject *>("confirmAction");
        QVERIFY(discard);
        QTRY_VERIFY(discard->property("visible").toBool()); // Escape asks before discarding edits.
        QVERIFY(dialog->property("visible").toBool());
        QVERIFY(QMetaObject::invokeMethod(discard, "clicked"));
        QTRY_VERIFY(!dialog->property("visible").toBool());
        QCOMPARE(m.computers().last().toMap()["name"].toString(), QString("My home computer"));
        QCOMPARE(m.computers().first().toMap()["phase"].toString(), QString("window-ready"));
        QCOMPARE(warnings.count(), 0);
    }
    void setupReadFailuresAndInitialCatalogErrorStayVisible() {
        QTemporaryDir temp;
        const QString binary = temp.path() + "/backend";
        auto script = [&](const QByteArray &body) {
            QFile file(binary); QVERIFY(file.open(QIODevice::WriteOnly | QIODevice::Truncate));
            file.write("#!/bin/sh\n" + body); file.close();
            QVERIFY(file.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner));
        };
        script("echo 'catalog cannot be read' >&2\nexit 1\n");
        Manager m(binary, temp.path() + "/missing.socket");
        Theme theme("/missing/palette");
        QQmlApplicationEngine engine;
        QSignalSpy warnings(&engine, &QQmlEngine::warnings);
        engine.rootContext()->setContextProperty("manager", &m);
        engine.rootContext()->setContextProperty("theme", &theme);
        engine.load(QUrl("qrc:/qml/Main.qml"));
        QVERIFY(!engine.rootObjects().isEmpty());
        auto *window = engine.rootObjects().first();
        QTRY_VERIFY(!m.loading());
        QVERIFY(window->findChild<QObject *>("serviceBanner")->property("visible").toBool());
        QVERIFY(!window->findChild<QObject *>("firstComputerHeading")->property("visible").toBool());
        auto *dialog = window->findChild<QObject *>("setupDialog");
        QVERIFY(QMetaObject::invokeMethod(dialog, "begin", Q_ARG(QVariant, QVariant(""))));
        QTRY_VERIFY(!m.setupBusy());
        QCOMPARE(dialog->property("errorAction").toString(), QString("catalog"));
        QVERIFY(!dialog->property("discovering").toBool());
        QVERIFY(dialog->findChild<QObject *>("setupReadRetry")->property("visible").toBool());
        script(R"(if [ "$3" = catalog ]; then
printf '%s\n' '{"paired":[],"revision":"test"}'
else echo 'discovery transport failed' >&2; exit 1; fi
)");
        QVERIFY(QMetaObject::invokeMethod(dialog, "retryRead"));
        QTRY_COMPARE(dialog->property("errorAction").toString(), QString("discover"));
        QVERIFY(dialog->property("loaded").toBool());
        QVERIFY(!dialog->property("discovering").toBool());
        QVERIFY(dialog->property("error").toString().contains("discovery transport failed"));
        script(R"(printf '%s\n' '{"candidates":[],"warnings":["Local network discovery unavailable"]}'
)");
        QVERIFY(QMetaObject::invokeMethod(dialog, "retryRead"));
        QTRY_VERIFY(!m.setupBusy());
        QVERIFY(dialog->property("error").toString().isEmpty());
        QCOMPARE(dialog->property("discoveryWarning").toString(), QString("Local network discovery unavailable"));
        QVERIFY(QMetaObject::invokeMethod(dialog, "close"));
        script("echo 'get unavailable' >&2\nexit 1\n");
        QVERIFY(QMetaObject::invokeMethod(dialog, "begin", Q_ARG(QVariant, QVariant("saved-pc"))));
        QTRY_VERIFY(!m.setupBusy());
        QCOMPARE(dialog->property("errorAction").toString(), QString("get"));
        QVERIFY(!dialog->findChild<QObject *>("setupLoadingSettings")->property("visible").toBool());
        script(R"(if [ "$4" != saved-pc ]; then echo 'lost computer identity' >&2; exit 1; fi
printf '%s\n' '{"computer":"saved-pc","name":"Saved PC","host":"pc.example","platform":"windows","profile":"desktop","profiles":{},"stream_resolution":"1920x1080","display":{"adapter":"sunshine"}}'
)");
        QVERIFY(QMetaObject::invokeMethod(dialog, "retryRead"));
        QTRY_VERIFY(dialog->property("loaded").toBool());
        QCOMPARE(dialog->property("draft").toMap()["computer"].toString(), QString("saved-pc"));
        QCOMPARE(warnings.count(), 0);
    }
    void retryCountsMatchScheduledBackendRetries() {
        QTemporaryDir temp;
        const QString binary = temp.path() + "/backend";
        QFile script(binary); QVERIFY(script.open(QIODevice::WriteOnly));
        script.write(R"(#!/bin/sh
printf '%s\n' '[{"computer":"retry-pc","profiles":["desktop"]}]'
)"); script.close();
        QVERIFY(script.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner));
        QLocalServer server; QVERIFY(server.listen(temp.path() + "/status.socket"));
        int attempt = 1;
        connect(&server, &QLocalServer::newConnection, &server, [&] {
            auto *socket = server.nextPendingConnection();
            connect(socket, &QLocalSocket::readyRead, socket, [&, socket] {
                socket->readAll();
                QJsonObject session{{"computer", "retry-pc"}, {"phase", "preflight"}, {"desired", true},
                    {"attempts", attempt}, {"next_retry", QDateTime::currentSecsSinceEpoch() + 60}};
                socket->write(QJsonDocument(QJsonObject{{"ok", true}, {"result", QJsonObject{{"computers", QJsonArray{session}}}}}).toJson(QJsonDocument::Compact) + "\n");
            });
            connect(socket, &QLocalSocket::disconnected, socket, &QObject::deleteLater);
        });
        Manager m(binary, server.fullServerName());
        Theme theme("/missing/palette");
        QQmlApplicationEngine engine;
        engine.rootContext()->setContextProperty("manager", &m);
        engine.rootContext()->setContextProperty("theme", &theme);
        engine.load(QUrl("qrc:/qml/Main.qml"));
        QVERIFY(!engine.rootObjects().isEmpty());
        for (attempt = 1; attempt <= 3; ++attempt) {
            m.setActive(true); m.poll();
            QTRY_VERIFY(!m.computers().isEmpty() && m.computers().first().toMap()["attempts"].toInt() == attempt);
            const auto facts = engine.rootObjects().first()->property("facts").value<QJSValue>().toVariant().toList();
            bool found = false;
            for (const auto &fact : facts) if (fact.toMap()["label"] == "Next attempt") {
                QVERIFY(fact.toMap()["value"].toString().contains(QString("retry %1 of 3").arg(attempt)));
                found = true;
            }
            QVERIFY(found);
        }
    }
    void inspectionSubjectChangesDiscardOldHostEvidence() {
        Manager m("/missing", "/missing", true);
        Theme theme("/missing/palette");
        QQmlApplicationEngine engine;
        QSignalSpy warnings(&engine, &QQmlEngine::warnings);
        engine.rootContext()->setContextProperty("manager", &m);
        engine.rootContext()->setContextProperty("theme", &theme);
        engine.load(QUrl("qrc:/qml/Main.qml"));
        auto *dialog = engine.rootObjects().first()->findChild<QObject *>("setupDialog");
        QVERIFY(QMetaObject::invokeMethod(dialog, "begin", Q_ARG(QVariant, QVariant("work"))));
        QTRY_VERIFY(dialog->property("loaded").toBool());
        QVariantMap draft{{"host", "a.example"}, {"platform", "windows"}, {"ssh", QVariantMap{{"alias", "pc-a"}}},
            {"display", QVariantMap{{"adapter", "windows"}, {"device_id", "display-a"}}}};
        const QVariantMap inspection{{"platform", "windows"}, {"helper", QVariantMap{{"installed", false}}}};
        auto change = [&](QString key, QVariant value) {
            QVERIFY(QMetaObject::invokeMethod(dialog, "set", Q_ARG(QVariant, QVariant(key)), Q_ARG(QVariant, value)));
        };
        dialog->setProperty("draft", draft); dialog->setProperty("inspection", inspection);
        change("name", "New name"); change("bitrate", 45000);
        QCOMPARE(dialog->property("inspection").toMap(), inspection);
        for (const auto &entry : QVariantMap{{"host", "b.example"}, {"platform", "macos"}, {"ssh", QVariantMap{{"alias", "pc-b"}}},
                {"display", QVariantMap{{"adapter", "virtual"}}}}.asKeyValueRange()) {
            dialog->setProperty("draft", draft); dialog->setProperty("inspection", inspection);
            change(entry.first, entry.second);
            QVERIFY(dialog->property("inspection").toMap().isEmpty());
            QVERIFY(!dialog->findChild<QObject *>("setupInstall")->property("visible").toBool());
        }
        QCOMPARE(warnings.count(), 0);
    }
    void themeSurvivesAtomicFilesAndDirectoryReplacement() {
        QTemporaryDir temp;
        QString directory = temp.path() + "/current/theme";
        QString path = directory + "/colors.toml";
        Theme theme(path); // Theme may be installed after the app starts.
        const auto fallback = theme.colors();
        auto write = [&](QByteArray bg) {
            QVERIFY(QDir().mkpath(directory));
            QSaveFile file(path); QVERIFY(file.open(QIODevice::WriteOnly));
            file.write("background = \"" + bg + "\"\nforeground = \"#eeeeee\"\naccent = \"#88ccaa\"\n");
            QVERIFY(file.commit());
        };
        write("#202020");
        QTRY_COMPARE(theme.colors()["bg"].value<QColor>(), QColor("#202020"));
        QVERIFY(theme.colors() != fallback);
        write("#303030");
        QTRY_COMPARE(theme.colors()["bg"].value<QColor>(), QColor("#303030"));
        QVERIFY(QDir().rename(directory, temp.path() + "/retired"));
        write("#404040");
        QTRY_COMPARE(theme.colors()["bg"].value<QColor>(), QColor("#404040"));
        write("#505050"); // Watch is rearmed on the new directory inode.
        QTRY_COMPARE(theme.colors()["bg"].value<QColor>(), QColor("#505050"));
        auto valid = theme.colors();
        QFile partial(path); QVERIFY(partial.open(QIODevice::WriteOnly | QIODevice::Truncate));
        partial.write("background = \"broken\"\n"); partial.close();
        QTest::qWait(200);
        QCOMPARE(theme.colors(), valid);
        QSignalSpy changes(&theme, &Theme::changed);
        write("#505050"); QTest::qWait(200);
        QCOMPARE(changes.count(), 0);
    }
    void lightPaletteUsesReadableActionText() {
        auto colors = Theme::palette({{"background", QColor("#ffffff")}, {"foreground", QColor("#222222")}, {"accent", QColor("#385ac3")}});
        QCOMPARE(colors["bg"].value<QColor>(), QColor("#ffffff"));
        QVERIFY(colors["onAccent"].value<QColor>().lightnessF() > .8);
        QVERIFY(colors["muted"].value<QColor>().lightnessF() < .5);
        QVERIFY(colors["warning"].value<QColor>().lightnessF() < .6);
    }
    void demoNeverTouchesBackend() {
        Manager m("/does/not/exist", "/does/not/exist", true);
        QCOMPARE(m.computers().size(), 3);
        m.act("studio", "disconnect");
        QVERIFY(m.computers()[0].toMap()["busy"].toBool());
        m.act("studio", "connect"); // One pending command per computer.
        QTRY_COMPARE(m.computers()[0].toMap()["phase"].toString(), "idle");
        m.demoState("restore-pending");
        QVERIFY(m.computers()[0].toMap()["recovery_pending"].toBool());
        m.act("studio", "restore");
        QTRY_COMPARE(m.computers()[0].toMap()["phase"].toString(), "idle");
        m.act("studio", "release"); // No implicit abandonment of recovery.
        QVERIFY(!m.computers()[0].toMap()["busy"].toBool());
    }
    void refitRequiresBackendCapability() {
        QTemporaryDir temp;
        QFile script(temp.path() + "/backend");
        QVERIFY(script.open(QIODevice::WriteOnly));
        script.write("#!/bin/sh\nprintf '[]\\n'\n");
        script.close();
        script.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner);
        QLocalServer server;
        QVERIFY(server.listen(temp.path() + "/control.sock"));
        QJsonObject session{{"computer", "test"}, {"platform", "macos"}, {"phase", "window-ready"},
            {"desired", true}, {"window", QJsonObject{{"address", "fake"}}}};
        connect(&server, &QLocalServer::newConnection, this, [&] {
            auto *socket = server.nextPendingConnection();
            connect(socket, &QLocalSocket::disconnected, socket, &QObject::deleteLater);
            connect(socket, &QLocalSocket::readyRead, socket, [&, socket] {
                socket->readAll();
                socket->write(QJsonDocument(QJsonObject{{"ok", true}, {"result", QJsonObject{{"computers", QJsonArray{session}}}}}).toJson(QJsonDocument::Compact) + "\n");
            });
        });
        Manager m(script.fileName(), server.fullServerName());
        QTRY_VERIFY(m.available());
        Theme theme("/missing/palette");
        QQmlApplicationEngine engine;
        engine.rootContext()->setContextProperty("manager", &m);
        engine.rootContext()->setContextProperty("theme", &theme);
        engine.load(QUrl("qrc:/qml/Main.qml"));
        QVERIFY(!engine.rootObjects().isEmpty());
        auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        auto *refit = window->findChild<QObject *>("refitAction");
        QVERIFY(refit);
        QVERIFY(!refit->property("visible").toBool()); // Older status replies cannot authorize Refit.
        session["platform"] = "windows";
        session["refit_available"] = true;
        m.poll();
        QTRY_VERIFY(refit->property("visible").toBool());
        QVERIFY(refit->property("enabled").toBool());
        session["refit_available"] = false;
        m.poll();
        QTRY_VERIFY(!refit->property("visible").toBool()); // Verification can expire while connected.
        QVERIFY(!refit->property("enabled").toBool());
        window->close();
    }
    void statusIsFramedAndStaleRecordsSurvive() {
        QTemporaryDir temp;
        auto binary = temp.path() + "/backend";
        QFile script(binary); QVERIFY(script.open(QIODevice::WriteOnly));
        script.write("#!/bin/sh\nprintf '%s\\n' '[{\"computer\":\"test\",\"name\":\"Test\",\"profiles\":[\"desktop\"]}]'\n");
        script.close(); script.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner);
        QLocalServer server; QVERIFY(server.listen(temp.path() + "/control.sock"));
        bool valid = true;
        connect(&server, &QLocalServer::newConnection, this, [&] {
            auto *socket = server.nextPendingConnection();
            connect(socket, &QLocalSocket::disconnected, socket, &QObject::deleteLater);
            connect(socket, &QLocalSocket::readyRead, socket, [&, socket] {
                QCOMPARE(socket->readAll(), QByteArray("{\"command\":\"status\"}\n"));
                if (!valid) { socket->write("not json\n"); return; }
                socket->write("{\"ok\":true,\"result\":");
                QTimer::singleShot(15, socket, [socket] { socket->write("{\"computers\":[{\"computer\":\"test\",\"phase\":\"window-ready\",\"desired\":true},{\"computer\":\"removed\",\"phase\":\"restore-pending\",\"recovery_pending\":true}]}}\n"); });
            });
        });
        Manager m(binary, server.fullServerName());
        QTRY_VERIFY(!m.loading()); QTRY_VERIFY(m.available());
        QCOMPARE(m.computers().size(), 2);
        QVERIFY(m.computers()[1].toMap()["unconfigured"].toBool());
        valid = false; m.poll();
        QTRY_VERIFY(!m.available());
        QCOMPARE(m.computers().size(), 2);
        QVERIFY(m.computers()[0].toMap()["stale"].toBool());
        m.setActive(false);
        valid = true; m.poll(); QTest::qWait(30);
        QVERIFY(!m.available());
        m.setActive(true); QTRY_VERIFY(m.available());
    }
    void explicitActionsUseArgvAndSuppressDuplicates() {
        QTemporaryDir temp;
        QString binary = temp.path() + "/fake backend";
        QFile script(binary); QVERIFY(script.open(QIODevice::WriteOnly));
        script.write(R"(#!/bin/sh
if [ "$2" = computers ]; then
  printf '%s\n' '[{"computer":"test","profiles":["desktop"]}]'
else
  printf '%s\n' "$@" > "${0}.args"
  sleep 0.1
  printf '%s\n' '{}'
fi
)");
        script.close(); script.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner);
        Manager m(binary, temp.path() + "/missing.socket");
        QTRY_VERIFY(!m.loading());
        m.act("test", "connect", "desktop");
        QVERIFY(m.computers()[0].toMap()["busy"].toBool());
        m.act("test", "disconnect");
        QTRY_VERIFY(!m.computers()[0].toMap()["busy"].toBool());
        QFile args(binary + ".args"); QVERIFY(args.open(QIODevice::ReadOnly));
        QCOMPARE(args.readAll(), QByteArray("--json\nconnect\ntest\n--profile\ndesktop\n"));
        QVERIFY(m.notice().isEmpty()); // Accepted commands show through status, not a banner.
        QVERIFY(!m.noticeError());
    }
    void setupUsesBoundedStdinAndReportsFailures() {
        QTemporaryDir temp;
        QString binary = temp.path() + "/fake backend";
        QFile script(binary); QVERIFY(script.open(QIODevice::WriteOnly));
        script.write(R"(#!/bin/sh
if [ "$2" = computers ]; then
  printf '%s\n' '[]'
else
  printf '%s\n' "$@" > "${0}.args"
  cat > "${0}.input"
  sleep 0.1
  printf '%s\n' 'synthetic connection failure' >&2
  exit 1
fi
)");
        script.close(); script.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner);
        Manager m(binary, temp.path() + "/missing.socket");
        QTRY_VERIFY(!m.loading());
        QSignalSpy replies(&m, &Manager::setupFinished);
        QVariantMap draft{{"name", "Literal $(text) with spaces"}, {"computer", "example"}};
        m.setup("test", draft);
        QVERIFY(m.setupBusy());
        m.setup("save", draft); // One outstanding settings request.
        QTRY_COMPARE(replies.count(), 1);
        QVERIFY(!m.setupBusy());
        QCOMPARE(replies.first()[0].toString(), QString("test"));
        QVERIFY(!replies.first()[1].toBool());
        QVERIFY(replies.first()[3].toString().contains("synthetic connection failure"));
        QFile args(binary + ".args"); QVERIFY(args.open(QIODevice::ReadOnly));
        QCOMPARE(args.readAll(), QByteArray("--json\nsettings\ntest\n"));
        QFile input(binary + ".input"); QVERIFY(input.open(QIODevice::ReadOnly));
        QCOMPARE(QJsonDocument::fromJson(input.readAll()).object().toVariantMap(), draft);
        QVERIFY(m.computers().isEmpty());
    }
    void pairingDiscoveryAndRecoveryFlowsInDemo() {
        Manager m("/must-not-run", "/must-not-connect", true);
        Theme theme("/missing/palette");
        QQmlApplicationEngine engine;
        QSignalSpy warnings(&engine, &QQmlEngine::warnings);
        engine.rootContext()->setContextProperty("manager", &m);
        engine.rootContext()->setContextProperty("theme", &theme);
        engine.load(QUrl("qrc:/qml/Main.qml"));
        auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        auto *dialog = window->findChild<QObject *>("setupDialog");
        QVERIFY(QMetaObject::invokeMethod(dialog, "begin", Q_ARG(QVariant, QVariant(""))));
        QTRY_VERIFY(dialog->property("loaded").toBool());
        QTRY_VERIFY(!dialog->property("discovering").toBool()); // Discovery follows the catalog on its own.
        QCOMPARE(dialog->property("discovered").toList().size(), 3);
        QVariantMap target{{"name", "Garage PC"}, {"host", "garage.tail-example.ts.net"}, {"platform", "windows"}};
        QVERIFY(QMetaObject::invokeMethod(dialog, "startPair", Q_ARG(QVariant, QVariant(target)), Q_ARG(QVariant, QVariant(""))));
        QVERIFY(dialog->property("pairing").toBool());
        QCOMPARE(dialog->property("pin").toString().size(), 4);
        QVERIFY(m.setupBusy());
        QTRY_COMPARE_WITH_TIMEOUT(dialog->property("step").toInt(), 1, 8000); // A successful pairing continues to settings.
        QVERIFY(!dialog->property("pairing").toBool());
        auto draft = dialog->property("draft").toMap();
        QCOMPARE(draft["pairing_uuid"].toString(), QString("22222222-3333-4444-5555-666666666666"));
        QCOMPARE(draft["platform"].toString(), QString("windows"));
        QCOMPARE(draft["display"].toMap()["adapter"].toString(), QString("sunshine"));
        // Default matching needs no SSH; verified matching below requires inspection.
        QCOMPARE(draft["stream_resolution"].toString(), QString("1920x1080"));
        QVERIFY(QMetaObject::invokeMethod(dialog, "setAdapter", Q_ARG(QVariant, QVariant("virtual"))));
        QVERIFY(dialog->property("sshAliasError").toString().isEmpty());
        QVERIFY(!dialog->property("displayError").toString().isEmpty());
        QVERIFY(QMetaObject::invokeMethod(dialog, "setNested", Q_ARG(QVariant, QVariant("ssh")), Q_ARG(QVariant, QVariant("alias")), Q_ARG(QVariant, QVariant("bad alias"))));
        QVERIFY(!dialog->property("sshAliasError").toString().isEmpty());
        QVERIFY(QMetaObject::invokeMethod(dialog, "setNested", Q_ARG(QVariant, QVariant("ssh")), Q_ARG(QVariant, QVariant("alias")), Q_ARG(QVariant, QVariant(""))));
        QVariant recovery;
        QVERIFY(QMetaObject::invokeMethod(dialog, "recoverySummary", Q_RETURN_ARG(QVariant, recovery)));
        QVERIFY(recovery.toString().contains("verified after connecting"));
        QVERIFY(QMetaObject::invokeMethod(dialog, "setNested", Q_ARG(QVariant, QVariant("ssh")), Q_ARG(QVariant, QVariant("alias")), Q_ARG(QVariant, QVariant("fake-pc"))));
        QVERIFY(QMetaObject::invokeMethod(dialog, "inspectHost"));
        QTRY_VERIFY_WITH_TIMEOUT(!m.setupBusy(), 4000);
        QVERIFY(!dialog->property("draft").toMap()["display"].toMap()["output"].toString().isEmpty());
        QVERIFY(dialog->property("displayError").toString().isEmpty());
        // Managed Windows recovery: alias, inspection, capture display, helper install.
        QVERIFY(QMetaObject::invokeMethod(dialog, "setAdapter", Q_ARG(QVariant, QVariant("windows"))));
        auto *next = dialog->findChild<QObject *>("setupNext");
        QVERIFY(QMetaObject::invokeMethod(next, "clicked"));
        QCOMPARE(dialog->property("step").toInt(), 1); // Alias and capture display are required first.
        QVERIFY(dialog->property("attempted").toBool());
        QVERIFY(QMetaObject::invokeMethod(dialog, "setNested", Q_ARG(QVariant, QVariant("ssh")), Q_ARG(QVariant, QVariant("alias")), Q_ARG(QVariant, QVariant("garage"))));
        QVERIFY(QMetaObject::invokeMethod(dialog, "inspectHost"));
        QTRY_VERIFY(dialog->property("inspection").toMap().contains("displays"));
        QVERIFY(!dialog->property("inspection").toMap()["helper"].toMap()["installed"].toBool());
        const auto device = dialog->property("inspection").toMap()["displays"].toList().first().toMap()["id"].toString();
        QVERIFY(QMetaObject::invokeMethod(dialog, "setNested", Q_ARG(QVariant, QVariant("display")), Q_ARG(QVariant, QVariant("device_id")), Q_ARG(QVariant, QVariant(device))));
        QVERIFY(QMetaObject::invokeMethod(dialog, "installHelper"));
        QTRY_VERIFY(dialog->property("inspection").toMap()["helper"].toMap()["installed"].toBool());
        QVERIFY(dialog->property("valid").toBool());
        QVERIFY(QMetaObject::invokeMethod(next, "clicked"));
        QCOMPARE(dialog->property("step").toInt(), 2);
        QTRY_VERIFY(dialog->property("tested").toBool());
        QVERIFY(QMetaObject::invokeMethod(next, "clicked"));
        QTRY_VERIFY(!dialog->property("visible").toBool());
        QCOMPARE(m.computers().size(), 4);
        // A wrong PIN is reported on the pairing page and offers a retry.
        QVERIFY(QMetaObject::invokeMethod(dialog, "begin", Q_ARG(QVariant, QVariant(""))));
        QTRY_VERIFY(dialog->property("loaded").toBool());
        QTRY_VERIFY(!dialog->property("discovering").toBool());
        QVERIFY(QMetaObject::invokeMethod(dialog, "startPair", Q_ARG(QVariant, QVariant(target)), Q_ARG(QVariant, QVariant("0000")))); // The demo rejects 0000.
        QTRY_VERIFY_WITH_TIMEOUT(!m.setupBusy(), 8000);
        QVERIFY(dialog->property("pairing").toBool());
        QVERIFY(dialog->property("error").toString().contains("incorrect PIN"));
        QCOMPARE(dialog->property("errorAction").toString(), QString("pair"));
        QCOMPARE(warnings.count(), 0);
        window->close();
    }
    void sharedHostSetup_data() {
        QTest::addColumn<QString>("platform");
        QTest::addColumn<QString>("adapter");
        QTest::addColumn<bool>("editing");
        for (const auto &adapter : {QString("macos"), QString("betterdisplay"), QString("windows"), QString("virtual")}) {
            const QString platform = adapter == "macos" || adapter == "betterdisplay" ? "macos" : "windows";
            for (bool editing : {false, true})
                QTest::newRow(qPrintable(adapter + (editing ? "-edit" : "-add"))) << platform << adapter << editing;
        }
    }
    void sharedHostSetup() {
        QFETCH(QString, platform);
        QFETCH(QString, adapter);
        QFETCH(bool, editing);
        Manager m("/missing", "/missing", true);
        Theme theme("/missing/palette");
        QQmlApplicationEngine engine;
        QSignalSpy warnings(&engine, &QQmlEngine::warnings);
        engine.rootContext()->setContextProperty("manager", &m);
        engine.rootContext()->setContextProperty("theme", &theme);
        engine.load(QUrl("qrc:/qml/Main.qml"));
        QVERIFY(!engine.rootObjects().isEmpty());
        auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        auto *dialog = window->findChild<QObject *>("setupDialog");
        const QString computer = platform == "macos" ? "studio" : "work";
        QVERIFY(QMetaObject::invokeMethod(dialog, "begin", Q_ARG(QVariant, QVariant(editing ? computer : ""))));
        QTRY_VERIFY(dialog->property("loaded").toBool());
        QTRY_VERIFY(!m.setupBusy());
        if (!editing) {
            QVariantMap host{{"name", "Test host"}, {"host", "host.example.net"}, {"pairing_uuid", "11111111-2222-3333-4444-555555555555"}};
            QVERIFY(QMetaObject::invokeMethod(dialog, "choose", Q_ARG(QVariant, QVariant(host)), Q_ARG(QVariant, QVariant(platform))));
        }
        QVERIFY(QMetaObject::invokeMethod(dialog, "setAdapter", Q_ARG(QVariant, QVariant(adapter))));
        const auto buttons = dialog->findChildren<QObject *>("setupInspect");
        QCOMPARE(buttons.size(), 1); // Both platforms use the same action, including main-display following.
        auto *inspect = buttons.first();
        QVERIFY(inspect->property("visible").toBool());
        QVERIFY(!inspect->property("enabled").toBool());
        QCOMPARE(inspect->property("text").toString(), QString("Inspect host"));
        QCOMPARE(dialog->findChild<QObject *>("setupSshUser")->property("visible").toBool(), platform == "macos");
        QCOMPARE(dialog->findChild<QObject *>("setupSshAlias")->property("visible").toBool(), platform == "windows");
        QVERIFY(QMetaObject::invokeMethod(dialog, "setNested", Q_ARG(QVariant, QVariant("ssh")), Q_ARG(QVariant, QVariant(platform == "macos" ? "user" : "alias")), Q_ARG(QVariant, QVariant("test-host"))));
        QVERIFY(inspect->property("enabled").toBool());
        QVERIFY(QMetaObject::invokeMethod(inspect, "clicked"));
        QTRY_VERIFY(!dialog->property("inspection").toMap().isEmpty());
        QCOMPARE(inspect->property("text").toString(), QString("Inspect again"));
        QVERIFY(dialog->property("valid").toBool());
        if (adapter == "macos") {
            QVERIFY(dialog->property("resolutions").toStringList().contains("5120x2880"));
            QVERIFY(!dialog->property("draft").toMap()["display"].toMap().contains("mode"));
        }
        dialog->setProperty("advanced", true);
        QCOMPARE(dialog->findChild<QObject *>("setupFitWindow")->property("visible").toBool(), adapter == "virtual");
        QVERIFY(dialog->findChild<QObject *>("setupResolution")->property("visible").toBool());
        // Changing identity revokes the inventory and restores the common inspection action.
        QVERIFY(QMetaObject::invokeMethod(dialog, "set", Q_ARG(QVariant, QVariant("host")), Q_ARG(QVariant, QVariant("other.example.net"))));
        QVERIFY(dialog->property("inspection").toMap().isEmpty());
        QCOMPARE(inspect->property("text").toString(), QString("Inspect host"));
        QTest::qWait(100); // Exercise the deferred inspection scroll for each adapter.
        QCOMPARE(warnings.count(), 0);
        window->close();
    }
    void resolutionIsPickedFromTheHostOrTyped() {
        Manager m("/missing", "/missing", true);
        Theme theme("/missing/palette");
        QQmlApplicationEngine engine;
        QSignalSpy warnings(&engine, &QQmlEngine::warnings);
        engine.rootContext()->setContextProperty("manager", &m);
        engine.rootContext()->setContextProperty("theme", &theme);
        engine.load(QUrl("qrc:/qml/Main.qml"));
        auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        window->show();
        window->requestActivate();
        QVERIFY(QTest::qWaitForWindowActive(window));
        auto *dialog = window->findChild<QObject *>("setupDialog");
        QVERIFY(QMetaObject::invokeMethod(dialog, "begin", Q_ARG(QVariant, QVariant(""))));
        QTRY_VERIFY(dialog->property("loaded").toBool());
        QTRY_VERIFY(!dialog->property("discovering").toBool());
        QVariantMap host{{"name", "Studio"}, {"host", "studio.example.net"}, {"pairing_uuid", "11111111-2222-3333-4444-555555555555"}};
        QVERIFY(QMetaObject::invokeMethod(dialog, "choose", Q_ARG(QVariant, QVariant(host)), Q_ARG(QVariant, QVariant("macos"))));
        dialog->setProperty("advanced", true);
        auto *field = dialog->findChild<QQuickItem *>("setupResolution");
        QVERIFY(field);
        QVERIFY(field->property("editable").toBool());
        QCOMPARE(field->property("editText").toString(), QString("1920x1080")); // The balanced preset.
        QCOMPARE(field->property("currentIndex").toInt(), 0);
        // Picking a suggestion updates the draft and the quality preset.
        field->setProperty("currentIndex", 1);
        QVERIFY(QMetaObject::invokeMethod(field, "activated", Q_ARG(int, 1)));
        QCOMPARE(dialog->property("draft").toMap()["stream_resolution"].toString(), QString("2560x1440"));
        QCOMPARE(dialog->property("presetIndex").toInt(), 3); // Bitrate no longer matches a preset: custom.
        // Typing any WIDTHxHEIGHT is accepted; the validator blocks other characters.
        field->forceActiveFocus();
        QTRY_VERIFY(field->property("contentItem").value<QQuickItem *>()->hasActiveFocus());
        const auto type = [window](const QString &text) { for (const QChar c : text) QTest::keyClick(window, c.toLatin1()); };
        QTest::keyClick(window, Qt::Key_A, Qt::ControlModifier);
        type("3000x2000abc");
        QCOMPARE(field->property("editText").toString(), QString("3000x2000"));
        QCOMPARE(dialog->property("draft").toMap()["stream_resolution"].toString(), QString("3000x2000"));
        QVERIFY(dialog->property("resolutionError").toString().isEmpty());
        QTest::keyClick(window, Qt::Key_A, Qt::ControlModifier);
        type("3000x");
        QVERIFY(!dialog->property("resolutionError").toString().isEmpty());
        QVERIFY(field->property("invalid").toBool());
        type("1500");
        QVERIFY(!field->property("invalid").toBool());
        // Leaving the field keeps the typed value and marks it as not in the list.
        dialog->findChild<QQuickItem *>("setupNext")->forceActiveFocus();
        QTRY_VERIFY(!field->hasActiveFocus());
        QCOMPARE(field->property("editText").toString(), QString("3000x1500"));
        QCOMPARE(dialog->property("draft").toMap()["stream_resolution"].toString(), QString("3000x1500"));
        QCOMPARE(field->property("currentIndex").toInt(), -1);
        // A preset chosen elsewhere is reflected back into the field.
        QVERIFY(QMetaObject::invokeMethod(dialog, "set", Q_ARG(QVariant, QVariant("stream_resolution")), Q_ARG(QVariant, QVariant("3840x2160"))));
        QCOMPARE(field->property("editText").toString(), QString("3840x2160"));
        QCOMPARE(field->property("currentIndex").toInt(), 3);
        // Fullscreen and native monitor size are shared connection settings.
        auto *fullscreen = dialog->findChild<QObject *>("setupFullscreen");
        auto *monitor = dialog->findChild<QObject *>("setupMatchMonitor");
        QVERIFY(fullscreen);
        QVERIFY(monitor);
        fullscreen->setProperty("checked", true);
        QVERIFY(QMetaObject::invokeMethod(fullscreen, "toggled"));
        monitor->setProperty("checked", true);
        QVERIFY(QMetaObject::invokeMethod(monitor, "toggled"));
        QCOMPARE(dialog->property("draft").toMap()["display_mode"].toString(), QString("fullscreen"));
        QCOMPARE(dialog->property("draft").toMap()["stream_resolution"].toString(), QString("monitor"));
        QVERIFY(!field->property("enabled").toBool());
        monitor->setProperty("checked", false);
        QVERIFY(QMetaObject::invokeMethod(monitor, "toggled"));
        QCOMPARE(dialog->property("draft").toMap()["stream_resolution"].toString(), QString("3840x2160"));
        // An inspected Mac display offers its modes first, with HiDPI modes doubled to their pixel size.
        QVERIFY(QMetaObject::invokeMethod(dialog, "setAdapter", Q_ARG(QVariant, QVariant("betterdisplay"))));
        QVERIFY(QMetaObject::invokeMethod(dialog, "setNested", Q_ARG(QVariant, QVariant("ssh")), Q_ARG(QVariant, QVariant("user")), Q_ARG(QVariant, QVariant("streamer"))));
        QVERIFY(QMetaObject::invokeMethod(dialog, "inspectHost"));
        QTRY_VERIFY(dialog->property("inspection").toMap().contains("displays"));
        const auto offered = dialog->property("resolutions").toStringList();
        QCOMPARE(offered.mid(0, 3), QStringList({"5120x2880", "2560x1440", "3840x2160"}));
        QVERIFY(offered.contains("1920x1080"));
        QCOMPARE(offered.count("2560x1440"), 1);
        QCOMPARE(field->property("editText").toString(), QString("3840x2160"));
        QCOMPARE(field->property("currentIndex").toInt(), 2);
        // Existing-display and fixed-mode adapters cannot promise host refitting.
        auto *fit = dialog->findChild<QObject *>("setupFitWindow");
        QVERIFY(fit);
        QVERIFY(!fit->property("enabled").toBool());
        QVERIFY(QMetaObject::invokeMethod(dialog, "setAdapter", Q_ARG(QVariant, QVariant("virtual"))));
        QVERIFY(QMetaObject::invokeMethod(dialog, "setNested", Q_ARG(QVariant, QVariant("ssh")), Q_ARG(QVariant, QVariant("alias")), Q_ARG(QVariant, QVariant("test-pc"))));
        QVERIFY(QMetaObject::invokeMethod(dialog, "setNested", Q_ARG(QVariant, QVariant("display")), Q_ARG(QVariant, QVariant("output")), Q_ARG(QVariant, QVariant("{11111111-2222-3333-4444-555555555555}"))));
        QVERIFY(fit->property("enabled").toBool());
        fit->setProperty("checked", true);
        QVERIFY(QMetaObject::invokeMethod(fit, "toggled"));
        QCOMPARE(dialog->property("draft").toMap()["stream_resolution"].toString(), QString("auto"));
        QVERIFY(!field->property("enabled").toBool());
        QVariant summary;
        QVERIFY(QMetaObject::invokeMethod(dialog, "summary", Q_RETURN_ARG(QVariant, summary)));
        QVERIFY(summary.toString().startsWith("Saved size with manual Refit"));
        QVERIFY(QMetaObject::invokeMethod(dialog, "setAdapter", Q_ARG(QVariant, QVariant("external"))));
        QCOMPARE(dialog->property("draft").toMap()["stream_resolution"].toString(), QString("3840x2160"));
        QVERIFY(field->property("enabled").toBool());
        QVERIFY(!fit->property("enabled").toBool());
        QVERIFY(warnings.isEmpty());
    }
    void launcherRemovalUsesTheLauncherCommand() {
        QTemporaryDir temp;
        QString binary = temp.path() + "/fake backend";
        QFile script(binary); QVERIFY(script.open(QIODevice::WriteOnly));
        script.write("#!/bin/sh\nif [ \"$2\" = computers ]; then printf '[{\"computer\":\"test\",\"name\":\"Test\",\"profiles\":[\"desktop\"]}]\\n'; else printf '%s\\n' \"$@\" > \"${0}.args\"; printf '{}\\n'; fi\n");
        script.close(); script.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner);
        Manager m(binary, temp.path() + "/missing.socket");
        QTRY_VERIFY(!m.loading());
        QVERIFY(!m.computers()[0].toMap()["launcher_installed"].toBool());
        m.act("test", "launcher-remove");
        QTRY_VERIFY(m.notice().contains("removed from your app launcher"));
        QFile args(binary + ".args"); QVERIFY(args.open(QIODevice::ReadOnly));
        QCOMPARE(args.readAll(), QByteArray("--json\nlauncher\nremove\ntest\n"));
    }
    void removeUsesSettingsCommandAndForgetsLocally() {
        QTemporaryDir temp;
        QString binary = temp.path() + "/fake backend";
        QFile script(binary); QVERIFY(script.open(QIODevice::WriteOnly));
        script.write(R"(#!/bin/sh
if [ "$2" = computers ]; then
  printf '%s\n' '[{"computer":"test","name":"Test","profiles":["desktop"]}]'
else
  printf '%s\n' "$@" > "${0}.args"
  printf '%s\n' '{"removed":true}'
fi
)");
        script.close(); script.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner);
        Manager m(binary, temp.path() + "/missing.socket");
        QTRY_VERIFY(!m.loading());
        QCOMPARE(m.computers().size(), 1);
        m.remove("test");
        QVERIFY(m.computers()[0].toMap()["busy"].toBool());
        QTRY_VERIFY(m.notice().contains("Test was removed"));
        QVERIFY(!m.noticeError());
        QFile args(binary + ".args"); QVERIFY(args.open(QIODevice::ReadOnly));
        QCOMPARE(args.readAll(), QByteArray("--json\nsettings\nremove\ntest\n"));
    }
    void failedCommandsBecomeErrorNotices() {
        QTemporaryDir temp;
        QString binary = temp.path() + "/fake backend";
        QFile script(binary); QVERIFY(script.open(QIODevice::WriteOnly));
        script.write("#!/bin/sh\nif [ \"$2\" = computers ]; then printf '[]\\n'; else printf 'remote-desktops: Disconnect this computer before removing it.\\n' >&2; exit 1; fi\n");
        script.close(); script.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner);
        Manager m(binary, temp.path() + "/missing.socket");
        QTRY_VERIFY(!m.loading());
        m.startService();
        QVERIFY(m.serviceBusy());
        QTRY_VERIFY(!m.serviceBusy());
        QVERIFY(m.noticeError());
        QCOMPARE(m.notice(), QString("Disconnect this computer before removing it."));
        m.clearNotice();
        QVERIFY(m.notice().isEmpty()); QVERIFY(!m.noticeError());
    }
    void demoRemoveAndServiceNeverTouchBackend() {
        Manager m("/does/not/exist", "/does/not/exist", true);
        m.demoState("unavailable");
        QVERIFY(!m.available());
        m.startService();
        QVERIFY(m.available());
        m.remove("work");
        QTRY_COMPARE(m.computers().size(), 2);
        QVERIFY(m.notice().contains("Work laptop"));
        m.demoState("many");
        QCOMPARE(m.computers().size(), 11);
        m.demoState("unconfigured");
        QVERIFY(m.computers().last().toMap()["unconfigured"].toBool());
    }
    void paletteReadsModeAndKeepsEveryForegroundReadable() {
        auto luminance = [](const QColor &c) {
            auto linear = [](double v) { return v <= .04045 ? v / 12.92 : std::pow((v + .055) / 1.055, 2.4); };
            return .2126 * linear(c.redF()) + .7152 * linear(c.greenF()) + .0722 * linear(c.blueF());
        };
        auto contrast = [&](const QColor &a, const QColor &b) {
            double x = luminance(a), y = luminance(b);
            return (std::max(x, y) + .05) / (std::min(x, y) + .05);
        };
        for (const auto &mode : {QString("light"), QString("dark")}) {
            const bool light = mode == "light";
            auto colors = Theme::palette({{"background", QColor(light ? "#f5f1e8" : "#060b1e")}, {"foreground", QColor(light ? "#303640" : "#ffcead")},
                                          {"accent", QColor(light ? "#365ca8" : "#7d82d9")}, {"yellow", QColor(light ? "#926b16" : "#e9bb4f")}}, mode);
            QCOMPARE(colors["mode"].toString(), mode);
            for (const auto &ground : {"bg", "sidebar", "surface", "selected", "hover", "cardStart", "warningBg", "successBg"})
                for (const auto &ink : {"text", "secondary", "muted"})
                    QVERIFY2(contrast(colors[ink].value<QColor>(), colors[ground].value<QColor>()) >= 4.5, qPrintable(QString("%1 on %2 (%3)").arg(ink, ground, mode)));
            QVERIFY(contrast(colors["disabledText"].value<QColor>(), colors["disabled"].value<QColor>()) >= 4.5);
            QVERIFY(contrast(colors["warning"].value<QColor>(), colors["warningBg"].value<QColor>()) >= 4.5);
            QVERIFY(contrast(colors["success"].value<QColor>(), colors["bg"].value<QColor>()) >= 4.5);
            QVERIFY(contrast(colors["danger"].value<QColor>(), colors["surface"].value<QColor>()) >= 4.5);
        }
        // A palette declaring light mode stays light even with a dark-looking background key order.
        QCOMPARE(Theme::palette({{"background", QColor("#ffffff")}, {"foreground", QColor("#222222")}, {"accent", QColor("#385ac3")}})["mode"].toString(), QString("light"));
        auto type = Theme::scale(11);
        QVERIFY(type["caption"].toDouble() >= 9);
        QVERIFY(type["body"].toDouble() > type["caption"].toDouble());
        QVERIFY(type["title"].toDouble() > type["subtitle"].toDouble());
        QVERIFY(Theme::scale(0)["body"].toDouble() >= 10); // Unknown system font still yields a usable scale.
    }
    void missingBackendIsActionable() {
        Manager m("/missing/backend", "/missing/socket");
        QTRY_VERIFY(!m.loading());
        QVERIFY(m.error().contains("could not start"));
        QVERIFY(!m.available());
    }
};
QTEST_MAIN(ManagerTests)
#include "manager.moc"
