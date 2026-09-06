import QtQuick
import QtQuick.Controls

// Scroll bar that stays visible whenever there is more content to reach.
ScrollBar {
    id: bar
    policy: ScrollBar.AsNeeded
    implicitWidth: 12; implicitHeight: 12
    padding: 3
    minimumSize: .08
    hoverEnabled: true
    contentItem: Rectangle {
        implicitWidth: 6; implicitHeight: 6
        radius: 3
        color: bar.pressed || bar.hovered ? theme.colors.muted : theme.colors.borderStrong
        opacity: bar.size < 1 ? (bar.active || bar.hovered ? 1 : .85) : 0
        Behavior on opacity { NumberAnimation { duration: 150 } }
        Behavior on color { ColorAnimation { duration: 120 } }
    }
}
