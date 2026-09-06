import QtQuick
import QtQuick.Controls

SpinBox {
    id: control
    implicitHeight: 42
    editable: true
    font.pointSize: theme.type.body
    leftPadding: 44; rightPadding: 44
    contentItem: TextInput {
        text: control.displayText; font: control.font
        color: control.enabled ? theme.colors.text : theme.colors.disabledText
        selectionColor: theme.colors.accent; selectedTextColor: theme.colors.onAccent
        horizontalAlignment: Qt.AlignHCenter; verticalAlignment: Qt.AlignVCenter
        readOnly: !control.editable; validator: control.validator; inputMethodHints: control.inputMethodHints
        clip: width < implicitWidth
    }
    component Step: Rectangle {
        required property bool pressed
        required property bool hovered
        required property string glyph
        implicitWidth: 40; height: control.height; radius: 9
        color: pressed ? theme.colors.selected : hovered ? theme.colors.hover : "transparent"
        Icon { glyph: parent.glyph; size: 16; anchors.centerIn: parent; color: control.enabled ? theme.colors.secondary : theme.colors.disabledText }
    }
    up.indicator: Step { x: control.width - width; pressed: control.up.pressed; hovered: control.up.hovered; glyph: "plus" }
    down.indicator: Step { x: 0; pressed: control.down.pressed; hovered: control.down.hovered; glyph: "minus" }
    background: Rectangle {
        radius: 9
        color: control.enabled ? theme.colors.surface : theme.colors.disabled
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? theme.colors.accent : theme.colors.border
    }
}
