import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl

Button {
    id: control
    property bool primary: false
    property bool destructive: false
    // Quiet buttons are tertiary actions: no surface until hovered.
    property bool quiet: false
    property string hint: ""
    readonly property color contentColor: !enabled ? theme.colors.disabledText
        : primary ? theme.colors.onAccent
        : destructive ? theme.colors.danger
        : quiet ? theme.colors.secondary : theme.colors.text
    icon.width: 18; icon.height: 18
    icon.color: contentColor
    implicitHeight: quiet ? 36 : 42
    implicitWidth: Math.max(quiet ? 0 : 96, implicitContentWidth + leftPadding + rightPadding)
    leftPadding: quiet ? 10 : 18; rightPadding: quiet ? 10 : 18
    spacing: 8
    font.pointSize: theme.type.body
    font.weight: quiet ? Font.Medium : Font.DemiBold
    hoverEnabled: true
    Accessible.name: text
    contentItem: IconLabel {
        icon: control.icon
        text: control.text
        font: control.font
        color: control.contentColor
        spacing: control.spacing
        display: control.display
        mirrored: control.mirrored
        alignment: Qt.AlignCenter
    }
    background: Rectangle {
        radius: 9
        color: !control.enabled ? (control.quiet ? "transparent" : theme.colors.disabled)
            : control.primary ? (control.down ? theme.colors.accentPressed : control.hovered ? theme.colors.accentHover : theme.colors.accent)
            : control.destructive && !control.quiet ? (control.down ? theme.colors.dangerBorder : control.hovered ? theme.colors.dangerBg : theme.colors.surface)
            : control.down ? theme.colors.selected : control.hovered ? theme.colors.hover : control.quiet ? "transparent" : theme.colors.surface
        border.width: control.visualFocus ? 2 : (control.primary || control.quiet || !control.enabled) ? 0 : 1
        border.color: control.visualFocus ? theme.colors.accent : control.destructive ? theme.colors.dangerBorder : theme.colors.border
        Behavior on color { ColorAnimation { duration: 120 } }
    }
    Tip { text: control.hint; visible: control.hovered && control.hint.length > 0 }
}
