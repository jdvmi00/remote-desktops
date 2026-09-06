import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Themed modal dialog base. Popups do not inherit the window palette, so the
// full palette is set here for any default-styled internals.
Dialog {
    id: sheet
    property string subtitle: ""
    // Modal popups swallow window shortcuts, so Escape is handled here. A
    // dialog that opts out of automatic closing gets a signal instead.
    signal escapeRequested()
    component Footer: Item {
        default property alias content: row.data
        implicitHeight: row.implicitHeight + 32
        RowLayout { id: row; anchors.fill: parent; anchors.margins: 16; anchors.topMargin: 12; spacing: 10 }
    }
    anchors.centerIn: parent
    width: Math.min(parent.width - 48, 560)
    modal: true
    focus: true
    padding: 24; topPadding: 12
    palette.window: theme.colors.bg; palette.windowText: theme.colors.text; palette.text: theme.colors.text
    palette.base: theme.colors.surface; palette.button: theme.colors.surface; palette.buttonText: theme.colors.text
    palette.highlight: theme.colors.accent; palette.highlightedText: theme.colors.onAccent
    palette.mid: theme.colors.border; palette.dark: theme.colors.borderStrong; palette.light: theme.colors.hover
    palette.toolTipBase: theme.colors.tooltipBg; palette.toolTipText: theme.colors.tooltipText; palette.placeholderText: theme.colors.muted
    background: Rectangle { radius: 16; color: theme.colors.bg; border.color: theme.colors.borderStrong }
    Overlay.modal: Rectangle { color: theme.colors.overlay }
    header: ColumnLayout {
        spacing: 4
        Label { Layout.leftMargin: 24; Layout.rightMargin: 24; Layout.topMargin: 22; Layout.fillWidth: true; text: sheet.title; color: theme.colors.text; font.pointSize: theme.type.subtitle; font.weight: Font.DemiBold; elide: Text.ElideRight }
        Label { visible: sheet.subtitle.length > 0; Layout.leftMargin: 24; Layout.rightMargin: 24; Layout.fillWidth: true; text: sheet.subtitle; color: theme.colors.secondary; wrapMode: Text.WordWrap }
    }
    contentItem: ColumnLayout {
        spacing: 16
        // The content item takes focus inside the popup so key events pass
        // through it before the popup's own handling.
        focus: true
        Keys.onEscapePressed: event => {
            if (sheet.closePolicy & Popup.CloseOnEscape) event.accepted = false
            else { sheet.escapeRequested(); event.accepted = true }
        }
    }
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 }
        NumberAnimation { property: "scale"; from: .97; to: 1; duration: 160; easing.type: Easing.OutCubic }
    }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
}
