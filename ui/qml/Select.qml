import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ComboBox {
    id: control
    implicitHeight: 42
    implicitWidth: Math.max(160, implicitContentWidth + leftPadding + rightPadding)
    leftPadding: 12; rightPadding: 40
    font.pointSize: theme.type.body
    hoverEnabled: true
    contentItem: Text {
        text: control.displayText; font: control.font
        color: control.enabled ? theme.colors.text : theme.colors.disabledText
        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    indicator: Icon {
        name: "chevron-down"; size: 16
        x: control.width - width - 13; y: (control.height - height) / 2
        color: control.enabled ? theme.colors.secondary : theme.colors.disabledText
    }
    background: Rectangle {
        radius: 9
        color: !control.enabled ? theme.colors.disabled : control.down || control.hovered ? theme.colors.hover : theme.colors.surface
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? theme.colors.accent : control.enabled ? theme.colors.border : "transparent"
        Behavior on color { ColorAnimation { duration: 120 } }
    }
    delegate: ItemDelegate {
        id: item
        required property var modelData
        required property int index
        width: ListView.view.width
        height: 38
        hoverEnabled: true
        highlighted: control.highlightedIndex === index
        readonly property string label: control.textRole ? modelData[control.textRole] : modelData
        Accessible.name: label
        contentItem: RowLayout {
            spacing: 8
            Text { Layout.fillWidth: true; text: item.label; font.pointSize: theme.type.body; color: theme.colors.text; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter; font.weight: control.currentIndex === item.index ? Font.DemiBold : Font.Normal }
            Icon { glyph: "check"; size: 14; color: theme.colors.accentText; visible: control.currentIndex === item.index }
        }
        background: Rectangle { radius: 7; color: item.highlighted || item.hovered ? theme.colors.hover : "transparent" }
    }
    popup: Popup {
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 12, 320)
        padding: 6
        palette.window: theme.colors.surface; palette.text: theme.colors.text; palette.highlight: theme.colors.hover
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollBar.vertical: Bar {}
        }
        background: Rectangle { radius: 10; color: theme.colors.surface; border.color: theme.colors.borderStrong }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 100 } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 80 } }
    }
}
