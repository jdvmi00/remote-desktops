#include "Theme.h"
#include <QColor>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFont>
#include <QGuiApplication>
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
// Nudge a foreground toward black or white until it reads at WCAG AA (4.5:1).
QColor readable(QColor text, const QColor &background) {
    const QColor target = contrast(Qt::black, background) > contrast(Qt::white, background) ? Qt::black : Qt::white;
    for (int i=0; i<100 && contrast(text, background)<4.5; ++i) text = mix(text, target, .05);
    return text;
}
}
QVariantMap Theme::palette(const QMap<QString, QColor> &source, const QString &mode) {
    auto value = [&](const QString &key, QColor fallback) { return source.value(key, fallback); };
    const QColor bg = value("background", QColor("#141c20"));
    // Omarchy declares its mode; a bare palette is classified by luminance.
    const bool light = mode == "light" || (mode.isEmpty() && luminance(bg) > .35);
    const QColor accent = value("accent", QColor("#afe6c5"));
    const QColor yellow = value("yellow", QColor(light ? "#8a6a1a" : "#e9bd83"));
    const QColor red = value("red", QColor(light ? "#a83a3a" : "#f2b2a7"));
    const QColor green = value("green", accent);
    QColor text = readable(value("foreground", QColor(light ? "#2b2f36" : "#f0f2ed")), bg);
    // Optional Omarchy keys refine derived tones; background, foreground and
    // accent alone still produce a complete palette.
    const QColor surface = value("lighter_background", mix(bg, text, light ? .045 : .06));
    const QColor sidebar = value("dark_background", mix(bg, Qt::black, light ? .035 : .15));
    const QColor selected = source.contains("selection") ? mix(bg, value("selection", accent), .6) : mix(bg, accent, .14);
    const QColor hover = mix(surface, text, .06);
    const QColor cardStart = mix(bg, accent, .10), cardEnd = mix(bg, accent, .03);
    const QColor warningBg = mix(bg, yellow, .12), successBg = mix(bg, green, .12), dangerBg = mix(bg, red, .12);
    const QColor disabled = mix(bg, text, .05);
    QColor secondary = mix(bg, text, .74);
    QColor muted = source.contains("muted") ? value("muted", text) : mix(bg, text, .58);
    // Every shared foreground is checked on every surface it can be drawn on.
    const QList<QColor> grounds{bg, sidebar, surface, selected, hover, cardStart, warningBg, successBg, dangerBg};
    auto everywhere = [&](QColor c) { for (const auto &g : grounds) c = readable(c, g); return c; };
    text = everywhere(text); secondary = everywhere(secondary); muted = everywhere(muted);
    QVariantMap result;
    auto put = [&](const char *key, const QVariant &v) { result[key] = v; };
    put("mode", light ? "light" : "dark");
    put("bg", bg); put("sidebar", sidebar); put("surface", surface); put("hover", hover);
    put("text", text); put("secondary", secondary); put("muted", muted);
    put("border", mix(bg, text, light ? .16 : .22)); put("borderStrong", mix(bg, text, light ? .3 : .38));
    put("accent", accent); put("onAccent", readable(bg, accent));
    put("accentHover", mix(accent, text, .15)); put("accentPressed", mix(accent, bg, .12));
    put("accentText", everywhere(readable(accent, selected)));
    put("selected", selected); put("selectedBorder", mix(bg, accent, .45));
    put("warning", everywhere(readable(yellow, warningBg))); put("warningBg", warningBg); put("warningBorder", mix(bg, yellow, .45));
    put("danger", everywhere(readable(red, dangerBg))); put("dangerBg", dangerBg); put("dangerBorder", mix(bg, red, .45));
    put("success", everywhere(readable(green, successBg))); put("successBg", successBg); put("successBorder", mix(bg, green, .45));
    put("cardStart", cardStart); put("cardEnd", cardEnd);
    put("disabled", disabled); put("disabledText", readable(mix(bg, text, .5), disabled));
    put("overlay", QColor(0, 0, 0, light ? 70 : 140));
    put("shadow", QColor(0, 0, 0, light ? 35 : 120));
    const QColor tooltipBg = mix(surface, text, .1);
    put("tooltipBg", tooltipBg); put("tooltipText", readable(text, tooltipBg));
    return result;
}
QVariantMap Theme::scale(double base) {
    if (!(base > 0)) base = 10.5;
    auto half = [](double v) { return std::round(v * 2) / 2; };
    const double body = std::max(10.0, half(base));
    QVariantMap t;
    t["caption"] = std::max(9.0, half(base * .86));
    t["body"] = body;
    t["lead"] = half(body * 1.15);
    t["subtitle"] = half(body * 1.45);
    t["title"] = half(body * 2.1);
    return t;
}
QString Theme::currentPath() {
    auto state = qEnvironmentVariable("XDG_STATE_HOME");
    if (state.isEmpty()) state = QDir::homePath() + "/.local/state";
    return state + "/omarchy/current/theme/colors.toml";
}
Theme::Theme(QString path, QObject *parent) : QObject(parent), m_path(std::move(path)), m_colors(palette({})) {
    const QFont font = QGuiApplication::font();
    double base = font.pointSizeF();
    if (base <= 0 && font.pixelSize() > 0) base = font.pixelSize() * 72.0 / 96.0;
    m_type = scale(base);
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
    QString mode;
    // Only the flat hex-color assignments and the mode key in Omarchy's
    // colors.toml contract are interpreted. No theme code is executed.
    static const QRegularExpression line(R"(^\s*([a-z_]+)\s*=\s*["'](#[0-9a-fA-F]{6})["']\s*(?:#.*)?$)");
    static const QRegularExpression modeLine(R"(^\s*mode\s*=\s*["'](light|dark)["']\s*(?:#.*)?$)");
    for (const auto &part : text.split('\n')) {
        auto match = line.match(part);
        if (match.hasMatch()) source[match.captured(1)] = QColor(match.captured(2));
        auto m = modeLine.match(part);
        if (m.hasMatch()) mode = m.captured(1);
    }
    // Keep the last complete palette through a theme replacement or partial write.
    if (!source.contains("background") || !source.contains("foreground") || !source.contains("accent")) return;
    auto next = palette(source, mode);
    if (next != m_colors) { m_colors = next; emit changed(); }
}
