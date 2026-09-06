import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 1120; height: 760
    minimumWidth: 820; minimumHeight: 650
    visible: true
    title: manager.demo ? "Remote Desktops · Design preview" : "Remote Desktops"
    color: theme.colors.bg
    palette.window: theme.colors.bg
    palette.windowText: theme.colors.text
    palette.text: theme.colors.text
    palette.button: theme.colors.surface
    palette.buttonText: theme.colors.text
    palette.base: theme.colors.surface
    palette.alternateBase: theme.colors.hover
    palette.highlight: theme.colors.accent
    palette.highlightedText: theme.colors.onAccent
    palette.brightText: theme.colors.onAccent
    palette.dark: theme.colors.secondary
    palette.mid: theme.colors.border
    font.family: "Inter"
    font.pixelSize: 14
    property string selectedId: ""
    property string chosenProfile: ""
    readonly property var entries: manager.computers
    readonly property var selected: {
        for (let i = 0; i < entries.length; ++i) if (entries[i].computer === selectedId) return entries[i]
        return entries.length ? entries[0] : null
    }
    readonly property string phase: selected ? selected.phase : "idle"
    readonly property bool connected: selected && !selected.stale && !!selected.window && selected.desired
    readonly property bool recovering: phase === "restore-pending" || phase === "attention" && selected && (!!selected.recovery_pending || !!selected.recovery_error)
    readonly property bool transitioning: manager.available && ["preflight", "preparing", "connecting", "reconnecting", "stopping", "restoring", "release-pending"].indexOf(phase) >= 0
    readonly property string profile: {
        if (!selected) return ""
        if (selected.desired && selected.profile) return selected.profile
        const profiles = selected.profiles || []
        return profiles.indexOf(chosenProfile) >= 0 ? chosenProfile : selected.default_profile || (profiles.indexOf("desktop") >= 0 ? "desktop" : profiles[0]) || ""
    }
    readonly property bool canAct: !!root.selected && !root.selected.busy && !root.transitioning && (!root.selected.unconfigured || root.recovering)
    onSelectedIdChanged: chosenProfile = ""
    onActiveChanged: manager.setActive(active)
    function label(p) {
        return ({"window-ready":"Connected", running:"Client running", idle:"Disconnected", preflight:"Checking connection", preparing:"Preparing desktop", connecting:"Opening desktop", reconnecting:"Reconnecting", stopping:"Disconnecting", restoring:"Restoring display", "restore-pending":"Restore needed", attention:"Needs attention", "release-pending":"Releasing recovery"})[p] || "Checking status"
    }
    function action() {
        if (!canAct) return
        manager.act(selected.computer, recovering ? "restore" : connected ? "focus" : "connect", profile)
    }
    Shortcut { sequence: "Ctrl+R"; onActivated: manager.refresh() }
    Shortcut { sequence: "Ctrl+Return"; enabled: root.canAct; onActivated: root.action() }
    Shortcut { sequences: [StandardKey.Cancel]; onActivated: { help.close(); details.close() } }
    component Caption: Label { color: theme.colors.secondary; font.pixelSize: 12; font.letterSpacing: 1.4 }
    component Body: Label { textFormat: Text.PlainText; color: theme.colors.secondary; wrapMode: Text.WordWrap; lineHeight: 1.25 }
    component Divider: Rectangle { color: theme.colors.border; height: 1; Layout.fillWidth: true }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.preferredWidth: root.width < 960 ? 258 : 290
            Layout.fillHeight: true
            color: theme.colors.sidebar
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 24; spacing: 0
                RowLayout {
                    Layout.topMargin: 10; spacing: 12
                    Rectangle {
                        width: 34; height: 34; radius: 10; color: theme.colors.accent
                        ComputerGlyph { anchors.centerIn: parent; ink: theme.colors.onAccent }
                    }
                    Label { text: "Remote\nDesktops"; color: theme.colors.text; font.pixelSize: 17; font.weight: Font.DemiBold; lineHeight: .95 }
                }
                Caption { text: "YOUR COMPUTERS"; Layout.topMargin: 48; Layout.bottomMargin: 16 }
                ListView {
                    id: computerList
                    objectName: "computerList"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; spacing: 8; model: root.entries
                    keyNavigationEnabled: true
                    Keys.onDownPressed: if (currentIndex + 1 < root.entries.length) root.selectedId = root.entries[currentIndex + 1].computer
                    Keys.onUpPressed: if (currentIndex > 0) root.selectedId = root.entries[currentIndex - 1].computer
                    currentIndex: { for (let i=0; i<root.entries.length; ++i) if(root.entries[i].computer===root.selectedId) return i; return 0 }
                    delegate: ItemDelegate {
                        id: row
                        required property var modelData
                        required property int index
                        width: computerList.width; height: 84
                        hoverEnabled: true
                        readonly property bool selected: root.selected && root.selected.computer === modelData.computer
                        Accessible.name: modelData.name + ", " + (modelData.stale ? "Status unavailable" : root.label(modelData.phase))
                        onClicked: { root.selectedId = modelData.computer; computerList.currentIndex = index }
                        background: Rectangle {
                            radius: 10; color: row.selected ? theme.colors.selected : row.hovered ? theme.colors.hover : "transparent"
                            border.width: row.visualFocus ? 2 : 1
                            border.color: row.visualFocus ? theme.colors.accent : row.selected ? theme.colors.selectedBorder : "transparent"
                        }
                        contentItem: RowLayout {
                            spacing: 12
                            ComputerGlyph { Layout.leftMargin: 5; ink: row.selected ? theme.colors.accent : theme.colors.muted; laptop: modelData.platform === "macos" || modelData.platform === "windows" }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 7
                                Label { Layout.fillWidth: true; textFormat: Text.PlainText; text: modelData.name || modelData.computer; color: theme.colors.text; font.weight: Font.Medium; elide: Text.ElideRight }
                                RowLayout {
                                    spacing: 6
                                    Rectangle { width: 5; height: 5; radius: 3; color: modelData.stale ? theme.colors.muted : modelData.phase === "window-ready" ? theme.colors.accent : modelData.phase === "restore-pending" || modelData.phase === "attention" ? theme.colors.warning : theme.colors.muted }
                                    Label { text: modelData.stale ? "Status unavailable" : root.label(modelData.phase); color: theme.colors.secondary; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                                }
                            }
                        }
                    }
                }
                ActionButton { Layout.fillWidth: true; text: "Refresh computers"; hint: "Refresh settings and connection status · Ctrl+R"; enabled: !manager.loading; onClicked: manager.refresh() }
                Item { height: 14 }
                ActionButton { Layout.fillWidth: true; text: "Setup & help"; onClicked: help.open() }
                Divider { Layout.topMargin: 22; Layout.bottomMargin: 18 }
                RowLayout {
                    spacing: 7
                    Rectangle { width: 6; height: 6; radius: 3; color: manager.available ? theme.colors.accent : theme.colors.warning }
                    Label { text: manager.demo ? "DESIGN PREVIEW" : manager.available ? "MANAGER READY" : "STATUS UNAVAILABLE"; color: theme.colors.muted; font.pixelSize: 10; font.letterSpacing: 1 }
                }
                Body { Layout.fillWidth: true; Layout.topMargin: 9; Layout.bottomMargin: 8; text: manager.demo ? "Sample computers. All actions are simulated." : "Your connections stay open when you close this window."; font.pixelSize: 11; color: theme.colors.muted }
            }
        }
        Rectangle { Layout.fillHeight: true; width: 1; color: theme.colors.border }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                width: parent.width
                spacing: 0
                Item { Layout.preferredHeight: 36 }
                ColumnLayout {
                    Layout.fillWidth: true; Layout.leftMargin: 38; Layout.rightMargin: 38; spacing: 0
                    Caption { text: "WORK FROM ANYWHERE" }
                    RowLayout {
                        Layout.fillWidth: true; Layout.topMargin: 12; spacing: 14
                        Label { Layout.fillWidth: true; textFormat: Text.PlainText; text: root.selected ? root.selected.name || root.selected.computer : "Your desk, wherever you are."; color: theme.colors.text; font.pixelSize: root.width < 960 ? 29 : 36; font.weight: Font.DemiBold; font.letterSpacing: -1; elide: Text.ElideRight }
                        Rectangle {
                            visible: !!root.selected; implicitWidth: statusText.implicitWidth + 26; height: 30; radius: 15
                            color: root.recovering ? theme.colors.warningBg : root.connected ? theme.colors.selected : theme.colors.surface
                            Label { id: statusText; anchors.centerIn: parent; text: !manager.available ? "Status unavailable" : root.label(root.phase); color: root.recovering ? theme.colors.warning : root.connected ? theme.colors.accentText : theme.colors.secondary; font.pixelSize: 11; font.weight: Font.Medium }
                        }
                    }
                    Body { Layout.fillWidth: true; Layout.topMargin: 9; text: root.selected ? (root.selected.platform === "macos" ? "macOS" : root.selected.platform === "windows" ? "Windows" : root.selected.platform === "linux" ? "Linux" : "Remote computer") + (root.selected.host ? "  /  " + root.selected.host : "") : "Bring your computers together in one quiet workspace."; elide: Text.ElideRight; maximumLineCount: 2 }
                    Rectangle {
                        visible: !!manager.error || (!manager.available && !manager.loading)
                        Layout.fillWidth: true; Layout.topMargin: 20; implicitHeight: serviceMessage.implicitHeight + 28; radius: 10; color: theme.colors.warningBg; border.color: theme.colors.warningBorder
                        Body { id: serviceMessage; anchors.fill: parent; anchors.margins: 14; color: theme.colors.warning; text: manager.error || "Live status is unavailable. Existing connections may still be running. Connect starts the service if needed; refresh to check again."; font.pixelSize: 12 }
                    }
                    Rectangle {
                        visible: !!manager.notice
                        Layout.fillWidth: true; Layout.topMargin: 16
                        implicitHeight: feedback.implicitHeight + 24
                        color: theme.colors.selected; border.color: theme.colors.selectedBorder; radius: 10
                        RowLayout {
                            id: feedback
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12
                            Body { Layout.fillWidth: true; text: manager.notice; font.pixelSize: 12; Accessible.role: Accessible.AlertMessage }
                            Button { text: "Dismiss"; flat: true; palette.windowText: theme.colors.secondary; onClicked: manager.clearNotice() }
                        }
                    }
                    Rectangle {
                        visible: root.recovering || !!(root.selected && root.selected.error)
                        Layout.fillWidth: true; Layout.topMargin: 20; implicitHeight: recoveryText.implicitHeight + 34; color: theme.colors.warningBg; radius: 12; border.color: theme.colors.warningBorder
                        ColumnLayout {
                            id: recoveryText
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 17; spacing: 7
                            Label { text: root.recovering ? "Your display settings are protected" : "This connection needs attention"; color: theme.colors.warning; font.weight: Font.DemiBold }
                            Body { Layout.fillWidth: true; text: root.recovering ? "The last session could not finish restoring the host display. Bring the computer online, then restore before connecting again." : "Check that the computer and Sunshine are available, then try again."; font.pixelSize: 12; color: theme.colors.warning }
                            Button { text: "View technical details"; flat: true; palette.windowText: theme.colors.warning; onClicked: details.open() }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true; Layout.topMargin: 27
                        implicitHeight: root.recovering || manager.error || manager.notice || !manager.available ? 220 : 280; radius: 16; color: theme.colors.surface; border.color: theme.colors.border
                        gradient: Gradient { GradientStop { position: 0; color: theme.colors.heroStart } GradientStop { position: 1; color: theme.colors.heroEnd } }
                        BusyIndicator { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 14; width: 28; height: 28; running: root.transitioning || !!(root.selected && root.selected.busy); visible: running; Accessible.name: "Connection operation in progress" }
                        // Abstract device illustration; never a fabricated remote screenshot.
                        Rectangle {
                            width: 220; height: 132; radius: 10; anchors.horizontalCenter: parent.horizontalCenter; y: parent.height < 280 ? 15 : 34
                            scale: parent.height < 280 ? 0.75 : 1
                            transformOrigin: Item.Top
                            color: theme.colors.screen; border.color: root.connected ? theme.colors.selectedBorder : theme.colors.border; border.width: 2
                            Rectangle { anchors.fill: parent; anchors.margins: 7; radius: 5; color: theme.colors.screen
                                Rectangle { x: 14; y: 15; width: 52; height: 80; radius: 5; color: theme.colors.tile1 }
                                Rectangle { x: 76; y: 15; width: 110; height: 35; radius: 5; color: theme.colors.tile2 }
                                Rectangle { x: 76; y: 60; width: 50; height: 35; radius: 5; color: theme.colors.tile1 }
                                Rectangle { x: 136; y: 60; width: 50; height: 35; radius: 5; color: theme.colors.tile3 }
                            }
                            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 133; width: 20; height: 12; color: theme.colors.selectedBorder }
                            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 144; width: 76; height: 3; radius: 2; color: theme.colors.selectedBorder }
                        }
                        ColumnLayout {
                            anchors.horizontalCenter: parent.horizontalCenter; y: parent.height < 280 ? 145 : 202; width: parent.width - 40; spacing: 8
                            Label { Layout.alignment: Qt.AlignHCenter; text: manager.loading ? "Finding your computers…" : !root.selected ? "A place for every computer" : !manager.available ? "Connection status unavailable" : root.selected.busy ? "Sending request…" : root.transitioning ? root.label(root.phase) + "…" : root.recovering ? "Let's finish restoring your display" : root.connected ? "Your desktop is open" : root.phase === "running" ? "Client started" : "Ready when you are"; color: theme.colors.text; font.pixelSize: 19; font.weight: Font.Medium }
                            Body { Layout.alignment: Qt.AlignHCenter; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true; font.pixelSize: 12; text: !root.selected ? "Set up a paired computer to start your first session." : !manager.available ? "Refresh status, or connect to start the manager again." : root.connected ? "Switch to its window and pick up where you left off." : root.phase === "running" ? "The client is running; window detection is not available." : root.recovering ? "The saved recovery record stays safe until restoration succeeds." : "A full desktop, in its own window." }
                        }
                    }
                    ActionButton {
                        visible: !root.selected && !manager.loading
                        Layout.topMargin: 20
                        primary: true; text: "Set up a computer"; onClicked: help.open()
                    }
                    RowLayout {
                        visible: !!root.selected
                        Layout.fillWidth: true; Layout.topMargin: 24; spacing: 18
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 8
                            Caption { text: "CONNECTION PROFILE"; font.pixelSize: 10 }
                            ComboBox {
                                id: profiles
                                Layout.preferredWidth: Math.min(240, root.width / 4)
                                model: root.selected ? root.selected.profiles || [] : []
                                currentIndex: Math.max(0, model.indexOf(root.profile))
                                enabled: !!root.selected && !root.selected.desired && !root.selected.busy && !root.recovering && !root.transitioning
                                onActivated: root.chosenProfile = currentText
                                Accessible.name: "Connection profile"
                                palette.text: theme.colors.text; palette.buttonText: theme.colors.text; palette.base: theme.colors.surface; palette.highlight: theme.colors.selectedBorder; palette.highlightedText: theme.colors.text
                                background: Rectangle { radius: 8; color: theme.colors.surface; border.color: profiles.visualFocus ? theme.colors.accent : theme.colors.border }
                                ToolTip.visible: hovered && !enabled
                                ToolTip.text: "Disconnect before changing profiles."
                            }
                        }
                        ColumnLayout {
                            Layout.alignment: Qt.AlignRight; spacing: 9
                            Caption { text: "SESSION BEHAVIOR"; font.pixelSize: 10 }
                            Label { text: "Windowed · Move freely"; color: theme.colors.secondary; font.pixelSize: 13 }
                            Label { text: "No workspace restrictions"; color: theme.colors.muted; font.pixelSize: 11 }
                        }
                    }
                    Divider { Layout.topMargin: 23; Layout.bottomMargin: 23 }
                    RowLayout {
                        visible: !!root.selected
                        Layout.fillWidth: true; spacing: 10
                        ActionButton {
                            objectName: "primaryAction"
                            primary: true
                            text: root.selected && root.selected.busy ? "Working…" : root.recovering ? "Restore display" : root.connected ? "Open desktop  ↗" : root.transitioning ? "Connecting…" : "Connect  ↗"
                            enabled: root.canAct
                            hint: root.connected ? "Focus the existing desktop window · Ctrl+Enter" : "Start a desktop session · Ctrl+Enter"
                            onClicked: root.action()
                        }
                        ActionButton { text: "Reconnect"; visible: root.connected; enabled: !!root.selected && !root.selected.busy && manager.available && !root.transitioning; hint: "Restart this client connection"; onClicked: manager.act(root.selected.computer, "reconnect") }
                        Item { Layout.fillWidth: true }
                        ActionButton { text: root.transitioning ? "Cancel" : "Disconnect"; destructive: true; visible: !!root.selected && root.selected.desired; enabled: !!root.selected && !root.selected.busy && manager.available; hint: "Close the remote window and restore owned host settings"; onClicked: manager.act(root.selected.computer, "disconnect") }
                    }
                    RowLayout {
                        Layout.fillWidth: true; Layout.topMargin: 18; visible: !!root.selected
                        Button { text: "Add to app launcher"; flat: true; palette.windowText: theme.colors.secondary; enabled: !!root.selected && !root.selected.busy && !root.selected.unconfigured; onClicked: manager.act(root.selected.computer, "launcher") }
                        Item { Layout.fillWidth: true }
                        Button { text: "Connection details"; flat: true; palette.windowText: theme.colors.muted; onClicked: details.open() }
                    }
                    Item { Layout.preferredHeight: 28 }
                }
            }
        }
    }
    Dialog {
        id: help
        objectName: "helpDialog"
        anchors.centerIn: parent; width: Math.min(root.width - 64, 540)
        modal: true; title: "Make yourself at home"; standardButtons: Dialog.Close
        palette.window: theme.colors.surface; palette.windowText: theme.colors.text; palette.text: theme.colors.text; palette.buttonText: theme.colors.text
        ColumnLayout {
            width: parent.width; spacing: 18
            Body { Layout.fillWidth: true; text: "Remote Desktops manages your connections. Each remote desktop opens in its own Moonlight window." }
            Body { Layout.fillWidth: true; text: "1. Pair your computer in Moonlight.\n2. Add its connection settings using the setup guide.\n3. Refresh this list, choose a profile, and connect." }
            Body { Layout.fillWidth: true; text: "Add a computer to your app launcher to open it directly. In Hypertile Scenes, choose that launcher as an ordinary app." }
            ActionButton { text: "Open setup guide  ↗"; onClicked: Qt.openUrlExternally("https://github.com/jdvmi00/remote-desktops/blob/develop/docs/BACKEND.md") }
            Divider {}
            Body { Layout.fillWidth: true; text: "Ctrl+Enter opens the selected desktop. Ctrl+R refreshes. Tab moves between controls. Closing this manager never disconnects a computer."; font.pixelSize: 12 }
            Body { Layout.fillWidth: true; text: "Inside Moonlight, Ctrl+Alt+Shift+Z toggles mouse and keyboard capture."; font.pixelSize: 12 }
        }
    }
    Dialog {
        id: details
        anchors.centerIn: parent; width: Math.min(root.width - 64, 550)
        modal: true; title: "Connection details"; standardButtons: Dialog.Close
        palette.window: theme.colors.surface; palette.windowText: theme.colors.text; palette.text: theme.colors.text; palette.buttonText: theme.colors.text
        ColumnLayout {
            width: parent.width; spacing: 16
            Body { Layout.fillWidth: true; text: root.selected ? "Computer: " + root.selected.computer + "\nProfile: " + root.profile + "\nState: " + root.label(root.phase) + "\nWindow detected: " + (root.selected.window ? "Yes" : "No") : "No computer selected." }
            Body { Layout.fillWidth: true; text: root.selected ? root.selected.error || root.selected.recovery_error || "No connection errors reported." : ""; color: theme.colors.warning }
            Body { Layout.fillWidth: true; text: "Window detection confirms an owned client window. It does not measure video latency, frame rate, or image quality."; font.pixelSize: 12 }
            ActionButton { text: "Copy details"; onClicked: manager.copy(root.selected ? "Computer: " + root.selected.computer + "\nPhase: " + root.phase + "\n" + (root.selected.error || root.selected.recovery_error || "") : "No computer selected") }
        }
    }
}
