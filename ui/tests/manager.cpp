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
        QVariantMap host{{"name", "Home workstation"}, {"host", "home.example.net"}, {"pairing_uuid", "11111111-2222-3333-4444-555555555555"}};
        QVERIFY(QMetaObject::invokeMethod(dialog, "choose", Q_ARG(QVariant, QVariant(host))));
        auto *next = dialog->findChild<QObject *>("setupNext");
        auto *test = dialog->findChild<QObject *>("setupTest");
        QVERIFY(next && test);
        QVERIFY(next->property("enabled").toBool());
        QVERIFY(QMetaObject::invokeMethod(next, "clicked"));
        QCOMPARE(dialog->property("step").toInt(), 2);
        QVERIFY(!next->property("enabled").toBool());
        QVERIFY(m.setupBusy()); // The check starts on its own when the last step opens.
        QTRY_VERIFY(next->property("enabled").toBool());
        QVERIFY(QMetaObject::invokeMethod(dialog, "set", Q_ARG(QVariant, QVariant("name")), Q_ARG(QVariant, QVariant("My home computer"))));
        QVERIFY(!next->property("enabled").toBool());
        QVERIFY(QMetaObject::invokeMethod(test, "clicked"));
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
