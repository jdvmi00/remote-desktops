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
        QCOMPARE(primary->property("text").toString(), QString("Open desktop  ↗"));
        auto *list = window->findChild<QQuickItem *>("computerList");
        QVERIFY(list); list->forceActiveFocus();
        QTest::keyClick(window, Qt::Key_Down);
        QCOMPARE(window->property("selectedId").toString(), QString("work"));
        QCOMPARE(primary->property("text").toString(), QString("Connect  ↗"));
        QVERIFY(QMetaObject::invokeMethod(primary, "clicked"));
        QVERIFY(!primary->property("enabled").toBool());
        QTRY_COMPARE(primary->property("text").toString(), QString("Open desktop  ↗"));
        window->setProperty("selectedId", "studio");
        m.demoState("restore-pending");
        QCOMPARE(primary->property("text").toString(), QString("Restore display"));
        QVERIFY(QMetaObject::invokeMethod(primary, "clicked"));
        QTRY_COMPARE(primary->property("text").toString(), QString("Connect  ↗"));
        auto *help = window->findChild<QObject *>("helpDialog");
        QVERIFY(help); QVERIFY(QMetaObject::invokeMethod(help, "open"));
        QTest::keyClick(window, Qt::Key_Escape);
        QTRY_VERIFY(!help->property("visible").toBool());
        QCOMPARE(warnings.count(), 0);
        window->close();
        QCOMPARE(m.computers()[1].toMap()["phase"].toString(), QString("window-ready"));
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
        QVERIFY(m.notice().contains("Request accepted"));
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
