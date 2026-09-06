import QtQuick
import QtQuick.Controls

CheckBox {
    id: control
    spacing: 10
    font.pointSize: theme.type.body
    indicator: Rectangle {
        implicitWidth: 22; implicitHeight: 22; radius: 6
        x: control.leftPadding; y: (control.height - height) / 2
        color: !control.enabled ? theme.colors.disabled : control.checked ? theme.colors.accent : theme.colors.surface
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? theme.colors.accent : control.checked ? theme.colors.accent : theme.colors.borderStrong
        Behavior on color { ColorAnimation { duration: 120 } }
        Icon { glyph: "check"; size: 14; anchors.centerIn: parent; color: control.enabled ? theme.colors.onAccent : theme.colors.disabledText; visible: control.checked }
    }
    contentItem: Text {
        text: control.text; font: control.font
        color: control.enabled ? theme.colors.text : theme.colors.disabledText
        leftPadding: control.indicator.width + control.spacing
        verticalAlignment: Text.AlignVCenter; wrapMode: Text.WordWrap
    }
}
