#pragma once
#include <QObject>
#include <QColor>
#include <QVariantMap>
#include <QFileSystemWatcher>
#include <QTimer>

class Theme : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantMap colors READ colors NOTIFY changed)
public:
    explicit Theme(QString path, QObject *parent = nullptr);
    QVariantMap colors() const { return m_colors; }
    static QString currentPath();
    static QVariantMap palette(const QMap<QString, QColor> &source);
signals:
    void changed();
private:
    void reload();
    void watch();
    QString m_path;
    QVariantMap m_colors;
    QFileSystemWatcher m_watcher;
    QTimer m_debounce;
};
