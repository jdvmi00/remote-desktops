import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Transient message anchored over the content; informational messages fade
// out on their own, errors stay until dismissed or replaced.
Rectangle {
    id: toast
    property string text: ""
    property bool error: false
    property int maxWidth: 520
    signal dismissed()
    visible: opacity > 0
    opacity: text.length ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 160 } }
    radius: 12
    color: error ? theme.colors.dangerBg : theme.colors.surface
    border.color: error ? theme.colors.dangerBorder : theme.colors.borderStrong
    implicitWidth: Math.min(maxWidth, row.implicitWidth + 28)
    implicitHeight: row.implicitHeight + 22
    Accessible.role: Accessible.AlertMessage
    Accessible.name: text
    HoverHandler { id: hover }
    Timer { interval: 5000; running: toast.text.length > 0 && !toast.error && !hover.hovered; onTriggered: toast.dismissed() }
    RowLayout {
        id: row
        anchors.centerIn: parent; width: parent.width - 28; spacing: 10
        Icon { glyph: toast.error ? "alert" : "info"; color: toast.error ? theme.colors.danger : theme.colors.accentText }
        Label { Layout.fillWidth: true; text: toast.text; wrapMode: Text.WordWrap; color: toast.error ? theme.colors.danger : theme.colors.text; font.pointSize: theme.type.body }
        IconButton { name: "close"; hint: "Dismiss"; onClicked: toast.dismissed() }
    }
}
