import QtQuick

// Connection state as a colored dot: filled green when a window is ready,
// pulsing accent while a transition runs, warning when attention is needed,
// hollow when disconnected or unknown. A text label always accompanies it.
Item {
    id: dot
    property string phase: "idle"
    property bool stale: false
    property int size: 10
    readonly property string kind: stale ? "stale"
        : phase === "window-ready" ? "ok"
        : phase === "restore-pending" || phase === "attention" ? "warn"
        : ["preflight", "preparing", "connecting", "reconnecting", "stopping", "restoring", "release-pending", "running"].indexOf(phase) >= 0 ? "busy"
        : "off"
    implicitWidth: size; implicitHeight: size
    Rectangle {
        anchors.fill: parent; radius: width / 2
        color: dot.kind === "ok" ? theme.colors.success : dot.kind === "warn" ? theme.colors.warning : dot.kind === "busy" ? theme.colors.accent : "transparent"
        border.width: dot.kind === "off" || dot.kind === "stale" ? 1.5 : 0
        border.color: theme.colors.muted
        Behavior on color { ColorAnimation { duration: 200 } }
    }
    SequentialAnimation on opacity {
        running: dot.kind === "busy"; loops: Animation.Infinite
        NumberAnimation { to: .35; duration: 700; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
    }
    onKindChanged: if (kind !== "busy") opacity = 1
}
