import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 1120; height: 760
    minimumWidth: 880; minimumHeight: 600
    visible: true
    title: manager.demo ? "Remote Desktops · Preview" : "Remote Desktops"
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
    palette.dark: theme.colors.borderStrong
    palette.mid: theme.colors.border
    palette.placeholderText: theme.colors.muted
    palette.toolTipBase: theme.colors.tooltipBg
    palette.toolTipText: theme.colors.tooltipText
    // Type follows the desktop font; only the scale is set here.
    font.pointSize: theme.type.body

    property string selectedId: ""
    property string chosenProfile: ""
    property real nowSeconds: Date.now() / 1000
    readonly property var entries: manager.computers
    readonly property var selected: {
        for (let i = 0; i < entries.length; ++i) if (entries[i].computer === selectedId) return entries[i]
        return entries.length ? entries[0] : null
    }
    readonly property string phase: selected ? selected.phase : "idle"
    readonly property bool stale: !!selected && !!selected.stale
    readonly property bool connected: !!selected && !stale && !!selected.window && !!selected.desired
    readonly property bool recovering: phase === "restore-pending" || (phase === "attention" && !!selected && (!!selected.recovery_pending || !!selected.recovery_error))
    readonly property bool transitioning: manager.available && ["preflight", "preparing", "connecting", "reconnecting", "stopping", "restoring", "release-pending"].indexOf(phase) >= 0
    readonly property var profiles: selected ? selected.profiles || [] : []
    readonly property string profile: {
        if (!selected) return ""
        if (selected.desired && selected.profile) return selected.profile
        return profiles.indexOf(chosenProfile) >= 0 ? chosenProfile : selected.default_profile || (profiles.indexOf("desktop") >= 0 ? "desktop" : profiles[0]) || ""
    }
    readonly property bool canAct: !!selected && !selected.busy && !transitioning && phase !== "running" && (!selected.unconfigured || recovering)
    readonly property string errorText: selected && !stale ? (selected.error || selected.recovery_error || "") : ""
    readonly property string headline: {
        if (!selected) return ""
        if (stale) return "Status unavailable"
        if (selected.busy) return "Sending request…"
        if (selected.unconfigured) return recovering ? "Display restore needed" : "Removed from settings"
        if (recovering) return "Display restore needed"
        if (phase === "attention") return "Needs attention"
        if (connected) return "Connected"
        if (phase === "running") return "Client running"
        if (transitioning) return label(phase) + "…"
        return "Not connected"
    }
    readonly property string explanation: {
        if (!selected) return ""
        if (stale) return "Last known state: " + label(phase).toLowerCase() + ". The background service is not answering, so this may be out of date. An open desktop window keeps working."
        if (selected.unconfigured) return recovering ? "This computer was removed from your settings, but its last session could not restore the host display. Restore it before forgetting the record."
                                                     : "This computer is no longer in your settings. Its session record is settled and can be removed."
        if (recovering) return "The last session could not finish restoring the host display. Bring the computer online, then restore before connecting again."
        if (phase === "attention") return "The last connection ended with an error. Check that the computer and Sunshine are reachable, then connect again."
        if (connected) return "Your desktop is open in its own Moonlight window. Switch to it, or reconnect to restart the client."
        if (phase === "running") return "The Moonlight client is running, but window detection is not available in this session. Open it from your taskbar."
        if (phase === "preflight") return "Checking that the computer and Sunshine are reachable."
        if (phase === "preparing") return "Preparing the host display for streaming."
        if (phase === "connecting") return "Starting Moonlight and waiting for its window."
        if (phase === "reconnecting") return "Restarting the client. The saved recovery settings are kept."
        if (phase === "stopping") return "Closing the desktop window and restoring the host display."
        if (phase === "restoring") return "Restoring the host display settings."
        if (phase === "release-pending") return "Releasing the saved recovery record."
        return "Connect to open a full desktop in its own window."
    }
    readonly property var facts: {
        const f = []
        if (!selected || stale || selected.unconfigured) return f
        if (connected && selected.launched_at > 0) f.push({label: "Connected for", value: duration(selected.launched_at)})
        if (profile) f.push({label: "Profile", value: profile})
        if (selected.desired || phase === "running") f.push({label: "Window", value: selected.window ? "Detected" : phase === "running" ? "Not observed" : "Waiting"})
        const video = selected.evidence ? selected.evidence.negotiated_video : null
        if (video && video.width) f.push({label: "Video stream", value: video.width + " × " + video.height + " · " + video.fps + " fps"})
        if (selected.desired && selected.client_version && selected.client_version !== "unknown") f.push({label: "Client", value: "Moonlight " + selected.client_version})
        if (selected.attempts > 0 && selected.next_retry > nowSeconds) f.push({label: "Next attempt", value: "in " + Math.ceil(selected.next_retry - nowSeconds) + " s · attempt " + (selected.attempts + 1) + " of 3"})
        return f
    }
    readonly property string tone: !selected || stale ? "neutral" : recovering || phase === "attention" ? "warning" : connected ? "success" : "neutral"
    onSelectedIdChanged: chosenProfile = ""
    onActiveChanged: manager.setActive(active)
    function label(p) {
        return ({"window-ready": "Connected", running: "Client running", idle: "Not connected", preflight: "Checking connection", preparing: "Preparing desktop",
                 connecting: "Opening desktop", reconnecting: "Reconnecting", stopping: "Disconnecting", restoring: "Restoring display",
                 "restore-pending": "Restore needed", attention: "Needs attention", "release-pending": "Releasing recovery"})[p] || "Checking status"
    }
    function platformName(p) { return ({macos: "macOS", windows: "Windows", linux: "Linux"})[p] || "Remote computer" }
    function duration(since) {
        const s = Math.max(0, Math.floor(nowSeconds - since))
        if (s < 60) return "under a minute"
        const m = Math.floor(s / 60)
        if (m < 60) return m + " min"
        return Math.floor(m / 60) + " h " + (m % 60) + " min"
    }
    function action() {
        if (!canAct) return
        manager.act(selected.computer, recovering ? "restore" : connected ? "focus" : "connect", profile)
    }
    function removeSelected() {
        if (!selected || selected.busy) return
        const id = selected.computer, name = selected.name || id
        confirm.ask("Remove " + name + "?",
                    selected.unconfigured ? "The settled session record for this computer will be deleted."
                                          : "Its settings and app launcher entry will be deleted. Pairing stays in Moonlight, so it can be added again later.",
                    "Remove", function() { manager.remove(id) })
    }
    function preview(name) {
        // Demo-only: open a secondary surface for screenshots and smoke tests.
        if (name === "help") help.open()
        else if (name === "details") details.open()
        else if (name === "remove") removeSelected()
        else if (name === "notice") manager.notify("Studio Mac was added to your app launcher.")
        else if (name === "error") manager.notify("Disconnect this computer before removing it.", true)
    }
    readonly property bool dialogOpen: setup.opened || help.opened || details.opened || confirm.opened
    Timer { interval: 1000; repeat: true; running: root.connected || (!!root.selected && root.selected.next_retry > root.nowSeconds); onTriggered: root.nowSeconds = Date.now() / 1000 }
    Shortcut { sequence: "Ctrl+R"; onActivated: manager.refresh() }
    Shortcut { sequence: "Ctrl+N"; enabled: !root.dialogOpen && !manager.setupBusy; onActivated: setup.begin("") }
    Shortcut { sequence: "Ctrl+Return"; enabled: root.canAct && !root.dialogOpen; onActivated: root.action() }
    component Caption: Label { color: theme.colors.muted; font.pointSize: theme.type.caption; font.letterSpacing: 1.1; font.weight: Font.DemiBold }
    component Body: Label { textFormat: Text.PlainText; color: theme.colors.secondary; wrapMode: Text.WordWrap; lineHeight: 1.25 }
    component Divider: Rectangle { color: theme.colors.border; height: 1; Layout.fillWidth: true }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        // Header: identity on the left, global state and actions on the right.
        Rectangle {
            Layout.fillWidth: true; implicitHeight: 56; color: theme.colors.sidebar
            RowLayout {
                anchors.fill: parent; anchors.leftMargin: 20; anchors.rightMargin: 12; spacing: 10
                Rectangle { width: 30; height: 30; radius: 9; color: theme.colors.accent; ComputerGlyph { anchors.centerIn: parent; ink: theme.colors.onAccent; scale: .8 } }
                Label { text: "Remote Desktops"; color: theme.colors.text; font.pointSize: theme.type.lead; font.weight: Font.DemiBold }
                Rectangle {
                    visible: manager.demo; radius: 6; implicitHeight: 22; implicitWidth: previewLabel.implicitWidth + 16; color: theme.colors.selected; border.color: theme.colors.selectedBorder
                    Label { id: previewLabel; anchors.centerIn: parent; text: "Preview"; color: theme.colors.accentText; font.pointSize: theme.type.caption; font.weight: Font.DemiBold }
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    id: serviceChip
                    radius: 9; implicitHeight: 32; implicitWidth: chipRow.implicitWidth + 24
                    color: chipArea.containsMouse ? theme.colors.hover : "transparent"
                    Behavior on color { ColorAnimation { duration: 120 } }
                    readonly property string status: manager.demo ? "Preview service" : manager.serviceBusy ? "Starting service…" : manager.available ? "Service running" : "Service not responding"
                    Accessible.role: Accessible.Button
                    Accessible.name: status + ". Check again."
                    RowLayout {
                        id: chipRow; anchors.centerIn: parent; spacing: 8
                        Rectangle { width: 9; height: 9; radius: 4.5; color: manager.serviceBusy ? theme.colors.accent : manager.available ? theme.colors.success : theme.colors.warning; Behavior on color { ColorAnimation { duration: 200 } } }
                        Label { text: serviceChip.status; color: theme.colors.secondary; font.pointSize: theme.type.caption; font.weight: Font.Medium }
                    }
                    MouseArea { id: chipArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: manager.refresh() }
                    Tip { visible: chipArea.containsMouse; text: "The background service keeps desktops running after this window closes. Click to check again." }
                }
                IconButton { name: "refresh"; hint: "Refresh computers and status · Ctrl+R"; enabled: !manager.loading; onClicked: manager.refresh() }
                IconButton { name: "help"; hint: "Setup & help"; onClicked: help.open() }
            }
        }
        Divider {}
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 0
            // Sidebar: the computer list and the one primary global action.
            Rectangle {
                Layout.preferredWidth: root.width < 1000 ? 248 : 284
                Layout.fillHeight: true
                color: theme.colors.sidebar
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 14; anchors.topMargin: 18; spacing: 0
                    RowLayout {
                        Layout.leftMargin: 10; Layout.rightMargin: 6; spacing: 8
                        Caption { text: "COMPUTERS" }
                        Label { visible: root.entries.length > 0; text: root.entries.length; color: theme.colors.muted; font.pointSize: theme.type.caption }
                        Item { Layout.fillWidth: true }
                    }
                    ListView {
                        id: computerList
                        objectName: "computerList"
                        Layout.fillWidth: true; Layout.fillHeight: true; Layout.topMargin: 10
                        clip: true; spacing: 4; model: root.entries
                        activeFocusOnTab: true
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: Bar {}
                        currentIndex: { for (let i = 0; i < root.entries.length; ++i) if (root.entries[i].computer === root.selectedId) return i; return 0 }
                        Accessible.role: Accessible.List
                        Accessible.name: "Computers"
                        function select(i) {
                            if (i < 0 || i >= root.entries.length) return
                            root.selectedId = root.entries[i].computer
                            positionViewAtIndex(i, ListView.Contain)
                        }
                        Keys.onDownPressed: select(currentIndex + 1)
                        Keys.onUpPressed: select(currentIndex - 1)
                        Keys.onPressed: event => {
                            if (event.key === Qt.Key_Home) { select(0); event.accepted = true }
                            else if (event.key === Qt.Key_End) { select(root.entries.length - 1); event.accepted = true }
                            else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { root.action(); event.accepted = true }
                            else if (event.text.length === 1 && /\S/.test(event.text) && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier))) {
                                // Type-ahead: jump to the next computer whose name starts with the key.
                                const c = event.text.toLowerCase(), n = root.entries.length
                                for (let step = 1; step <= n; ++step) {
                                    const i = (currentIndex + step) % n
                                    if (((root.entries[i].name || root.entries[i].computer) + "").toLowerCase().startsWith(c)) { select(i); break }
                                }
                                event.accepted = true
                            }
                        }
                        delegate: ItemDelegate {
                            id: row
                            required property var modelData
                            required property int index
                            width: ListView.view.width - (ListView.view.contentHeight > ListView.view.height ? 14 : 0)
                            height: 60
                            hoverEnabled: true
                            focusPolicy: Qt.NoFocus
                            readonly property bool selected: root.selected && root.selected.computer === modelData.computer
                            readonly property string status: root.label(modelData.phase)
                            Accessible.name: (modelData.name || modelData.computer) + ", " + (modelData.stale ? "last known " : "") + status
                            onClicked: root.selectedId = modelData.computer
                            onDoubleClicked: { root.selectedId = modelData.computer; root.action() }
                            background: Rectangle {
                                radius: 10
                                color: row.selected ? theme.colors.selected : row.hovered ? theme.colors.hover : "transparent"
                                border.width: row.selected && computerList.activeFocus ? 2 : 1
                                border.color: row.selected && computerList.activeFocus ? theme.colors.accent : row.selected ? theme.colors.selectedBorder : "transparent"
                                Behavior on color { ColorAnimation { duration: 120 } }
                            }
                            contentItem: RowLayout {
                                spacing: 12
                                ComputerGlyph { Layout.leftMargin: 4; scale: .9; ink: row.selected ? theme.colors.accentText : theme.colors.muted; laptop: modelData.platform === "macos" || modelData.platform === "windows" }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 4
                                    Label { Layout.fillWidth: true; textFormat: Text.PlainText; text: modelData.name || modelData.computer; color: theme.colors.text; font.weight: Font.Medium; elide: Text.ElideRight }
                                    RowLayout {
                                        spacing: 7
                                        StatusDot { phase: modelData.phase; stale: !!modelData.stale; size: 8 }
                                        Label { Layout.fillWidth: true; text: row.status; color: modelData.stale ? theme.colors.muted : theme.colors.secondary; font.pointSize: theme.type.caption; elide: Text.ElideRight }
                                    }
                                }
                            }
                        }
                    }
                    Body { visible: !root.entries.length && !manager.loading; Layout.fillWidth: true; Layout.leftMargin: 10; Layout.topMargin: 6; text: "No computers yet. Add a computer you have paired in Moonlight."; font.pointSize: theme.type.caption }
                    Body { visible: manager.loading && !root.entries.length; Layout.fillWidth: true; Layout.leftMargin: 10; Layout.topMargin: 6; text: "Finding your computers…"; font.pointSize: theme.type.caption }
                    ActionButton { objectName: "addComputer"; Layout.fillWidth: true; Layout.topMargin: 14; primary: true; icon.source: "qrc:/qml/icons/plus.svg"; text: "Add computer"; hint: "Add a computer paired in Moonlight · Ctrl+N"; enabled: !manager.setupBusy; onClicked: setup.begin("") }
                    Body { visible: manager.demo; Layout.fillWidth: true; Layout.topMargin: 12; Layout.leftMargin: 4; text: "Sample computers. Every action is simulated."; color: theme.colors.muted; font.pointSize: theme.type.caption }
                }
            }
            Rectangle { Layout.fillHeight: true; width: 1; color: theme.colors.border }
            Item {
                id: mainPane
                Layout.fillWidth: true; Layout.fillHeight: true
                ScrollView {
                    id: scroller
                    anchors.fill: parent
                    contentWidth: availableWidth; contentHeight: page.implicitHeight
                    clip: true
                    ScrollBar.vertical: Bar { parent: scroller; x: scroller.width - width; y: 0; height: scroller.height }
                    ColumnLayout {
                        id: page
                        width: scroller.availableWidth
                        spacing: 0
                        // Empty state: warm, and the only place with a headline.
                        ColumnLayout {
                            visible: !root.selected && !manager.loading
                            Layout.fillWidth: true; Layout.margins: 36; Layout.topMargin: 72; spacing: 0
                            Rectangle { Layout.alignment: Qt.AlignHCenter; width: 68; height: 68; radius: 20; color: theme.colors.selected; border.color: theme.colors.selectedBorder; ComputerGlyph { anchors.centerIn: parent; scale: 1.4; ink: theme.colors.accentText } }
                            Label { Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 24; text: "Add your first computer"; color: theme.colors.text; font.pointSize: theme.type.subtitle; font.weight: Font.DemiBold }
                            Body { Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 8; Layout.maximumWidth: 440; horizontalAlignment: Text.AlignHCenter; text: "Pair a computer in Moonlight, then add it here to open its desktop in a window you can move like any other app." }
                            ActionButton { Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 26; primary: true; icon.source: "qrc:/qml/icons/plus.svg"; text: "Add computer"; enabled: !manager.setupBusy; onClicked: setup.begin("") }
                            ActionButton { Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 6; quiet: true; icon.source: "qrc:/qml/icons/external.svg"; text: "Open the setup guide"; onClicked: Qt.openUrlExternally("https://github.com/jdvmi00/remote-desktops/blob/develop/docs/BACKEND.md") }
                        }
                        ColumnLayout {
                            visible: manager.loading && !root.selected
                            Layout.fillWidth: true; Layout.margins: 36; Layout.topMargin: 72; spacing: 10
                            Label { Layout.alignment: Qt.AlignHCenter; text: "Finding your computers…"; color: theme.colors.secondary; font.pointSize: theme.type.lead }
                        }
                        // Selected computer.
                        ColumnLayout {
                            visible: !!root.selected
                            Layout.fillWidth: true; Layout.margins: 36; Layout.topMargin: 28; spacing: 0
                            Label { Layout.fillWidth: true; textFormat: Text.PlainText; text: root.selected ? root.selected.name || root.selected.computer : ""; color: theme.colors.text; font.pointSize: theme.type.title; font.weight: Font.DemiBold; font.letterSpacing: -.5; elide: Text.ElideRight }
                            RowLayout {
                                Layout.fillWidth: true; Layout.topMargin: 4; spacing: 8
                                Body { text: root.selected ? root.platformName(root.selected.platform) : "" }
                                Body { visible: !!(root.selected && root.selected.host); text: "·"; color: theme.colors.muted }
                                Body { Layout.fillWidth: true; visible: !!(root.selected && root.selected.host); text: root.selected ? root.selected.host || "" : ""; elide: Text.ElideRight }
                            }
                            // Service banner: one cause, one action.
                            Rectangle {
                                visible: (!manager.available && !manager.loading) || !!manager.error
                                Layout.fillWidth: true; Layout.topMargin: 22
                                implicitHeight: bannerColumn.implicitHeight + 32; radius: 12
                                color: theme.colors.warningBg; border.color: theme.colors.warningBorder
                                ColumnLayout {
                                    id: bannerColumn
                                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16; spacing: 8
                                    RowLayout {
                                        spacing: 10
                                        Icon { glyph: "alert"; color: theme.colors.warning }
                                        Label { Layout.fillWidth: true; text: manager.error ? "Computer settings could not be read" : "The background service is not responding"; color: theme.colors.warning; font.weight: Font.DemiBold; wrapMode: Text.WordWrap }
                                    }
                                    Body { Layout.fillWidth: true; text: manager.error || "Open desktop windows keep running. Start the service to see live status, or check again." }
                                    RowLayout {
                                        Layout.topMargin: 4; spacing: 8
                                        ActionButton { visible: !manager.available; text: manager.serviceBusy ? "Starting…" : "Start service"; icon.source: "qrc:/qml/icons/play.svg"; enabled: !manager.serviceBusy; hint: "Start the background service without connecting"; onClicked: manager.startService() }
                                        ActionButton { quiet: true; text: "Check again"; icon.source: "qrc:/qml/icons/refresh.svg"; onClicked: manager.refresh() }
                                    }
                                }
                            }
                            // Status card: state, meaning, and only real facts.
                            Rectangle {
                                id: card
                                Layout.fillWidth: true; Layout.topMargin: 22
                                implicitHeight: cardColumn.implicitHeight + 44; radius: 14
                                color: root.tone === "warning" ? theme.colors.warningBg : root.tone === "success" ? theme.colors.successBg : theme.colors.surface
                                border.color: root.tone === "warning" ? theme.colors.warningBorder : root.tone === "success" ? theme.colors.successBorder : theme.colors.border
                                Behavior on implicitHeight { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                Behavior on color { ColorAnimation { duration: 200 } }
                                Behavior on border.color { ColorAnimation { duration: 200 } }
                                Accessible.role: Accessible.StaticText
                                Accessible.name: root.headline + ". " + root.explanation
                                ColumnLayout {
                                    id: cardColumn
                                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 22; spacing: 12
                                    RowLayout {
                                        Layout.fillWidth: true; spacing: 12
                                        StatusDot { phase: root.phase; stale: root.stale; size: 12 }
                                        Label { Layout.fillWidth: true; text: root.headline; color: root.tone === "warning" ? theme.colors.warning : root.tone === "success" ? theme.colors.success : theme.colors.text; font.pointSize: theme.type.lead; font.weight: Font.DemiBold; elide: Text.ElideRight }
                                    }
                                    Body { Layout.fillWidth: true; text: root.explanation }
                                    RowLayout {
                                        visible: root.errorText.length > 0
                                        Layout.fillWidth: true; spacing: 10
                                        Icon { glyph: "alert"; size: 16; color: theme.colors.warning; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                                        Body { Layout.fillWidth: true; text: root.errorText; color: theme.colors.warning; font.pointSize: theme.type.caption }
                                    }
                                    // Indeterminate progress while a request or transition is in flight.
                                    Rectangle {
                                        id: progress
                                        visible: root.transitioning || !!(root.selected && root.selected.busy) || manager.serviceBusy
                                        Layout.fillWidth: true; Layout.topMargin: 4; height: 3; radius: 1.5; color: theme.colors.border; clip: true
                                        Accessible.role: Accessible.ProgressBar
                                        Accessible.name: "Operation in progress"
                                        Rectangle {
                                            width: parent.width * .3; height: parent.height; radius: 1.5; color: theme.colors.accent
                                            SequentialAnimation on x { running: progress.visible; loops: Animation.Infinite; NumberAnimation { from: -progress.width * .3; to: progress.width; duration: 1300; easing.type: Easing.InOutQuad } }
                                        }
                                    }
                                    GridLayout {
                                        visible: root.facts.length > 0
                                        Layout.fillWidth: true; Layout.topMargin: 6; columns: root.width < 1000 ? 2 : 3; columnSpacing: 24; rowSpacing: 12
                                        // The model is the count, so delegates survive value updates
                                        // instead of being rebuilt on every status tick.
                                        Repeater {
                                            model: root.facts.length
                                            delegate: ColumnLayout {
                                                required property int index
                                                readonly property var fact: root.facts[index] || ({label: "", value: ""})
                                                Layout.fillWidth: true; spacing: 2
                                                Caption { text: fact.label.toUpperCase() }
                                                Label { Layout.fillWidth: true; text: fact.value; color: theme.colors.text; font.weight: Font.Medium; elide: Text.ElideRight }
                                            }
                                        }
                                    }
                                }
                            }
                            // Actions. Cancel sits beside the primary action, never where Disconnect is.
                            RowLayout {
                                Layout.fillWidth: true; Layout.topMargin: 16; spacing: 10
                                ActionButton {
                                    objectName: "primaryAction"
                                    primary: true
                                    icon.source: "qrc:/qml/icons/" + (root.recovering ? "refresh" : root.connected ? "external" : "play") + ".svg"
                                    text: root.selected && root.selected.busy ? "Working…" : root.recovering ? "Restore display" : root.connected || root.phase === "running" ? "Open desktop" : root.transitioning ? root.label(root.phase) + "…" : "Connect"
                                    // A running client without an observed window cannot be focused from here.
                                    enabled: root.canAct && root.phase !== "running"
                                    hint: root.recovering ? "Retry restoring the host display · Ctrl+Enter" : root.phase === "running" ? "No window was detected; open Moonlight from your taskbar" : root.connected ? "Focus the desktop window · Ctrl+Enter" : "Open a desktop session · Ctrl+Enter"
                                    onClicked: root.action()
                                }
                                ActionButton { text: "Cancel"; visible: root.transitioning && !!root.selected && !!root.selected.desired; enabled: !!root.selected && !root.selected.busy; hint: "Stop connecting and restore the host"; onClicked: manager.act(root.selected.computer, "disconnect") }
                                ActionButton { text: "Reconnect"; icon.source: "qrc:/qml/icons/refresh.svg"; visible: root.connected || root.phase === "running"; enabled: !!root.selected && !root.selected.busy && manager.available && !root.transitioning; hint: "Restart the client; recovery settings are kept"; onClicked: manager.act(root.selected.computer, "reconnect") }
                                Item { Layout.fillWidth: true }
                                ActionButton { text: "Disconnect"; icon.source: "qrc:/qml/icons/power.svg"; destructive: true; visible: !!root.selected && !!root.selected.desired && !root.transitioning; enabled: !!root.selected && !root.selected.busy && manager.available; hint: "Close the desktop window and restore host settings"; onClicked: manager.act(root.selected.computer, "disconnect") }
                            }
                            RowLayout {
                                visible: !!root.selected && !root.selected.unconfigured && root.profiles.length > 0
                                Layout.fillWidth: true; Layout.topMargin: 20; spacing: 12
                                Caption { text: "PROFILE" }
                                Select {
                                    id: profileSelect
                                    visible: root.profiles.length > 1
                                    Layout.preferredWidth: Math.min(240, root.width / 4)
                                    model: root.profiles
                                    currentIndex: Math.max(0, root.profiles.indexOf(root.profile))
                                    enabled: !!root.selected && !root.selected.desired && !root.selected.busy && !root.recovering && !root.transitioning
                                    onActivated: root.chosenProfile = currentText
                                    Accessible.name: "Connection profile"
                                }
                                Label { visible: root.profiles.length === 1; text: root.profile; color: theme.colors.text; font.weight: Font.Medium }
                                Body { Layout.fillWidth: true; visible: root.profiles.length > 1 && !!root.selected && !!root.selected.desired; text: "Disconnect to change the profile."; font.pointSize: theme.type.caption; color: theme.colors.muted; elide: Text.ElideRight }
                            }
                            Divider { Layout.topMargin: 22 }
                            Flow {
                                visible: !!root.selected
                                Layout.fillWidth: true; Layout.topMargin: 8; spacing: 2
                                ActionButton { quiet: true; icon.source: "qrc:/qml/icons/pencil.svg"; text: "Edit"; visible: !!root.selected && !root.selected.unconfigured; enabled: !manager.setupBusy; hint: "Change the name, address, or stream quality"; onClicked: setup.begin(root.selected.computer) }
                                ActionButton { objectName: "launcherAction"; quiet: true; icon.source: "qrc:/qml/icons/grid.svg"; text: root.selected && root.selected.launcher_installed ? "Remove from app launcher" : "Add to app launcher"; visible: !!root.selected && !root.selected.unconfigured; enabled: !!root.selected && !root.selected.busy; hint: root.selected && root.selected.launcher_installed ? "Delete the desktop entry for this computer" : "Install a desktop entry that opens this computer directly"; onClicked: manager.act(root.selected.computer, root.selected.launcher_installed ? "launcher-remove" : "launcher") }
                                ActionButton { quiet: true; icon.source: "qrc:/qml/icons/info.svg"; text: "Details"; hint: "Identity, state, and technical messages"; onClicked: details.open() }
                                ActionButton { quiet: true; destructive: true; icon.source: "qrc:/qml/icons/trash.svg"; text: "Remove"; enabled: !!root.selected && !root.selected.busy && !root.selected.desired && !root.transitioning && !root.recovering; hint: "Remove this computer from Remote Desktops"; onClicked: root.removeSelected() }
                            }
                            Item { Layout.preferredHeight: 24 }
                        }
                    }
                }
                Toast {
                    anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 20
                    maxWidth: mainPane.width - 48
                    text: manager.notice; error: manager.noticeError
                    onDismissed: manager.clearNotice()
                }
            }
        }
    }
    SetupDialog { id: setup; onSaved: computer => { root.selectedId = computer; manager.refresh() } }
    Confirm { id: confirm }
    Sheet {
        id: help
        objectName: "helpDialog"
        title: "Setup & help"
        width: Math.min(root.width - 64, 560)
        Body { Layout.fillWidth: true; text: "Remote Desktops keeps your connections in a background service, so closing this window never disconnects a computer. Each desktop opens in its own Moonlight window that you can move and resize like any app." }
        Repeater {
            model: ["Pair the computer in Moonlight.", "Choose Add computer and pick it from the paired list.", "Check the connection, save, and connect."]
            delegate: RowLayout {
                required property string modelData
                required property int index
                Layout.fillWidth: true; spacing: 12
                Rectangle { width: 24; height: 24; radius: 12; color: theme.colors.selected; border.color: theme.colors.selectedBorder; Label { anchors.centerIn: parent; text: index + 1; color: theme.colors.accentText; font.pointSize: theme.type.caption; font.weight: Font.DemiBold } }
                Body { Layout.fillWidth: true; text: modelData; color: theme.colors.text }
            }
        }
        Divider {}
        GridLayout {
            Layout.fillWidth: true; columns: 2; columnSpacing: 18; rowSpacing: 6
            Repeater {
                model: ["Ctrl+Enter", "Connect or open the selected desktop", "Ctrl+N", "Add a computer", "Ctrl+R", "Refresh computers and status", "↑ ↓", "Choose a computer in the list", "Esc", "Close a dialog", "Ctrl+Alt+Shift+Z", "Toggle mouse and keyboard capture inside Moonlight"]
                delegate: Label {
                    required property string modelData
                    required property int index
                    Layout.fillWidth: index % 2 === 1
                    text: modelData; wrapMode: Text.WordWrap
                    color: index % 2 === 0 ? theme.colors.text : theme.colors.secondary
                    font.family: index % 2 === 0 ? "monospace" : root.font.family
                    font.pointSize: index % 2 === 0 ? theme.type.caption : theme.type.body
                }
            }
        }
        footer: Sheet.Footer {
            ActionButton { quiet: true; icon.source: "qrc:/qml/icons/external.svg"; text: "Setup guide"; onClicked: Qt.openUrlExternally("https://github.com/jdvmi00/remote-desktops/blob/develop/docs/BACKEND.md") }
            Item { Layout.fillWidth: true }
            ActionButton { text: "Close"; primary: true; onClicked: help.close() }
        }
    }
    Sheet {
        id: details
        title: "Connection details"
        subtitle: root.selected ? root.selected.name || root.selected.computer : ""
        width: Math.min(root.width - 64, 560)
        readonly property var rows: {
            if (!root.selected) return []
            const s = root.selected
            const r = [["Computer ID", s.computer], ["Profile", root.profile || "—"], ["State", root.label(root.phase) + (root.stale ? " (last known)" : "")],
                       ["Window", s.window ? "Detected (identity match)" : "Not detected"], ["Client", s.client_version && s.client_version !== "unknown" ? "Moonlight " + s.client_version : "—"]]
            if (s.pid) r.push(["Client process", String(s.pid)])
            r.push(["Launcher entry", s.launcher_installed ? "Installed" : "Not installed"])
            return r
        }
        readonly property string report: rows.map(r => r[0] + ": " + r[1]).join("\n") + "\n" + (root.selected ? root.selected.error || root.selected.recovery_error || "No errors reported." : "")
        GridLayout {
            Layout.fillWidth: true; columns: 2; columnSpacing: 18; rowSpacing: 6
            Repeater {
                model: details.rows.length * 2
                delegate: Label {
                    required property int index
                    readonly property var row: details.rows[Math.floor(index / 2)] || ["", ""]
                    Layout.fillWidth: index % 2 === 1
                    text: row[index % 2]; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
                    color: index % 2 === 0 ? theme.colors.muted : theme.colors.text
                    font.pointSize: index % 2 === 0 ? theme.type.caption : theme.type.body
                }
            }
        }
        Body { Layout.fillWidth: true; text: root.selected ? root.selected.error || root.selected.recovery_error || "No errors reported." : "No computer selected."; color: root.errorText ? theme.colors.warning : theme.colors.secondary }
        Body { Layout.fillWidth: true; text: "Window detection confirms an owned client window. It does not measure video latency, frame rate, or image quality."; font.pointSize: theme.type.caption; color: theme.colors.muted }
        footer: Sheet.Footer {
            ActionButton { quiet: true; icon.source: "qrc:/qml/icons/copy.svg"; text: "Copy details"; onClicked: { manager.copy(details.report); manager.notify("Details copied to the clipboard.") } }
            Item { Layout.fillWidth: true }
            ActionButton { text: "Close"; primary: true; onClicked: details.close() }
        }
    }
}
