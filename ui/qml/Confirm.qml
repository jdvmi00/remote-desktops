import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Sheet {
    id: confirm
    property string body: ""
    property string actionText: "Continue"
    property bool destructive: true
    property var callback: null
    width: Math.min(parent.width - 48, 440)
    function ask(title, body, actionText, callback) {
        confirm.title = title; confirm.body = body; confirm.actionText = actionText; confirm.callback = callback
        open()
    }
    Label { Layout.fillWidth: true; text: confirm.body; color: theme.colors.secondary; wrapMode: Text.WordWrap; lineHeight: 1.25 }
    footer: Sheet.Footer {
        ActionButton { text: "Cancel"; onClicked: confirm.close() }
        Item { Layout.fillWidth: true }
        ActionButton {
            objectName: "confirmAction"
            text: confirm.actionText; primary: !confirm.destructive; destructive: confirm.destructive
            onClicked: { const run = confirm.callback; confirm.close(); if (run) run() }
        }
    }
}
