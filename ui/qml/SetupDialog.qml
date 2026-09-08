import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Sheet {
    id: setup
    objectName: "setupDialog"
    width: Math.min(parent.width - 48, 700)
    height: Math.min(parent.height - 40, 700)
    // Escape and Cancel go through requestClose(), which asks before
    // discarding a draft. Nothing closes this dialog by accident.
    closePolicy: Popup.NoAutoClose
    onEscapeRequested: requestClose()
    title: editing ? "Computer settings" : pairing ? "Pair a computer" : "Add a computer"
    topPadding: 0
    property string editingComputer: ""
    property string discoveryWarning: ""
    property bool editing: false
    property int step: 0
    property var draft: ({})
    property var paired: []
    property var discovered: []
    property bool discovering: false
    property bool pairing: false
    property string pin: ""
    property var pairTarget: ({})
    property var inspection: null
    property string revision: ""
    property string error: ""
    property string errorAction: ""
    property bool tested: false
    property bool loaded: false
    property bool advanced: false
    property bool edited: false
    property bool attempted: false
    property var touched: ({})
    signal saved(string computer)
    signal keyboardRequested()
    readonly property var steps: editing ? ["Settings", "Check & save"] : ["Computer", "Settings", "Check & save"]
    readonly property int stepIndex: editing ? step - 1 : step
    readonly property bool dirty: editing ? edited : step > 0 || pairing
    readonly property bool conflict: error.indexOf("changed elsewhere") >= 0
    readonly property bool checking: manager.setupBusy && step === 2
    readonly property string platform: draft.platform || "unknown"
    readonly property var ssh: draft.ssh || ({})
    readonly property var display: draft.display || ({adapter: "external"})
    readonly property string adapter: display.adapter || "external"
    readonly property bool managed: adapter !== "external" && adapter !== "sunshine"
    readonly property bool recoverable: platform === "macos" || platform === "windows"
    readonly property string nameError: (draft.name || "").trim().length > 0 ? "" : "Enter a name for this computer."
    readonly property string hostError: /^[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$/.test(draft.host || "") ? "" : "Enter a hostname or IP address using letters, digits, dots, colons, or dashes."
    readonly property bool matchingConfigured: adapter === "virtual" && !!display.output && !!(ssh.alias || "")
    readonly property bool matchesMonitor: draft.stream_resolution === "monitor"
    readonly property bool fitsWindow: draft.stream_resolution === "auto"
    readonly property string resolutionError: fitsWindow || matchesMonitor || /^[0-9]{3,5}x[0-9]{3,5}$/.test(draft.stream_resolution || "") ? "" : "Use WIDTHxHEIGHT, for example 2560x1440."
    readonly property string sshUserError: !managed || platform !== "macos" ? "" : /^[A-Za-z_][A-Za-z0-9_-]{0,63}$/.test(ssh.user || "") ? "" : "Enter the Mac's approved SSH user (letters, digits, dashes, underscores)."
    readonly property string sshAliasError: !managed || platform !== "windows" || (adapter === "virtual" && !(ssh.alias || "").length) ? "" : /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(ssh.alias || "") ? "" : "Enter the SSH alias for this PC from your ~/.ssh/config."
    readonly property string displayError: adapter === "betterdisplay" && !(display.uuid && display.mode) ? "Inspect the host and choose a display and mode."
        : adapter === "virtual" && !matchingConfigured ? "Inspect the PC to select and verify Sunshine display matching, or use the existing host display."
        : adapter === "windows" && !display.device_id ? "Inspect the host and choose the capture display." : ""
    readonly property bool valid: loaded && !nameError && !hostError && !resolutionError && !sshUserError && !sshAliasError && !displayError
    readonly property var presets: [{label: "Balanced · 1080p, 60 fps", res: "1920x1080", bitrate: 30000}, {label: "Sharper · 1440p, 60 fps", res: "2560x1440", bitrate: 45000}, {label: "Detailed · 4K, 60 fps", res: "3840x2160", bitrate: 80000}, {label: "Custom", res: "", bitrate: 0}]
    readonly property var codecs: [{label: "Automatic", value: "auto"}, {label: "HEVC (H.265)", value: "HEVC"}, {label: "H.264", value: "H.264"}, {label: "AV1", value: "AV1"}]
    readonly property var inputs: [{label: "Direct pointer", value: "absolute", hint: "The pointer lands exactly where you point. Best for desktop work."}, {label: "Relative pointer", value: "relative", hint: "Sends movement only. Needed by games that capture the mouse."}]
    readonly property var keyboardPolicies: [
        {label: "Remote desktop while focused", value: "always"},
        {label: "Remote desktop only in fullscreen", value: "fullscreen"},
        {label: "Keep system shortcuts on this computer", value: "never"}]
    readonly property var audios: [{label: "Play here, mute when unfocused", value: "focus", hint: "Sound plays on this computer and mutes while the desktop window is not active."}, {label: "Always play here", value: "continuous", hint: "Sound plays on this computer even while the window is in the background."}, {label: "Play here and on the host", value: "host", hint: "Sound plays here even in the background, and host playback stays enabled."}]
    readonly property var adapters: platform === "macos"
        ? [{label: "Use existing host display", value: "external", hint: "Streams the existing desktop. Resizing the window scales the picture; this app does not change the host display."},
           {label: "Follow the main display", value: "macos", hint: "Keeps Sunshine capturing the Mac's main display through lid and monitor changes, over SSH. The display mode is never changed."},
           {label: "Manage a display with BetterDisplay", value: "betterdisplay", hint: "Switches a chosen display to a streaming mode and restores it afterwards. Needs BetterDisplay on the Mac."}]
        : platform === "windows"
        ? [{label: "Match via Sunshine (no SSH)", value: "sunshine", hint: "Requests the saved stream resolution from Sunshine. Enable display configuration and automatic resolution switching in Sunshine on the PC. Refit requests the window size. If the host cannot apply it, the image may be scaled or the connection may fail; host resolution is unverified."},
           {label: "Use existing host display", value: "external", hint: "Streams the existing desktop. Resizing the window scales the picture; this app does not change the host display."},
           {label: "Verified matching (SSH)", value: "virtual", hint: "Optional: Sunshine changes a selected physical or virtual display to the requested stream size and restores it afterwards. Read-only SSH checks confirm the capture display and resolution. Driver size management is separate and optional."},
           {label: "Managed with the console helper", value: "windows", hint: "A small helper on the PC switches to a virtual capture display for the session and restores the physical displays afterwards, even if this app is offline."}]
        : [{label: "Use existing host display", value: "external", hint: ""}]
    readonly property int presetIndex: {
        const i = ["1920x1080", "2560x1440", "3840x2160"].indexOf(draft.stream_resolution)
        return i >= 0 && draft.fps === 60 && draft.bitrate === presets[i].bitrate && (draft.codec || "auto") === "auto" ? i : 3
    }
    readonly property var displays: inspection && inspection.displays ? inspection.displays : []
    // Resolutions worth offering: what the inspected display can show first, then common sizes. Any WIDTHxHEIGHT can still be typed.
    readonly property var resolutions: {
        const doubled = r => r.split("x").map(v => Number(v) * 2).join("x")
        const offered = []
        if (adapter === "betterdisplay" && chosenDisplay) {
            for (const m of [display.mode].concat(chosenDisplay.modes || []).filter(Boolean)) { if (m.hidpi) offered.push(doubled(m.resolution)); offered.push(m.resolution) }
        } else if (adapter === "macos") {
            const main = displays.find(d => d.main) || displays[0]
            if (main && main.current) { if (main.current.hidpi) offered.push(doubled(main.current.resolution)); offered.push(main.current.resolution) }
        } else if (adapter === "windows" && chosenDisplay && chosenDisplay.width && chosenDisplay.height) offered.push(chosenDisplay.width + "x" + chosenDisplay.height)
        return offered.concat(["1920x1080", "2560x1440", "3440x1440", "3840x2160", "6144x2560"]).filter((r, i, all) => all.indexOf(r) === i)
    }
    readonly property var chosenDisplay: displays.find(d => (adapter === "betterdisplay" ? d.uuid === display.uuid : (d.id || "").toLowerCase() === (display.device_id || "").toLowerCase())) || null
    function fieldError(key, message) { return message.length > 0 && (attempted || touched[key] === true) ? message : "" }
    function valueLabel(list, value) { for (const item of list) if (item.value === value) return item.label; return value || "" }
    function modeLabel(m) { return m ? m.resolution + (m.hidpi ? " HiDPI" : "") + " · " + m.refresh + " Hz" : "" }
    function summary() { return (matchesMonitor ? "Full monitor resolution" : fitsWindow ? "Saved size with manual Refit" : draft.stream_resolution || "") + " · " + (draft.display_mode === "fullscreen" ? "Fullscreen" : "Windowed") + " · " + (draft.fps || 60) + " fps · " + Math.round((draft.bitrate || 0) / 1000) + " Mbit/s · " + valueLabel(codecs, draft.codec || "auto") + " codec" }
    function recoverySummary() {
        if (adapter === "sunshine") return "Match via Sunshine · host resolution unverified"
        if (adapter === "macos") return "Follows the main display over SSH as " + (ssh.user || "?")
        if (adapter === "betterdisplay") return "Manages " + (chosenDisplay ? chosenDisplay.name : "a display") + " · " + modeLabel(display.mode) + " as " + (ssh.user || "?")
        if (adapter === "windows") return "Console helper via " + (ssh.alias || "?") + " · capture " + (chosenDisplay ? chosenDisplay.name : display.device_id || "?")
        if (adapter === "virtual") return "Match selected Sunshine display · verified after connecting"
        return "Leaves the host display alone"
    }
    readonly property var summaryRows: [["Keyboard", valueLabel(keyboardPolicies, draft.system_keys || "never")], ["Name", draft.name || ""], ["Address", draft.host || ""], ["Operating system", ({macos: "macOS", windows: "Windows", linux: "Linux"})[draft.platform] || "Not specified"], ["Quality", summary()], ["Mouse", valueLabel(inputs, draft.input || "absolute")], ["Audio", valueLabel(audios, draft.audio || "focus")], ["Host display", recoverySummary()]]
    function begin(computer) {
        if (manager.setupBusy) return
        editingComputer = computer; discoveryWarning = ""
        editing = !!computer; step = editing ? 1 : 0; draft = {}; paired = []; discovered = []; inspection = null
        error = ""; errorAction = ""; tested = false; loaded = false; advanced = false; edited = false; attempted = false; touched = {}
        pairing = false; pin = ""; pairTarget = {}; discovering = !editing
        launcher.checked = !editing
        open()
        manager.setup(editing ? "get" : "catalog", computer ? {computer: computer} : {})
    }
    function requestClose() {
        if (manager.setupBusy) return
        if (discard.opened) { discard.close(); return }
        if (dirty) discard.ask("Discard changes?", editing ? "Your edits to this computer will not be saved." : "This computer will not be added. You can add it again at any time.", "Discard", function() { setup.close() })
        else close()
    }
    function inspectionSubject(value) {
        const d = value.display || {}
        return JSON.stringify([value.host, value.platform, value.ssh || {}, d.adapter, d.output, d.settings])
    }
    function set(key, value) {
        const previous = inspectionSubject(draft)
        const next = Object.assign({}, draft); next[key] = value
        if (previous !== inspectionSubject(next)) {
            inspection = null
            // A new host identity cannot inherit a display selected on the old host.
            if (key === "host" || key === "platform" || key === "ssh") {
                next.display = Object.assign({}, next.display || {})
                for (const field of ["uuid", "mode", "device_id", "output"]) delete next.display[field]
            }
        }
        draft = next
        const t = Object.assign({}, touched); t[key] = true; touched = t
        tested = false; error = ""; edited = true
    }
    function setNested(group, key, value) {
        const inner = Object.assign({}, draft[group] || {}); inner[key] = value
        set(group, inner)
    }
    function setAdapter(value) {
        const initial = display.initial_resolution || "1920x1080"
        const next = {adapter: value}
        if (value !== "external") { if (display.require_ac !== undefined) next.require_ac = display.require_ac }
        set("display", next)
        if (value !== "virtual" && fitsWindow) set("stream_resolution", initial)
    }
    function choose(host, platform) {
        const slug = host.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "computer"
        draft = {computer: slug + "-" + host.pairing_uuid.slice(0, 8), pairing_uuid: host.pairing_uuid,
            revision: revision, name: host.name, host: host.host, platform: platform || "unknown", profile: "desktop",
            stream_resolution: "1920x1080", fps: 60, bitrate: 30000, codec: "auto", input: "absolute", audio: "focus", system_keys: "always",
            ssh: {}, display: {adapter: platform === "windows" ? "sunshine" : "external"}}
        step = 1; pairing = false; tested = false; error = ""; attempted = false; touched = {}; inspection = null
    }
    function pickDiscovered(entry) {
        if (entry.pairing_uuid) {
            const known = paired.find(h => h.pairing_uuid === entry.pairing_uuid)
            if (known && !known.configured) choose(known, entry.platform)
            return
        }
        startPair({name: entry.name, host: entry.host, platform: entry.platform || "unknown"}, "")
    }
    function startPair(target, givenPin) {
        if (manager.setupBusy) return
        pairTarget = target; error = ""; errorAction = ""; pairing = true
        pin = givenPin || String(1000 + Math.floor(Math.random() * 9000))
        manager.setup("pair", {host: target.host, pin: pin})
    }
    function inspectHost() {
        if (manager.setupBusy) return
        error = ""
        manager.setup("inspect", {computer: draft.computer, pairing_uuid: draft.pairing_uuid, host: draft.host, platform: platform, ssh: ssh, adapter: adapter, display: display})
    }
    function installHelper() {
        if (manager.setupBusy || !inspection || !display.device_id) return
        error = ""
        manager.setup("install-helper", {computer: draft.computer, pairing_uuid: draft.pairing_uuid, host: draft.host, platform: platform, ssh: ssh, device_id: display.device_id})
    }
    function advance() {
        if (step !== 1) return
        if (!valid) { attempted = true; return }
        step = 2
        if (!tested) check()
    }
    function check() {
        if (manager.setupBusy) return
        tested = false; error = ""
        manager.setup("test", draft)
    }
    function reload() {
        error = ""
        if (editing) { loaded = false; tested = false; manager.setup("get", {computer: editingComputer}) }
        else manager.setup("catalog")
    }
    function retryRead() {
        if (manager.setupBusy) return
        const action = errorAction
        error = ""; errorAction = ""
        if (action === "get") manager.setup("get", {computer: editingComputer})
        else if (action === "discover") { discovering = true; discoveryWarning = ""; manager.setup("discover") }
        else { discovering = true; manager.setup("catalog") }
    }
    function reveal(item) {
        const flick = scroll.contentItem
        const p = item.mapToItem(flick.contentItem, 0, 0)
        if (p.y < flick.contentY) flick.contentY = p.y
        else if (p.y + item.height > flick.contentY + flick.height)
            flick.contentY = Math.min(flick.contentHeight - flick.height, p.y + item.height - flick.height)
    }
    Connections {
        target: manager
        function onSetupFinished(action, ok, result, message) {
            if (!setup.visible) return
            if (action === "discover") {
                setup.discovering = false
                if (ok) {
                    setup.discovered = result.candidates || []
                    setup.discoveryWarning = (result.warnings || []).join("\n")
                    setup.error = ""; setup.errorAction = ""
                } else { setup.error = message; setup.errorAction = action }
                return
            }
            if (!ok) { if (action === "catalog") setup.discovering = false; setup.error = message; setup.errorAction = action; return }
            setup.error = ""; setup.errorAction = ""
            if (action === "catalog") {
                setup.paired = result.paired; setup.revision = result.revision; setup.loaded = true
                if (setup.step > 0) { const next = Object.assign({}, setup.draft); next.revision = result.revision; setup.draft = next }
                else if (setup.discovering) manager.setup("discover")
            }
            if (action === "get") { setup.inspection = null; setup.draft = result; setup.loaded = true; setup.edited = false }
            if (action === "pair") {
                setup.revision = result.revision || setup.revision
                const p = result.paired
                setup.choose({name: p.name, host: p.host || setup.pairTarget.host, pairing_uuid: p.pairing_uuid}, setup.pairTarget.platform)
            }
            if (action === "inspect") {
                // Preselect the obvious candidate so the form reads as complete.
                const list = result.displays || []
                if (setup.adapter === "betterdisplay" && !setup.display.uuid) {
                    const d = list.find(x => x.uuid && x.main) || list.find(x => x.uuid)
                    if (d) { setup.setNested("display", "uuid", d.uuid); setup.setNested("display", "mode", d.current || (d.modes && d.modes.length ? d.modes[0] : null)) }
                }
                if (setup.adapter === "virtual" && result.virtual && result.virtual.sunshine_output) {
                    setup.setNested("display", "output", result.virtual.sunshine_output)
                }
                if (setup.adapter === "windows" && !setup.display.device_id) {
                    const d = list.find(x => x.available && !x.internal && !x.active) || list.find(x => x.available && !x.internal) || list[0]
                    if (d) setup.setNested("display", "device_id", d.id)
                }
                setup.inspection = result
                revealLater.start()
            }
            if (action === "install-helper") setup.inspectHost()
            if (action === "test") setup.tested = true
            if (action === "save") {
                const id = setup.draft.computer
                setup.close(); setup.saved(id)
                if (launcher.checked) manager.act(id, "launcher")
            }
        }
    }
    Confirm { id: discard; parent: Overlay.overlay }
    // Bring the freshly listed displays into view once an inspection lands.
    Timer { id: revealLater; interval: 60; onTriggered: setup.reveal(setup.adapter === "macos" ? mainDisplayInfo : setup.adapter === "virtual" ? matchingInfo : setup.platform === "windows" ? deviceChoice : displayChoice) }
    component Body: Label { textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.colors.secondary; lineHeight: 1.25 }
    component Section: Label { color: theme.colors.muted; font.pointSize: theme.type.caption; font.letterSpacing: 1.1; font.weight: Font.DemiBold }
    component FieldLabel: Label { color: theme.colors.text; font.pointSize: theme.type.caption; font.weight: Font.Medium }
    component Hint: Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.colors.muted; font.pointSize: theme.type.caption }
    component Problem: Label { Layout.fillWidth: true; visible: text.length > 0; wrapMode: Text.WordWrap; color: theme.colors.danger; font.pointSize: theme.type.caption; Accessible.role: Accessible.AlertMessage }
    component Progress: Rectangle {
        id: bar
        // Hidden pages keep their own visible flag, so the owner says when to animate.
        property bool active: true
        Layout.fillWidth: true; height: 3; radius: 1.5; color: theme.colors.border; clip: true
        Accessible.role: Accessible.ProgressBar
        Rectangle {
            width: parent.width * .3; height: parent.height; radius: 1.5; color: theme.colors.accent
            SequentialAnimation on x { running: bar.active; loops: Animation.Infinite; NumberAnimation { from: -bar.width * .3; to: bar.width; duration: 1300; easing.type: Easing.InOutQuad } }
        }
    }
    component Input: Field { onActiveFocusChanged: if (activeFocus) setup.reveal(this) }
    component Choice: Select { onActiveFocusChanged: if (activeFocus) setup.reveal(this) }
    component Pick: Combo { onActiveFocusChanged: if (activeFocus) setup.reveal(this) }
    component Card: Rectangle {
        default property alias content: cardColumn.data
        Layout.fillWidth: true; radius: 12; color: theme.colors.surface; border.color: theme.colors.border
        implicitHeight: cardColumn.implicitHeight + 32
        ColumnLayout { id: cardColumn; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16; spacing: 8 }
    }
    component Warning: Rectangle {
        default property alias content: warnColumn.data
        Layout.fillWidth: true; radius: 12; color: theme.colors.warningBg; border.color: theme.colors.warningBorder
        implicitHeight: warnColumn.implicitHeight + 32
        ColumnLayout { id: warnColumn; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16; spacing: 8 }
    }

    // Step indicator: done, current, and upcoming steps are visibly different.
    RowLayout {
        visible: !setup.pairing
        Layout.fillWidth: true; Layout.topMargin: 6; spacing: 0
        Repeater {
            model: setup.steps
            delegate: RowLayout {
                required property string modelData
                required property int index
                readonly property bool done: index < setup.stepIndex
                readonly property bool current: index === setup.stepIndex
                Layout.fillWidth: index < setup.steps.length - 1
                spacing: 8
                Rectangle {
                    width: 24; height: 24; radius: 12
                    color: done || current ? theme.colors.accent : "transparent"
                    border.width: 1.5; border.color: done || current ? theme.colors.accent : theme.colors.borderStrong
                    Behavior on color { ColorAnimation { duration: 160 } }
                    Icon { visible: done; anchors.centerIn: parent; glyph: "check"; size: 14; color: theme.colors.onAccent }
                    Label { visible: !done; anchors.centerIn: parent; text: index + 1; color: current ? theme.colors.onAccent : theme.colors.muted; font.pointSize: theme.type.caption; font.weight: Font.DemiBold }
                }
                Label { text: modelData; color: current ? theme.colors.text : done ? theme.colors.secondary : theme.colors.muted; font.weight: current ? Font.DemiBold : Font.Normal }
                Rectangle { visible: index < setup.steps.length - 1; Layout.fillWidth: true; Layout.leftMargin: 10; Layout.rightMargin: 10; height: 1; color: done ? theme.colors.accent : theme.colors.border }
            }
        }
    }
    ScrollView {
        id: scroll
        Layout.fillWidth: true; Layout.fillHeight: true
        contentWidth: availableWidth; contentHeight: pages.implicitHeight; clip: true
        ScrollBar.vertical: Bar { parent: scroll; x: scroll.width - width; y: 0; height: scroll.height }
        ColumnLayout {
            id: pages
            width: scroll.availableWidth; spacing: 16
            // Pairing page: the PIN and where to type it.
            ColumnLayout {
                visible: setup.pairing
                Layout.fillWidth: true; Layout.topMargin: 6; spacing: 14
                Body { text: "Pair with " + (setup.pairTarget.name || setup.pairTarget.host || ""); color: theme.colors.text; font.pointSize: theme.type.lead }
                Body { text: "Sunshine on " + (setup.pairTarget.host || "the host") + " is waiting for this PIN." }
                Rectangle {
                    Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 6
                    implicitWidth: pinLabel.implicitWidth + 48; implicitHeight: pinLabel.implicitHeight + 28; radius: 14
                    color: theme.colors.selected; border.color: theme.colors.selectedBorder
                    Label { id: pinLabel; objectName: "setupPin"; anchors.centerIn: parent; text: setup.pin.split("").join(" "); color: theme.colors.text; font.pointSize: theme.type.title; font.weight: Font.DemiBold; font.letterSpacing: 4; Accessible.name: "Pairing PIN " + setup.pin }
                }
                Repeater {
                    model: ["On " + (setup.pairTarget.name || "the host") + ", open Sunshine's web interface at https://" + (setup.pairTarget.host || "host") + ":47990/pin", "Sign in and enter the PIN shown above.", "Keep this window open. Pairing finishes on its own."]
                    delegate: RowLayout {
                        required property string modelData
                        required property int index
                        Layout.fillWidth: true; spacing: 12
                        Rectangle { width: 24; height: 24; radius: 12; color: theme.colors.selected; border.color: theme.colors.selectedBorder; Layout.alignment: Qt.AlignTop; Label { anchors.centerIn: parent; text: index + 1; color: theme.colors.accentText; font.pointSize: theme.type.caption; font.weight: Font.DemiBold } }
                        Body { text: modelData; color: theme.colors.text }
                    }
                }
                ColumnLayout {
                    visible: manager.setupBusy
                    Layout.fillWidth: true; spacing: 10
                    Body { text: "Waiting for the PIN to be entered on the host…" }
                    Progress { active: parent.visible }
                }
                Warning {
                    visible: setup.error.length > 0 && setup.errorAction === "pair"
                    RowLayout { spacing: 10; Icon { glyph: "alert"; color: theme.colors.warning } Label { Layout.fillWidth: true; text: "Pairing did not complete"; color: theme.colors.warning; font.weight: Font.DemiBold } }
                    Body { objectName: "pairError"; text: setup.error; color: theme.colors.warning }
                    RowLayout { Layout.topMargin: 4; spacing: 8
                        ActionButton { text: "Try again with a new PIN"; icon.source: "qrc:/qml/icons/refresh.svg"; enabled: !manager.setupBusy; onClicked: setup.startPair(setup.pairTarget, "") }
                    }
                }
                Hint { text: "Moonlight keeps the pairing and its certificates. Close the Moonlight window before pairing so it cannot overwrite the result." }
            }
            // Step: choose a paired computer or pair a new one.
            ColumnLayout {
                visible: setup.step === 0 && !setup.pairing
                Layout.fillWidth: true; spacing: 14
                Body { text: "Choose a computer."; color: theme.colors.text; font.pointSize: theme.type.lead }
                ColumnLayout {
                    visible: manager.setupBusy && !setup.loaded
                    Layout.fillWidth: true; spacing: 10
                    Body { text: "Looking for paired computers…" }
                    Progress { active: parent.visible }
                }
                Section { visible: setup.paired.length > 0; text: "PAIRED IN MOONLIGHT" }
                Repeater {
                    model: setup.paired
                    delegate: ItemDelegate {
                        id: candidate
                        required property var modelData
                        Layout.fillWidth: true; implicitHeight: 62
                        hoverEnabled: true
                        enabled: !modelData.configured && !manager.setupBusy
                        Accessible.name: modelData.name + (modelData.configured ? ", already added" : "")
                        onClicked: setup.choose(modelData, (setup.discovered.find(d => d.pairing_uuid === modelData.pairing_uuid) || {}).platform)
                        background: Rectangle {
                            radius: 10
                            color: !candidate.enabled ? theme.colors.disabled : candidate.hovered ? theme.colors.hover : theme.colors.surface
                            border.width: candidate.visualFocus ? 2 : 1
                            border.color: candidate.visualFocus ? theme.colors.accent : candidate.enabled ? theme.colors.border : "transparent"
                            Behavior on color { ColorAnimation { duration: 120 } }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            ComputerGlyph { ink: candidate.enabled ? theme.colors.secondary : theme.colors.disabledText }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 3
                                Label { textFormat: Text.PlainText; text: candidate.modelData.name; color: candidate.enabled ? theme.colors.text : theme.colors.disabledText; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                                Label { textFormat: Text.PlainText; text: candidate.modelData.configured ? "Already added. Edit it from your computer list." : candidate.modelData.host || "You will enter its address next"; color: candidate.enabled ? theme.colors.secondary : theme.colors.disabledText; font.pointSize: theme.type.caption; elide: Text.ElideRight; Layout.fillWidth: true }
                            }
                            Icon { visible: candidate.enabled; glyph: "chevron-right"; color: theme.colors.muted }
                        }
                    }
                }
                Section { visible: setup.loaded; Layout.topMargin: setup.paired.length > 0 ? 8 : 0; text: "PAIR A NEW COMPUTER" }
                Body { visible: setup.loaded; text: "Computers reachable through Tailscale and on your network. Pairing goes through Moonlight and stays there." }
                ColumnLayout {
                    visible: setup.discovering
                    Layout.fillWidth: true; spacing: 10
                    Body { text: "Looking on Tailscale and the local network…"; font.pointSize: theme.type.caption }
                    Progress { active: parent.visible }
                }
                Repeater {
                    model: setup.discovered.filter(d => !d.pairing_uuid || !d.configured)
                    delegate: ItemDelegate {
                        id: found
                        required property var modelData
                        readonly property bool alreadyPaired: !!modelData.pairing_uuid
                        Layout.fillWidth: true; implicitHeight: 62
                        hoverEnabled: true
                        enabled: !manager.setupBusy
                        Accessible.name: modelData.name + ", " + (found.alreadyPaired ? "paired" : modelData.online ? "online" : "offline")
                        onClicked: setup.pickDiscovered(modelData)
                        background: Rectangle {
                            radius: 10
                            color: found.hovered ? theme.colors.hover : theme.colors.surface
                            border.width: found.visualFocus ? 2 : 1
                            border.color: found.visualFocus ? theme.colors.accent : theme.colors.border
                            Behavior on color { ColorAnimation { duration: 120 } }
                        }
                        contentItem: RowLayout {
                            spacing: 14
                            ComputerGlyph { laptop: found.modelData.platform === "macos" || found.modelData.platform === "windows"; ink: theme.colors.secondary }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 3
                                RowLayout {
                                    spacing: 8
                                    Label { textFormat: Text.PlainText; text: found.modelData.name; color: theme.colors.text; font.weight: Font.DemiBold; elide: Text.ElideRight }
                                    Rectangle { radius: 5; implicitHeight: 18; implicitWidth: sourceLabel.implicitWidth + 12; color: theme.colors.selected; Label { id: sourceLabel; anchors.centerIn: parent; text: found.modelData.source === "tailscale" ? "Tailscale" : "Local network"; color: theme.colors.accentText; font.pointSize: theme.type.caption } }
                                }
                                RowLayout {
                                    spacing: 7
                                    Rectangle { width: 8; height: 8; radius: 4; color: found.modelData.online ? theme.colors.success : "transparent"; border.width: found.modelData.online ? 0 : 1.5; border.color: theme.colors.muted }
                                    Label { textFormat: Text.PlainText; Layout.fillWidth: true; text: (found.modelData.online ? "Online" : "Offline") + " · " + found.modelData.host + (found.modelData.platform ? " · " + ({macos: "macOS", windows: "Windows", linux: "Linux"})[found.modelData.platform] : ""); color: theme.colors.secondary; font.pointSize: theme.type.caption; elide: Text.ElideRight }
                                }
                            }
                            Label { text: found.alreadyPaired ? "Paired" : "Pair"; color: found.alreadyPaired ? theme.colors.success : theme.colors.accentText; font.weight: Font.Medium }
                            Icon { glyph: "chevron-right"; color: theme.colors.muted }
                        }
                    }
                }
                Body { visible: setup.loaded && !setup.discovering && !setup.discovered.length && setup.errorAction !== "discover" && !setup.discoveryWarning; text: "Nothing was found. Enter the computer's address below." ; font.pointSize: theme.type.caption }
                RowLayout {
                    visible: setup.loaded
                    Layout.fillWidth: true; spacing: 8
                    Input { id: manualHost; objectName: "setupManualHost"; Layout.fillWidth: true; placeholderText: "Hostname, Tailscale name, or IP address"; maximumLength: 253; Accessible.name: "Computer address"; onAccepted: if (manualPair.enabled) manualPair.clicked() }
                    ActionButton { id: manualPair; text: "Pair"; icon.source: "qrc:/qml/icons/play.svg"; enabled: !manager.setupBusy && /^[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$/.test(manualHost.text); onClicked: setup.startPair({name: manualHost.text, host: manualHost.text, platform: "unknown"}, "") }
                }
                Hint { visible: setup.loaded; text: "The host needs Sunshine running. Tailscale names, local names, and IP addresses all work." }
            }
            Hint { text: setup.discoveryWarning; visible: setup.step === 0 && setup.discoveryWarning.length > 0; color: theme.colors.warning }
            // Step: name, address, quality, and display recovery.
            ColumnLayout {
                visible: setup.step === 1 && setup.loaded
                enabled: !manager.setupBusy
                Layout.fillWidth: true; spacing: 8
                Body { text: setup.editing ? "Change how this computer connects." : "A few details, then a quick check."; color: theme.colors.text; font.pointSize: theme.type.lead; Layout.bottomMargin: 6 }
                FieldLabel { text: "Keyboard shortcuts" }
                Choice {
                    objectName: "keyboardPolicy"
                    Layout.fillWidth: true; model: setup.keyboardPolicies; textRole: "label"; valueRole: "value"
                    currentIndex: Math.max(0, ["always", "fullscreen", "never"].indexOf(setup.draft.system_keys || "never"))
                    Accessible.name: "Where system keyboard shortcuts go"
                    onActivated: setup.set("system_keys", currentValue)
                }
                Hint {
                    text: (setup.draft.system_keys || "never") === "never"
                        ? "Super+Space and other system shortcuts stay here, even when this remote desktop has focus."
                        : "Super+Space and other system shortcuts control the remote desktop" + (setup.draft.system_keys === "fullscreen" ? " in fullscreen." : " while focused.")
                }
                RowLayout {
                    Layout.fillWidth: true
                    Hint { Layout.fillWidth: true; text: manager.keyboard.enabled ? "For a local command: " + manager.keyboard.prefix + ", then your usual shortcut." : "Enable a local-command prefix to arrange the remote tile without giving up remote shortcuts." }
                    ActionButton { quiet: true; text: "Configure prefix…"; onClicked: setup.keyboardRequested() }
                }
                Hint { text: "Ctrl+Alt+Shift+Z releases Moonlight capture. Keyboard changes apply after Disconnect, then Connect; Reconnect keeps the current session settings."; Layout.bottomMargin: 12 }
                FieldLabel { text: "Computer name" }
                Input { objectName: "setupName"; Layout.fillWidth: true; text: setup.draft.name || ""; maximumLength: 100; invalid: setup.fieldError("name", setup.nameError).length > 0; Accessible.name: "Computer name"; onTextEdited: setup.set("name", text) }
                Problem { text: setup.fieldError("name", setup.nameError) }
                FieldLabel { Layout.topMargin: 8; text: "Address" }
                Input { Layout.fillWidth: true; text: setup.draft.host || ""; placeholderText: "Hostname or IP address"; maximumLength: 253; invalid: setup.fieldError("host", setup.hostError).length > 0; Accessible.name: "Computer address"; onTextEdited: setup.set("host", text) }
                Problem { text: setup.fieldError("host", setup.hostError) }
                Hint { text: "Used to check reachability. Moonlight's saved address is used for the stream itself." }
                RowLayout {
                    Layout.fillWidth: true; Layout.topMargin: 8; spacing: 16
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 8
                        FieldLabel { text: "Operating system" }
                        Choice { objectName: "setupPlatform"; Layout.fillWidth: true; model: [{label: "Not specified", value: "unknown"}, {label: "macOS", value: "macos"}, {label: "Windows", value: "windows"}, {label: "Linux", value: "linux"}]; textRole: "label"; valueRole: "value"; currentIndex: Math.max(0, ["unknown", "macos", "windows", "linux"].indexOf(setup.draft.platform)); Accessible.name: "Operating system"; onActivated: { setup.set("platform", currentValue); setup.setAdapter(currentValue === "windows" ? "sunshine" : "external") } }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 8
                        FieldLabel { text: setup.editing ? "Default profile" : "Desktop quality" }
                        Choice {
                            Layout.fillWidth: true
                            model: setup.editing ? Object.keys(setup.draft.profiles || {}) : setup.presets
                            textRole: setup.editing ? "" : "label"
                            currentIndex: setup.editing ? Math.max(0, model.indexOf(setup.draft.profile)) : setup.presetIndex
                            Accessible.name: setup.editing ? "Default profile" : "Desktop quality"
                            onActivated: {
                                if (setup.editing) {
                                    const p = setup.draft.profiles[currentText]
                                    setup.set("profile", currentText)
                                    for (const key of ["stream_resolution", "fps", "bitrate", "codec", "input", "audio", "display_mode", "system_keys"])
                                        setup.set(key, p[key] === undefined ? ({fps: 60, bitrate: 60000, codec: "HEVC", input: "absolute", audio: "focus", display_mode: "windowed", system_keys: "never"})[key] : p[key])
                                    setup.set("display", p.display || {adapter: "external"})
                                } else if (currentIndex === 3) setup.advanced = true
                                else {
                                    setup.set("fps", 60); setup.set("codec", "auto")
                                    setup.set("stream_resolution", setup.presets[currentIndex].res)
                                    setup.set("bitrate", setup.presets[currentIndex].bitrate)
                                }
                            }
                        }
                    }
                }
                // Display recovery: only for platforms with a managed adapter.
                Section { visible: setup.recoverable; Layout.topMargin: 14; text: "HOST DISPLAY (OPTIONAL)" }
                Choice { objectName: "setupAdapter"; visible: setup.recoverable; Layout.fillWidth: true; model: setup.adapters; textRole: "label"; valueRole: "value"; currentIndex: Math.max(0, setup.adapters.map(a => a.value).indexOf(setup.adapter)); Accessible.name: "Host display"; onActivated: setup.setAdapter(currentValue) }
                Hint { visible: setup.recoverable; text: setup.valueLabel(setup.adapters.map(a => ({label: a.hint, value: a.value})), setup.adapter) }
                ColumnLayout {
                    visible: setup.recoverable && setup.managed
                    Layout.fillWidth: true; spacing: 8
                    FieldLabel { Layout.topMargin: 6; text: "SSH connection" }
                    Input { objectName: "setupSshUser"; visible: setup.platform === "macos"; Layout.fillWidth: true; text: setup.ssh.user || ""; placeholderText: "User on the host with key-based SSH access"; maximumLength: 64; invalid: setup.fieldError("ssh", setup.sshUserError).length > 0; Accessible.name: "SSH user"; onTextEdited: setup.setNested("ssh", "user", text) }
                    Input { objectName: "setupSshAlias"; visible: setup.platform === "windows"; Layout.fillWidth: true; text: setup.ssh.alias || ""; placeholderText: "A Host entry in ~/.ssh/config with key access"; maximumLength: 64; invalid: setup.fieldError("ssh", setup.sshAliasError).length > 0; Accessible.name: "SSH alias"; onTextEdited: setup.setNested("ssh", "alias", text) }
                    Problem { text: setup.fieldError("ssh", setup.sshUserError || setup.sshAliasError) }
                    Hint { text: "Uses your existing SSH keys and known hosts. No password is stored. Inspection reads host settings without changing them." }
                    Hint { visible: setup.platform === "macos"; text: "Enter the SSH user on the Mac. The connection uses the computer address above." }
                    Hint { visible: setup.platform === "windows"; text: "Enter the SSH alias for the PC from ~/.ssh/config." }
                    Hint { visible: setup.adapter === "windows"; text: "The alias must reach an administrator account on the PC over OpenSSH. Sunshine must already capture a virtual display, named in its output_name setting." }
                    Hint { visible: setup.adapter === "virtual"; text: "SSH verifies the selected display and its captured resolution. Refit stays disabled until a connection is verified." }
                    Check { visible: setup.platform === "macos"; text: "Require AC power before streaming"; checked: !!setup.display.require_ac; onToggled: setup.setNested("display", "require_ac", checked) }
                    RowLayout {
                        Layout.topMargin: 4; spacing: 8
                        ActionButton { objectName: "setupInspect"; text: setup.inspection ? "Inspect again" : "Inspect host"; icon.source: "qrc:/qml/icons/monitor.svg"; enabled: !manager.setupBusy && !setup.sshUserError && !setup.sshAliasError && (setup.adapter !== "virtual" || (setup.ssh.alias || "").length > 0); onClicked: setup.inspectHost() }
                        ActionButton { objectName: "setupInstall"; visible: setup.adapter === "windows" && !!(setup.inspection && setup.inspection.helper && !setup.inspection.helper.installed); text: "Install the helper"; icon.source: "qrc:/qml/icons/play.svg"; enabled: !manager.setupBusy && !!setup.inspection && !!setup.display.device_id; hint: "Installs the recovery helper on the PC over SSH; needs an administrator account"; onClicked: setup.installHelper() }
                    }
                    Hint { visible: !setup.inspection && !setup.attempted; text: "Inspect the host to read its display settings before continuing." }
                    Problem { text: setup.attempted ? setup.displayError : "" }
                    ColumnLayout {
                        id: mainDisplayInfo
                        visible: setup.adapter === "macos" && !!setup.inspection
                        Layout.fillWidth: true; spacing: 8
                        readonly property var mainDisplay: setup.displays.find(d => d.main) || null
                        Hint { text: "Main display: " + (mainDisplayInfo.mainDisplay ? mainDisplayInfo.mainDisplay.name + " · " + setup.modeLabel(mainDisplayInfo.mainDisplay.current) : "Not reported by the host") }
                        Hint { text: "Follows the main display through lid and monitor changes. The host display mode stays unchanged." }
                    }
                    ColumnLayout {
                        visible: setup.adapter === "betterdisplay"
                        Layout.fillWidth: true; spacing: 8
                        ColumnLayout {
                            visible: setup.inspection && setup.inspection.platform === "macos"
                            Layout.fillWidth: true; spacing: 8
                            Hint { visible: setup.inspection && setup.inspection.betterdisplay === false; text: "BetterDisplay was not found on the Mac; install it to manage a display mode."; color: theme.colors.warning }
                            FieldLabel { text: "Display to manage" }
                            Choice {
                                id: displayChoice
                                objectName: "setupDisplay"
                                Layout.fillWidth: true
                                model: setup.displays.filter(d => d.uuid)
                                textRole: "name"
                                currentIndex: Math.max(0, setup.displays.filter(d => d.uuid).map(d => d.uuid).indexOf(setup.display.uuid))
                                Accessible.name: "Display to manage"
                                onActivated: { const d = setup.displays.filter(d => d.uuid)[currentIndex]; setup.setNested("display", "uuid", d.uuid); setup.setNested("display", "mode", d.current || (d.modes.length ? d.modes[0] : null)) }
                            }
                            FieldLabel { text: "Streaming mode" }
                            Choice {
                                Layout.fillWidth: true
                                readonly property var modes: setup.chosenDisplay && setup.chosenDisplay.modes ? setup.chosenDisplay.modes : []
                                model: modes.map(m => ({label: setup.modeLabel(m), mode: m}))
                                textRole: "label"
                                currentIndex: Math.max(0, modes.map(m => setup.modeLabel(m)).indexOf(setup.modeLabel(setup.display.mode)))
                                Accessible.name: "Streaming mode"
                                onActivated: setup.setNested("display", "mode", model[currentIndex].mode)
                            }
                            Check { text: "Follow the main display if it changes"; checked: !!setup.display.follow_main; onToggled: setup.setNested("display", "follow_main", checked) }
                            Hint { text: "The chosen mode is applied when a session starts and the original mode is restored when it ends. A manual change on the Mac is never overwritten." }
                        }
                    }
                    ColumnLayout {
                        id: matchingInfo
                        visible: setup.adapter === "virtual" && !!(setup.inspection && setup.inspection.virtual)
                        Layout.fillWidth: true; spacing: 8
                        readonly property var virt: setup.inspection && setup.inspection.virtual ? setup.inspection.virtual : ({})
                        Hint { text: "Selected Sunshine display: " + (setup.display.output || "Not selected") }
                        Check { text: "Manage Virtual Display Driver sizes over SSH"; checked: !!setup.display.sync_modes; onToggled: setup.setNested("display", "sync_modes", checked) }
                        Hint { text: "Enable size management only for the supported Virtual Display Driver. It edits its mode list and reloads it before connecting. Leave it off for physical monitors or host-managed sizes." }
                        Hint { text: "Sunshine resolution option: " + (parent.virt.dd_resolution_option || "unset") + " · Driver sizes: " + ((parent.virt.modes || []).join(", ") || "none") + (parent.virt.driver_pipe ? " · driver reloads on demand" : " · driver control pipe not found") }
                        Hint { visible: parent.virt.dd_resolution_option !== "auto"; color: theme.colors.warning; text: "Set dd_resolution_option = auto in Sunshine's configuration and restart Sunshine, so the virtual display takes the stream's size." }
                        Hint { visible: parent.virt.settings_present === false; color: theme.colors.warning; text: "The driver's settings file was not found at " + (parent.virt.settings || "") + "." }
                    }
                    ColumnLayout {
                        visible: setup.adapter === "windows" && setup.inspection && setup.inspection.platform === "windows"
                        Layout.fillWidth: true; spacing: 8
                        Hint { text: "Sunshine output: " + (setup.inspection && setup.inspection.sunshine_output ? setup.inspection.sunshine_output : "not set") + " · Helper: " + (setup.inspection && setup.inspection.helper && setup.inspection.helper.installed ? "installed" + (setup.inspection.helper.fresh === false ? " (not running)" : "") : "not installed") }
                        Hint { visible: !!(setup.inspection && !setup.inspection.sunshine_output); text: "Set output_name in Sunshine's configuration to the virtual display before installing the helper."; color: theme.colors.warning }
                        FieldLabel { text: "Capture display for streaming" }
                        Choice {
                            id: deviceChoice
                            objectName: "setupDevice"
                            Layout.fillWidth: true
                            model: setup.displays.map(d => ({label: d.name + (d.hardware ? " · " + d.hardware : "") + (d.internal ? " · built-in" : "") + (d.active ? " · active" : ""), id: d.id}))
                            textRole: "label"
                            currentIndex: Math.max(0, setup.displays.map(d => (d.id || "").toLowerCase()).indexOf((setup.display.device_id || "").toLowerCase()))
                            Accessible.name: "Capture display"
                            onActivated: setup.setNested("display", "device_id", model[currentIndex].id)
                        }
                        Hint { text: "Choose the virtual display Sunshine captures, not a physical panel. During a session only that display stays active; the helper restores the others afterwards." }
                    }
                }
                Check {
                    objectName: "setupFullscreen"
                    text: "Open in true fullscreen"
                    checked: setup.draft.display_mode === "fullscreen"
                    onToggled: setup.set("display_mode", checked ? "fullscreen" : "windowed")
                }
                Check {
                    objectName: "setupMatchMonitor"
                    text: "Use full monitor resolution"
                    checked: setup.matchesMonitor
                    onToggled: {
                        if (checked && !setup.fitsWindow && !setup.matchesMonitor)
                            setup.setNested("display", "initial_resolution", setup.draft.stream_resolution || "1920x1080")
                        setup.set("stream_resolution", checked ? "monitor" : setup.display.initial_resolution || "1920x1080")
                    }
                }
                Hint {
                    text: "For a sharp fullscreen picture, enable both options. Connect requests the full pixel size of the monitor you launch from, including space normally used by bars and borders. The host display must support and match that size."
                }
                ActionButton {
                    Layout.topMargin: 10; quiet: true
                    icon.source: "qrc:/qml/icons/" + (setup.advanced ? "chevron-down" : "chevron-right") + ".svg"
                    text: "Advanced stream settings"
                    onClicked: setup.advanced = !setup.advanced
                    Accessible.name: (setup.advanced ? "Hide" : "Show") + " advanced stream settings"
                }
                GridLayout {
                    visible: setup.advanced
                    Layout.fillWidth: true; columns: 2; columnSpacing: 16; rowSpacing: 8
                    FieldLabel { text: "Resolution" }
                    FieldLabel { text: "Frame rate" }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 6
                        Pick {
                            objectName: "setupResolution"
                            Layout.fillWidth: true
                            model: setup.resolutions
                            enabled: !setup.fitsWindow && !setup.matchesMonitor
                            value: setup.fitsWindow || setup.matchesMonitor ? "" : setup.draft.stream_resolution || ""
                            placeholder: setup.matchesMonitor ? "Full monitor resolution" : setup.fitsWindow ? "Last saved stream size" : ""
                            validator: RegularExpressionValidator { regularExpression: /[0-9]{0,5}x?[0-9]{0,5}/ }
                            invalid: setup.fieldError("stream_resolution", setup.resolutionError).length > 0
                            Accessible.name: "Stream resolution"
                            onEdited: function(text) { setup.set("stream_resolution", text) }
                        }
                        Check {
                            objectName: "setupFitWindow"
                            visible: setup.adapter === "virtual"
                            text: "Enable manual Refit"
                            checked: setup.fitsWindow
                            enabled: setup.matchingConfigured
                            Accessible.name: "Size the stream to the window"
                            onToggled: {
                                if (checked && !setup.matchingConfigured) { checked = false; return }
                                if (checked && !setup.fitsWindow) setup.setNested("display", "initial_resolution", setup.draft.stream_resolution || "1920x1080")
                                setup.set("stream_resolution", checked ? "auto" : setup.display.initial_resolution || "1920x1080")
                            }
                        }
                        Hint { visible: setup.adapter === "sunshine" && !setup.matchesMonitor; text: "Connect uses the saved size. Refit requests the current window size and remembers it. The host resolution remains unverified without SSH." }
                        Hint { visible: setup.adapter !== "sunshine" && !setup.matchingConfigured; text: setup.platform === "windows" ? "Window resizing scales the picture. To change the host resolution, choose a Sunshine matching mode above." : "Window resizing scales the picture. Stream resolution controls video size; it does not change the host display mode." }
                        Hint { visible: setup.fitsWindow; text: "Each connection opens at the size last used here. Press Refit in the connection view to match the current window; that size is then remembered for next time." }
                        Problem { text: setup.fieldError("stream_resolution", setup.resolutionError) }
                    }
                    Spin { onActiveFocusChanged: if (activeFocus) setup.reveal(this); Layout.fillWidth: true; Layout.alignment: Qt.AlignTop; from: 20; to: 240; value: setup.draft.fps || 60; Accessible.name: "Frames per second"; onValueModified: setup.set("fps", value) }
                    FieldLabel { text: "Bitrate (Mbit/s)" }
                    FieldLabel { text: "Codec" }
                    Spin { onActiveFocusChanged: if (activeFocus) setup.reveal(this); Layout.fillWidth: true; from: 1; to: 200; value: Math.round((setup.draft.bitrate || 30000) / 1000); Accessible.name: "Bitrate in megabits per second"; onValueModified: setup.set("bitrate", value * 1000) }
                    Choice { Layout.fillWidth: true; model: setup.codecs; textRole: "label"; valueRole: "value"; currentIndex: Math.max(0, setup.codecs.map(c => c.value).indexOf(setup.draft.codec || "auto")); Accessible.name: "Codec"; onActivated: setup.set("codec", currentValue) }
                    FieldLabel { text: "Mouse" }
                    FieldLabel { text: "Audio" }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 6
                        Choice { id: inputChoice; Layout.fillWidth: true; model: setup.inputs; textRole: "label"; valueRole: "value"; currentIndex: Math.max(0, setup.inputs.map(c => c.value).indexOf(setup.draft.input || "absolute")); Accessible.name: "Mouse mode"; onActivated: setup.set("input", currentValue) }
                        Hint { text: setup.inputs[inputChoice.currentIndex].hint }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 6
                        Choice { id: audioChoice; Layout.fillWidth: true; model: setup.audios; textRole: "label"; valueRole: "value"; currentIndex: Math.max(0, setup.audios.map(c => c.value).indexOf(setup.draft.audio || "focus")); Accessible.name: "Audio"; onActivated: setup.set("audio", currentValue) }
                        Hint { text: setup.audios[audioChoice.currentIndex].hint }
                    }
                    FieldLabel { visible: setup.managed && setup.platform === "macos"; text: "SSH control socket (optional)" }
                    Item { visible: setup.managed && setup.platform === "macos" }
                    Input { visible: setup.managed && setup.platform === "macos"; Layout.fillWidth: true; Layout.columnSpan: 2; text: setup.ssh.control_path || ""; placeholderText: "/path/to/ssh-control-socket"; Accessible.name: "SSH control socket path"; onTextEdited: setup.setNested("ssh", "control_path", text) }
                }
                Hint { Layout.topMargin: 8; text: setup.editing ? "Changes apply after disconnecting and starting a new connection." : "You can tune stream quality and recovery later from Edit." }
            }
            ColumnLayout {
                objectName: "setupLoadingSettings"
                visible: setup.step === 1 && !setup.loaded && manager.setupBusy
                Layout.fillWidth: true; spacing: 10
                Body { text: "Loading settings…" }
                Progress { active: parent.visible }
            }
            // Step: check and save.
            ColumnLayout {
                visible: setup.step === 2
                Layout.fillWidth: true; spacing: 16
                Body { text: setup.tested ? (setup.editing ? "Your changes are ready to save." : "Ready to add this computer.") : setup.checking ? "Checking the connection…" : "Checking the connection"; color: theme.colors.text; font.pointSize: theme.type.lead }
                Card {
                    GridLayout {
                        Layout.fillWidth: true; columns: 2; columnSpacing: 20; rowSpacing: 8
                        // Fixed count: values update in place rather than rebuilding delegates.
                        Repeater {
                            model: setup.summaryRows.length * 2
                            delegate: Label {
                                required property int index
                                readonly property var row: setup.summaryRows[Math.floor(index / 2)] || ["", ""]
                                Layout.fillWidth: index % 2 === 1
                                text: row[index % 2]; textFormat: Text.PlainText; wrapMode: Text.WordWrap
                                color: index % 2 === 0 ? theme.colors.muted : theme.colors.text
                                font.pointSize: index % 2 === 0 ? theme.type.caption : theme.type.body
                            }
                        }
                    }
                }
                ColumnLayout {
                    visible: setup.checking
                    Layout.fillWidth: true; spacing: 10
                    Body { text: setup.managed ? "Checking reachability, Moonlight pairing, the Desktop app, and the display over SSH. Nothing on the host is changed." : "Checking reachability, Moonlight pairing, and the Desktop app. This does not start a stream or change the host display." }
                    Progress { active: parent.visible }
                }
                RowLayout {
                    visible: setup.tested && !setup.checking
                    Layout.fillWidth: true; spacing: 10
                    Icon { glyph: "check"; color: theme.colors.success; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 4
                        Label { text: setup.managed ? "Connection and display checks passed" : "Connection check passed"; color: theme.colors.success; font.weight: Font.DemiBold }
                        Body { text: manager.demo ? "Simulated check. No real computer was contacted." : (setup.managed ? "Moonlight authenticated, the Desktop app is listed, and the host answered over SSH. " : "Moonlight authenticated and found the Desktop app. ") + "Video and input are verified when you connect." }
                    }
                }
                Warning {
                    visible: setup.error.length > 0 && setup.step === 2
                    RowLayout {
                        spacing: 10
                        Icon { glyph: "alert"; color: theme.colors.warning }
                        Label { Layout.fillWidth: true; text: setup.conflict ? "Settings changed elsewhere" : setup.errorAction === "save" ? "The computer could not be saved" : "The connection check failed"; color: theme.colors.warning; font.weight: Font.DemiBold; wrapMode: Text.WordWrap }
                    }
                    Body { objectName: "setupError"; text: setup.conflict ? (setup.editing ? "Another editor saved this configuration first. Reload to continue from the latest saved settings; your edits here will be replaced." : "Another editor saved the configuration first. Reload to continue with your draft.") : setup.error; color: theme.colors.warning }
                    RowLayout {
                        Layout.topMargin: 4; spacing: 8
                        ActionButton { visible: setup.conflict; text: "Reload"; icon.source: "qrc:/qml/icons/refresh.svg"; enabled: !manager.setupBusy; onClicked: setup.reload() }
                        ActionButton { visible: !setup.conflict; text: "Check again"; icon.source: "qrc:/qml/icons/refresh.svg"; enabled: !manager.setupBusy; onClicked: setup.check() }
                    }
                }
                Check { id: launcher; text: setup.editing ? "Update the app launcher entry" : "Add to the app launcher"; checked: true; enabled: !manager.setupBusy }
                Hint { text: "Opens this computer directly from your launcher, and lets Hypertile Scenes treat it as an ordinary app." }
            }
        }
    }
    // Errors outside the check and pairing pages stay near the controls that caused them.
    Rectangle {
        visible: setup.error.length > 0 && setup.step !== 2 && !setup.pairing
        Layout.fillWidth: true; radius: 10; color: theme.colors.warningBg; border.color: theme.colors.warningBorder
        implicitHeight: earlyError.implicitHeight + 24
        RowLayout {
            id: earlyError
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12; spacing: 10
            Icon { glyph: "alert"; size: 16; color: theme.colors.warning }
            Body { text: setup.error; color: theme.colors.warning; font.pointSize: theme.type.caption }
            ActionButton { objectName: "setupReadRetry"; visible: ["catalog", "get", "discover"].indexOf(setup.errorAction) >= 0; enabled: !manager.setupBusy; text: "Try again"; onClicked: setup.retryRead() }
            ActionButton { visible: setup.conflict; quiet: true; text: "Reload"; onClicked: setup.reload() }
        }
    }
    footer: Sheet.Footer {
        ActionButton { text: "Cancel"; enabled: !manager.setupBusy; onClicked: setup.requestClose() }
        ActionButton { visible: setup.step === 0 && !setup.pairing; quiet: true; icon.source: "qrc:/qml/icons/refresh.svg"; text: "Refresh list"; enabled: !manager.setupBusy; onClicked: { setup.discovering = true; manager.setup("catalog") } }
        Item { Layout.fillWidth: true }
        ActionButton { text: "Back"; icon.source: "qrc:/qml/icons/arrow-left.svg"; visible: setup.pairing || setup.step > (setup.editing ? 1 : 0); enabled: !manager.setupBusy; onClicked: { if (setup.pairing) { setup.pairing = false; setup.error = "" } else { setup.step--; setup.error = "" } } }
        ActionButton {
            objectName: "setupNext"; primary: true; visible: setup.step > 0 && !setup.pairing
            text: setup.step === 2 ? "Save computer" : "Continue"
            icon.source: setup.step === 2 ? "qrc:/qml/icons/check.svg" : ""
            enabled: !manager.setupBusy && setup.loaded && (setup.step !== 2 || setup.tested)
            onClicked: { if (setup.step === 2) manager.setup("save", setup.draft); else setup.advance() }
        }
    }
}
