import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool primary: false
    property bool destructive: false
    property string hint: ""
    implicitHeight: 44
    implicitWidth: Math.max(100, contentItem.implicitWidth + 36)
    font.pixelSize: 14
    font.weight: Font.DemiBold
    hoverEnabled: true
    Accessible.name: text
    ToolTip.visible: hovered && hint.length > 0
    ToolTip.text: hint
    ToolTip.delay: 650
    contentItem: Text {
        text: control.text
        font: control.font
        color: !control.enabled ? theme.colors.disabledText : control.primary ? theme.colors.onAccent : control.destructive ? theme.colors.danger : theme.colors.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 9
        color: !control.enabled ? theme.colors.disabled : control.primary ? (control.down ? theme.colors.accentPressed : control.hovered ? theme.colors.accentHover : theme.colors.accent) : control.hovered ? theme.colors.hover : theme.colors.surface
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? theme.colors.accent : control.primary ? "transparent" : theme.colors.border
        Behavior on color { ColorAnimation { duration: 110 } }
    }
}
