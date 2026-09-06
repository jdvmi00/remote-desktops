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
        color: !control.enabled ? "#747d85" : control.primary ? "#122820" : control.destructive ? "#f2b2a7" : "#e7ece8"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 9
        color: !control.enabled ? "#20272b" : control.primary ? (control.down ? "#85c8a5" : control.hovered ? "#c5f3d6" : "#afe6c5") : control.hovered ? "#303a3e" : "#232c30"
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? "#afe6c5" : control.primary ? "transparent" : "#3b474b"
        Behavior on color { ColorAnimation { duration: 110 } }
    }
}
