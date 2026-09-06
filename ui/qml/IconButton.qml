import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl

// Icon-only button; the hint doubles as its accessible name.
Button {
    id: control
    property string name: ""
    property string hint: ""
    icon.source: name ? "qrc:/qml/icons/" + name + ".svg" : ""
    icon.width: 18; icon.height: 18
    icon.color: !enabled ? theme.colors.disabledText : hovered ? theme.colors.text : theme.colors.secondary
    implicitWidth: 36; implicitHeight: 36
    hoverEnabled: true
    display: AbstractButton.IconOnly
    Accessible.name: hint
    contentItem: IconLabel { icon: control.icon; display: AbstractButton.IconOnly; alignment: Qt.AlignCenter; mirrored: control.mirrored }
    background: Rectangle {
        radius: 9
        color: control.down ? theme.colors.selected : control.hovered ? theme.colors.hover : "transparent"
        border.width: control.visualFocus ? 2 : 0
        border.color: theme.colors.accent
        Behavior on color { ColorAnimation { duration: 120 } }
    }
    Tip { text: control.hint; visible: control.hovered && control.hint.length > 0 }
}
