#include "Manager.h"
#include "Theme.h"
#include <QCommandLineParser>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QQuickStyle>
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
    parser.addOption({"setup-preview", "Show guided setup (computer, preferences, advanced, check).", "page"});
    parser.addOption({"compact", "Render the preview at the minimum supported size."});
    parser.addOption({"state", "Initial demo state (restore-pending, preflight, idle, empty, unavailable).", "phase"});
    parser.process(app);
    const bool demo = parser.isSet("demo");
    if ((parser.isSet("smoke-test") || parser.isSet("screenshot") || parser.isSet("state") || parser.isSet("compact") || parser.isSet("setup-preview")) && !demo) return 2;
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
    if (parser.isSet("setup-preview")) {
        auto *setup = engine.rootObjects().first()->findChild<QObject *>("setupDialog");
        QMetaObject::invokeMethod(setup, "begin", Q_ARG(QVariant, QVariant("")));
        const auto page = parser.value("setup-preview");
        if (page != "computer") QTimer::singleShot(350, setup, [setup, page] {
            QVariantMap host{{"name", "Home workstation"}, {"host", "home.example.net"}, {"pairing_uuid", "11111111-2222-3333-4444-555555555555"}};
            QMetaObject::invokeMethod(setup, "choose", Q_ARG(QVariant, QVariant(host)));
            if (page == "advanced") setup->setProperty("advanced", true);
            if (page == "check") { setup->setProperty("step", 2); setup->setProperty("tested", true); }
        });
    }
    if (parser.isSet("compact")) { engine.rootObjects().first()->setProperty("width", 820); engine.rootObjects().first()->setProperty("height", 650); }
    if (parser.isSet("smoke-test") || parser.isSet("screenshot")) {
        QTimer::singleShot(900, &app, [&] {
            if (parser.isSet("screenshot")) {
                auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
                if (!window || !window->grabWindow().save(parser.value("screenshot"))) warnings = true;
            }
            app.exit(warnings ? 1 : 0);
        });
    }
    return app.exec();
}
