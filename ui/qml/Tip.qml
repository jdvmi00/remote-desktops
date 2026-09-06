import QtQuick
import QtQuick.Controls

ToolTip {
    id: tip
    delay: 600
    padding: 8; leftPadding: 11; rightPadding: 11
    font.pointSize: theme.type.caption
    contentItem: Text { text: tip.text; font: tip.font; color: theme.colors.tooltipText; wrapMode: Text.WordWrap }
    background: Rectangle { color: theme.colors.tooltipBg; radius: 7; border.color: theme.colors.borderStrong }
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 120 } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 90 } }
}
