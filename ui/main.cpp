#include "Manager.h"
#include "Theme.h"
#include <QCommandLineParser>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QQuickStyle>
#include <QSettings>
#include <QStandardPaths>
#include <QFileInfo>
#include <QDir>

int main(int argc, char **argv) {
    QGuiApplication app(argc, argv);
    app.setApplicationName("Remote Desktops");
    app.setOrganizationName("Remote Desktops");
    app.setDesktopFileName("remote-desktops-manager");
    QQuickStyle::setStyle("Basic");
    QCommandLineParser parser;
    parser.addHelpOption();
    parser.addOption({"theme-file", "Read a palette from this file (preview/testing).", "path"});
    parser.addOption({"demo", "Use synthetic computers; never access a real backend."});
    parser.addOption({"backend", "Absolute path to the Rust CLI.", "path"});
    parser.addOption({"smoke-test", "Render the demo and exit with failure on QML warnings."});
    parser.addOption({"screenshot", "Save an isolated demo rendering and exit.", "path"});
    parser.addOption({"setup-preview", "Show guided setup (computer, pair, preferences, recovery, windows, advanced, check).", "page"});
    parser.addOption({"compact", "Render the preview at the minimum supported size."});
    parser.addOption({"dialog", "Open a preview surface (help, details, remove, notice, error).", "name"});
    parser.addOption({"state", "Initial demo state (idle, connecting, preflight, running, attention, restore-pending, empty, unavailable, many, unconfigured).", "phase"});
    parser.process(app);
    const bool demo = parser.isSet("demo");
    if ((parser.isSet("smoke-test") || parser.isSet("screenshot") || parser.isSet("state") || parser.isSet("compact") || parser.isSet("setup-preview") || parser.isSet("dialog")) && !demo) return 2;
    QString backend = parser.value("backend");
    if (backend.isEmpty()) {
        backend = QCoreApplication::applicationDirPath() + "/remote-desktops";
        if (!QFileInfo::exists(backend)) {
            const auto installed = QStandardPaths::findExecutable("remote-desktops");
            if (!installed.isEmpty()) backend = installed;
        }
    }
    if (!demo && (backend.isEmpty() || !QFileInfo(backend).isAbsolute())) {
        qCritical("Pass --backend with the absolute path to the Rust remote-desktops executable.");
        return 2;
    }
    Manager manager(backend, qEnvironmentVariable("XDG_RUNTIME_DIR") + "/remote-desktops/control.sock", demo);
    if (parser.isSet("state")) manager.demoState(parser.value("state"));
    Theme theme(parser.isSet("theme-file") ? parser.value("theme-file") : Theme::currentPath());
    QQmlApplicationEngine engine;
    bool warnings = false;
    QObject::connect(&engine, &QQmlEngine::warnings, &app, [&warnings](const QList<QQmlError> &errors) { warnings = true; for (const auto &error : errors) fprintf(stderr, "%s\n", qPrintable(error.toString())); });
    engine.rootContext()->setContextProperty("manager", &manager);
    engine.rootContext()->setContextProperty("theme", &theme);
    engine.load(QUrl("qrc:/qml/Main.qml"));
    if (engine.rootObjects().isEmpty()) return 1;
    auto *window = engine.rootObjects().first();
    // Window size and the last selected computer persist between launches.
    // The preview never writes user settings.
    QSettings settings;
    if (!demo) {
        if (settings.contains("window/width") && settings.contains("window/height")) {
            window->setProperty("width", qMax(settings.value("window/width").toInt(), window->property("minimumWidth").toInt()));
            window->setProperty("height", qMax(settings.value("window/height").toInt(), window->property("minimumHeight").toInt()));
        }
        window->setProperty("selectedId", settings.value("window/selected").toString());
        QObject::connect(&app, &QCoreApplication::aboutToQuit, &app, [&settings, window] {
            settings.setValue("window/width", window->property("width"));
            settings.setValue("window/height", window->property("height"));
            settings.setValue("window/selected", window->property("selectedId"));
        });
    }
    if (parser.isSet("setup-preview")) {
        auto *setup = window->findChild<QObject *>("setupDialog");
        QMetaObject::invokeMethod(setup, "begin", Q_ARG(QVariant, QVariant("")));
        const auto page = parser.value("setup-preview");
        // The demo catalog and discovery take about 600 ms; act once they are done.
        if (page != "computer") QTimer::singleShot(900, setup, [setup, page] {
            if (page == "pair") {
                QVariantMap target{{"name", "Garage PC"}, {"host", "garage.tail-example.ts.net"}, {"platform", "windows"}};
                QMetaObject::invokeMethod(setup, "startPair", Q_ARG(QVariant, QVariant(target)), Q_ARG(QVariant, QVariant("")));
                return;
            }
            QVariantMap host{{"name", "Home workstation"}, {"host", "home.example.net"}, {"pairing_uuid", "11111111-2222-3333-4444-555555555555"}};
            const QString platform = page == "recovery" ? "macos" : (page == "windows" || page == "matching") ? "windows" : "unknown";
            QMetaObject::invokeMethod(setup, "choose", Q_ARG(QVariant, QVariant(host)), Q_ARG(QVariant, QVariant(platform)));
            if (page == "recovery" || page == "windows" || page == "matching") {
                QMetaObject::invokeMethod(setup, "setAdapter", Q_ARG(QVariant, QVariant(page == "recovery" ? "betterdisplay" : page == "matching" ? "virtual" : "windows")));
                QMetaObject::invokeMethod(setup, "setNested", Q_ARG(QVariant, QVariant("ssh")), Q_ARG(QVariant, QVariant(page == "recovery" ? "user" : "alias")), Q_ARG(QVariant, QVariant(page == "recovery" ? "streamer" : "garage")));
                QMetaObject::invokeMethod(setup, "inspectHost");
            }
            if (page == "advanced") setup->setProperty("advanced", true);
            if (page == "check") QMetaObject::invokeMethod(setup, "advance");
        });
    }
    if (parser.isSet("compact")) { window->setProperty("width", 880); window->setProperty("height", 600); }
    if (parser.isSet("dialog")) QTimer::singleShot(300, window, [window, name = parser.value("dialog")] { QMetaObject::invokeMethod(window, "preview", Q_ARG(QVariant, QVariant(name))); });
    if (parser.isSet("smoke-test") || parser.isSet("screenshot")) {
        QTimer::singleShot(2600, &app, [&] {
            if (parser.isSet("screenshot")) {
                auto *quick = qobject_cast<QQuickWindow *>(window);
                if (!quick || !quick->grabWindow().save(parser.value("screenshot"))) warnings = true;
            }
            app.exit(warnings ? 1 : 0);
        });
    }
    return app.exec();
}
