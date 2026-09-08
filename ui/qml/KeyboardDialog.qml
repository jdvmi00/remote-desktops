import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Sheet {
    id: dialog
    objectName: "keyboardDialog"
    title: "Keyboard & local commands"
    subtitle: "Shared by remote desktops on this computer"
    width: Math.min(parent.width - 48, 580)
    height: Math.min(parent.height - 40, 650)
    closePolicy: Popup.NoAutoClose
    onEscapeRequested: requestClose()
    property bool enabledDraft: false
    property string prefixDraft: "F12"
    property int timeoutDraft: 5
    property string revision: ""
    property string error: ""
    property bool edited: false
    function load() {
        const s = manager.keyboard
        enabledDraft = !!s.enabled; prefixDraft = s.prefix || "F12"; timeoutDraft = s.timeout || 5
        revision = s.revision || ""; edited = false; error = ""
    }
    function begin() { load(); open(); manager.loadKeyboard() }
    function requestClose() {
        if (manager.keyboardBusy) return
        if (edited) discard.ask("Discard keyboard changes?", "Your local-command prefix settings will stay as they were.", "Discard", function() { dialog.close() })
        else close()
    }
    Connections {
        target: manager
        function onChanged() { if (dialog.visible && !dialog.edited && !manager.keyboardBusy) dialog.load() }
        function onKeyboardFinished(ok, message) {
            if (!dialog.visible) return
            if (ok) { dialog.edited = false; dialog.close(); manager.notify(manager.keyboard.enabled ? "Local-command prefix saved: " + manager.keyboard.prefix + ", then your usual shortcut." : "Local-command prefix disabled. Moonlight’s Ctrl+Alt+Shift+Z still releases capture.") }
            else dialog.error = message
        }
    }
    Confirm { id: discard; parent: Overlay.overlay }
    component Copy: Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; textFormat: Text.PlainText; color: theme.colors.secondary; lineHeight: 1.2 }
    ScrollView {
        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
        ColumnLayout {
            width: parent.width; spacing: 14
            Check {
                objectName: "prefixEnabled"
                Layout.fillWidth: true; text: "Use a local-command prefix"
                enabled: !!manager.keyboard.available && !manager.keyboardBusy
                checked: dialog.enabledDraft
                onToggled: { dialog.enabledDraft = checked; dialog.edited = true }
            }
            Copy { text: "Keep familiar shortcuts on both computers. Press the prefix, release it, then use a local shortcut. Remote control resumes when you release that combination." }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 8
                enabled: dialog.enabledDraft && !manager.keyboardBusy
                Copy { text: "Prefix shortcut"; color: theme.colors.text; font.weight: Font.Medium }
                Field {
                    objectName: "prefixField"; Layout.fillWidth: true
                    text: dialog.prefixDraft; placeholderText: "F12 or Super+Ctrl+K"; maximumLength: 64
                    Accessible.name: "Local-command prefix shortcut"
                    onTextEdited: { dialog.prefixDraft = text; dialog.edited = true; dialog.error = "" }
                }
                Copy { font.pointSize: theme.type.caption; text: "F12 is a simple starting point. You can use F1–F12, Pause, or modifiers with a letter, number, Space, or Escape. Conflicting local shortcuts will be rejected when you save." }
                RowLayout {
                    Layout.fillWidth: true
                    Copy { text: "Cancel if unused after" }
                    Spin { objectName: "prefixTimeout"; from: 2; to: 15; value: dialog.timeoutDraft; Accessible.name: "Prefix timeout in seconds"; onValueModified: { dialog.timeoutDraft = value; dialog.edited = true } }
                    Copy { text: "seconds"; Layout.fillWidth: false }
                }
            }
            Rectangle {
                Layout.fillWidth: true; implicitHeight: example.implicitHeight + 28
                radius: 10; color: theme.colors.surface; border.color: theme.colors.border
                ColumnLayout {
                    id: example; anchors.fill: parent; anchors.margins: 14; spacing: 8
                    Copy { text: "While controlling a remote desktop"; color: theme.colors.text; font.weight: Font.DemiBold }
                    Copy { text: "Super+Space → remote menu" }
                    Copy { text: (dialog.prefixDraft || "Prefix") + ", then Super+Shift+Arrow → move its local tile" }
                    Copy { text: "Press the prefix again or Esc to cancel. A brief on-screen hint shows when a local command is armed."; font.pointSize: theme.type.caption }
                }
            }
            Copy { text: "Set each computer’s Keyboard shortcuts to “Remote desktop while focused” in Edit. Prefix changes apply immediately; capture changes need Disconnect, then Connect." }
            Copy { text: "Only managed Moonlight windows use this prefix. Unbound keys still go to the focused application. Ctrl+Alt+Shift+Z remains Moonlight’s capture toggle."; font.pointSize: theme.type.caption }
            Copy { visible: !manager.keyboard.available; color: theme.colors.warning; text: manager.keyboard.error || "This option requires a running Hyprland Lua session. You can still choose keyboard capture separately in each computer’s settings." }
            Copy { objectName: "prefixError"; visible: dialog.error.length > 0; text: dialog.error; color: theme.colors.danger; Accessible.role: Accessible.AlertMessage }
            ActionButton { visible: dialog.error.indexOf("changed elsewhere") >= 0; quiet: true; text: "Reload saved settings"; onClicked: { dialog.edited = false; manager.loadKeyboard() } }
        }
    }
    footer: Sheet.Footer {
        ActionButton { text: "Cancel"; quiet: true; enabled: !manager.keyboardBusy; onClicked: dialog.requestClose() }
        Item { Layout.fillWidth: true }
        ActionButton {
            objectName: "saveKeyboard"; primary: true; text: manager.keyboardBusy ? "Applying…" : "Save preferences"
            enabled: !!manager.keyboard.available && !manager.keyboardBusy && dialog.edited && dialog.prefixDraft.trim().length > 0
            onClicked: manager.saveKeyboard({enabled: dialog.enabledDraft, prefix: dialog.prefixDraft, timeout: dialog.timeoutDraft, revision: dialog.revision})
        }
    }
}
