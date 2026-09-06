#pragma once
#include <QObject>
#include <QColor>
#include <QVariantMap>
#include <QFileSystemWatcher>
#include <QTimer>

class Theme : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantMap colors READ colors NOTIFY changed)
    Q_PROPERTY(QVariantMap type READ type CONSTANT)
public:
    explicit Theme(QString path, QObject *parent = nullptr);
    QVariantMap colors() const { return m_colors; }
    // Type scale in points, derived from the desktop's application font so
    // text follows the system font size the same way colors follow the theme.
    QVariantMap type() const { return m_type; }
    static QString currentPath();
    static QVariantMap palette(const QMap<QString, QColor> &source, const QString &mode = {});
    static QVariantMap scale(double basePointSize);
signals:
    void changed();
private:
    void reload();
    void watch();
    QString m_path;
    QVariantMap m_colors, m_type;
    QFileSystemWatcher m_watcher;
    QTimer m_debounce;
};
