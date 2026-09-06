import QtQuick
import QtQuick.Controls

TextField {
    id: control
    property bool invalid: false
    implicitHeight: 42
    leftPadding: 12; rightPadding: 12
    font.pointSize: theme.type.body
    color: enabled ? theme.colors.text : theme.colors.disabledText
    placeholderTextColor: theme.colors.muted
    selectionColor: theme.colors.accent; selectedTextColor: theme.colors.onAccent
    background: Rectangle {
        radius: 9
        color: control.enabled ? theme.colors.surface : theme.colors.disabled
        border.width: control.activeFocus || control.invalid ? 2 : 1
        border.color: control.invalid ? theme.colors.danger : control.activeFocus ? theme.colors.accent : theme.colors.border
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
}
