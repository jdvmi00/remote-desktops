#include "Theme.h"
#include <QColor>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QRegularExpression>
#include <cmath>

namespace {
QColor mix(const QColor &a, const QColor &b, double weight) {
    return QColor::fromRgbF(a.redF()*(1-weight)+b.redF()*weight,
                           a.greenF()*(1-weight)+b.greenF()*weight,
                           a.blueF()*(1-weight)+b.blueF()*weight);
}
double luminance(const QColor &c) {
    auto linear = [](double v) { return v <= .04045 ? v/12.92 : std::pow((v+.055)/1.055, 2.4); };
    return .2126*linear(c.redF()) + .7152*linear(c.greenF()) + .0722*linear(c.blueF());
}
double contrast(const QColor &a, const QColor &b) {
    double x = luminance(a), y = luminance(b);
    return (std::max(x,y)+.05)/(std::min(x,y)+.05);
}
QColor readable(QColor text, const QColor &background) {
    const QColor target = contrast(Qt::black, background) > contrast(Qt::white, background) ? Qt::black : Qt::white;
    for (int i=0; i<100 && contrast(text, background)<4.5; ++i) text = mix(text, target, .05);
    return text;
}
}
QVariantMap Theme::palette(const QMap<QString, QColor> &source) {
    auto value = [&](const QString &key, QColor fallback) { return source.value(key, fallback); };
    QColor bg = value("background", QColor("#141c20"));
    QColor text = readable(value("foreground", QColor("#f0f2ed")), bg);
    QColor accent = value("accent", QColor("#afe6c5"));
    QColor surface = value("lighter_background", mix(bg, text, .06));
    QColor sidebar = value("dark_background", mix(bg, Qt::black, .15));
    QColor warningBg = mix(bg, value("yellow", QColor("#e9bd83")), .12);
    QColor selected = mix(bg, accent, .14);
    QColor secondary = readable(mix(bg, text, .74), bg);
    QColor border = mix(bg, text, .24);
    // Shared foreground must remain readable on every ordinary surface.
    for (const auto &background : {surface, sidebar, selected}) text = readable(text, background);
    QVariantMap result;
    auto put = [&](const char *key, QColor color) { result[key] = color; };
    put("bg", bg); put("sidebar", sidebar); put("surface", surface);
    put("text", text); put("secondary", secondary); put("muted", readable(mix(bg,text,.58), bg));
    put("border", border); put("hover", mix(surface,text,.06));
    put("accent", accent); put("onAccent", readable(bg,accent));
    put("accentHover", mix(accent, text,.15)); put("accentPressed", mix(accent,bg,.12));
    put("selected", selected); put("selectedBorder", mix(bg,accent,.45));
    put("accentText", readable(accent,selected));
    put("warningBg", warningBg); put("warning", readable(value("yellow",QColor("#e9bd83")),warningBg));
    put("warningBorder", mix(bg,value("yellow",QColor("#e9bd83")),.45));
    put("danger", readable(value("red",QColor("#f2b2a7")),surface));
    put("success", readable(value("green",accent),sidebar));
    put("heroStart", mix(bg,accent,.12)); put("heroEnd", mix(bg,accent,.025));
    put("screen", mix(bg,accent,.08)); put("tile1", mix(bg,accent,.21));
    put("tile2", mix(bg,accent,.38)); put("tile3", mix(bg,accent,.28));
    put("disabled", mix(bg,text,.06)); put("disabledText", mix(bg,text,.48));
    return result;
}
QString Theme::currentPath() {
    auto state = qEnvironmentVariable("XDG_STATE_HOME");
    if (state.isEmpty()) state = QDir::homePath() + "/.local/state";
    return state + "/omarchy/current/theme/colors.toml";
}
Theme::Theme(QString path, QObject *parent) : QObject(parent), m_path(std::move(path)), m_colors(palette({})) {
    m_debounce.setSingleShot(true); m_debounce.setInterval(100);
    connect(&m_watcher, &QFileSystemWatcher::fileChanged, this, [this] { m_debounce.start(); });
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged, this, [this] { m_debounce.start(); });
    connect(&m_debounce, &QTimer::timeout, this, &Theme::reload);
    reload();
}
void Theme::watch() {
    QStringList wanted;
    if (QFileInfo::exists(m_path)) wanted << m_path;
    // Parent watches survive both file replacement and Omarchy's remove/move
    // of the entire theme directory. A missing install watches its nearest parent.
    QDir dir(QFileInfo(m_path).absolutePath());
    int existing = 0;
    while (true) {
        if (dir.exists()) { wanted << dir.absolutePath(); if (++existing == 3) break; }
        const auto parent = QFileInfo(dir.absolutePath()).absolutePath();
        if (parent == dir.absolutePath()) break;
        dir = QDir(parent);
    }
    const auto old = m_watcher.files() + m_watcher.directories();
    if (!old.isEmpty()) m_watcher.removePaths(old);
    if (!wanted.isEmpty()) m_watcher.addPaths(wanted);
}
void Theme::reload() {
    watch();
    QFile file(m_path);
    if (!file.open(QIODevice::ReadOnly) || file.size() > 65536) return;
    const QString text = QString::fromUtf8(file.readAll());
    QMap<QString,QColor> source;
    // Only the flat hex-color assignments in Omarchy's colors.toml contract
    // are interpreted. No shell, external parser, or theme code is executed.
    static const QRegularExpression line(R"(^\s*([a-z_]+)\s*=\s*["'](#[0-9a-fA-F]{6})["']\s*(?:#.*)?$)");
    for (const auto &part : text.split('\n')) {
        auto match = line.match(part);
        if (match.hasMatch()) source[match.captured(1)] = QColor(match.captured(2));
    }
    // Keep the last complete palette through a theme replacement or partial write.
    if (!source.contains("background") || !source.contains("foreground") || !source.contains("accent")) return;
    auto next = palette(source);
    if (next != m_colors) { m_colors = next; emit changed(); }
}
