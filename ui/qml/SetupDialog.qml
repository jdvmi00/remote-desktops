import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Sheet {
    id: setup
    objectName: "setupDialog"
    width: Math.min(parent.width - 48, 680)
    height: Math.min(parent.height - 40, 660)
    // Escape and Cancel go through requestClose(), which asks before
    // discarding a draft. Nothing closes this dialog by accident.
    closePolicy: Popup.NoAutoClose
    onEscapeRequested: requestClose()
    title: editing ? "Computer settings" : "Add a computer"
    topPadding: 0
    property bool editing: false
    property int step: 0
    property var draft: ({})
    property var paired: []
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
    readonly property var steps: editing ? ["Settings", "Check & save"] : ["Computer", "Settings", "Check & save"]
    readonly property int stepIndex: editing ? step - 1 : step
    readonly property bool dirty: editing ? edited : step > 0
    readonly property bool conflict: error.indexOf("changed elsewhere") >= 0
    readonly property bool checking: manager.setupBusy && step === 2
    readonly property string nameError: (draft.name || "").trim().length > 0 ? "" : "Enter a name for this computer."
    readonly property string hostError: /^[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$/.test(draft.host || "") ? "" : "Enter a hostname or IP address using letters, digits, dots, colons, or dashes."
    readonly property string resolutionError: /^[0-9]{3,5}x[0-9]{3,5}$/.test(draft.stream_resolution || "") ? "" : "Use WIDTHxHEIGHT, for example 2560x1440."
    readonly property bool valid: loaded && !nameError && !hostError && !resolutionError
    readonly property var presets: [{label: "Balanced · 1080p, 60 fps", res: "1920x1080", bitrate: 30000}, {label: "Sharper · 1440p, 60 fps", res: "2560x1440", bitrate: 45000}, {label: "Detailed · 4K, 60 fps", res: "3840x2160", bitrate: 80000}, {label: "Custom", res: "", bitrate: 0}]
    readonly property var codecs: [{label: "Automatic", value: "auto"}, {label: "HEVC (H.265)", value: "HEVC"}, {label: "H.264", value: "H.264"}, {label: "AV1", value: "AV1"}]
    readonly property var inputs: [{label: "Direct pointer", value: "absolute", hint: "The pointer lands exactly where you point. Best for desktop work."}, {label: "Relative pointer", value: "relative", hint: "Sends movement only. Needed by games that capture the mouse."}]
    readonly property var audios: [{label: "Play here, mute when unfocused", value: "focus", hint: "Sound plays on this computer and mutes while the desktop window is not active."}, {label: "Always play here", value: "continuous", hint: "Sound plays on this computer even while the window is in the background."}, {label: "Keep audio on the host", value: "host", hint: "Nothing plays here; the remote computer keeps its sound."}]
    readonly property int presetIndex: {
        const i = ["1920x1080", "2560x1440", "3840x2160"].indexOf(draft.stream_resolution)
        return i >= 0 && draft.fps === 60 && draft.bitrate === presets[i].bitrate && (draft.codec || "auto") === "auto" ? i : 3
    }
    function fieldError(key, message) { return message.length > 0 && (attempted || touched[key] === true) ? message : "" }
    function valueLabel(list, value) { for (const item of list) if (item.value === value) return item.label; return value || "" }
    function summary() { return (draft.stream_resolution || "") + " · " + (draft.fps || 60) + " fps · " + Math.round((draft.bitrate || 0) / 1000) + " Mbit/s · " + valueLabel(codecs, draft.codec || "auto") + " codec" }
    function begin(computer) {
        if (manager.setupBusy) return
        editing = !!computer; step = editing ? 1 : 0; draft = {}; paired = []
        error = ""; errorAction = ""; tested = false; loaded = false; advanced = false; edited = false; attempted = false; touched = {}
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
    function set(key, value) {
        const next = Object.assign({}, draft); next[key] = value; draft = next
        const t = Object.assign({}, touched); t[key] = true; touched = t
        tested = false; error = ""; edited = true
    }
    function choose(host) {
        const slug = host.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "computer"
        draft = {computer: slug + "-" + host.pairing_uuid.slice(0, 8), pairing_uuid: host.pairing_uuid,
            revision: revision, name: host.name, host: host.host, platform: "unknown", profile: "desktop",
            stream_resolution: "1920x1080", fps: 60, bitrate: 30000, codec: "auto", input: "absolute", audio: "focus"}
        step = 1; tested = false; error = ""; attempted = false; touched = {}
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
        if (editing) { loaded = false; tested = false; manager.setup("get", {computer: draft.computer}) }
        else manager.setup("catalog")
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
            if (!ok) { setup.error = message; setup.errorAction = action; return }
            setup.error = ""; setup.errorAction = ""
            if (action === "catalog") {
                setup.paired = result.paired; setup.revision = result.revision; setup.loaded = true
                if (setup.step > 0) { const next = Object.assign({}, setup.draft); next.revision = result.revision; setup.draft = next }
            }
            if (action === "get") { setup.draft = result; setup.loaded = true; setup.edited = false }
            if (action === "test") setup.tested = true
            if (action === "save") {
                const id = setup.draft.computer
                setup.close(); setup.saved(id)
                if (launcher.checked) manager.act(id, "launcher")
            }
        }
    }
    Confirm { id: discard; parent: Overlay.overlay }
    component Body: Label { textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.colors.secondary; lineHeight: 1.25 }
    component FieldLabel: Label { color: theme.colors.text; font.pointSize: theme.type.caption; font.weight: Font.Medium }
    component Hint: Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.colors.muted; font.pointSize: theme.type.caption }
    component Problem: Label { Layout.fillWidth: true; visible: text.length > 0; wrapMode: Text.WordWrap; color: theme.colors.danger; font.pointSize: theme.type.caption; Accessible.role: Accessible.AlertMessage }
    component Progress: Rectangle {
        id: bar
        Layout.fillWidth: true; height: 3; radius: 1.5; color: theme.colors.border; clip: true
        Accessible.role: Accessible.ProgressBar
        Rectangle {
            width: parent.width * .3; height: parent.height; radius: 1.5; color: theme.colors.accent
            SequentialAnimation on x { running: bar.visible; loops: Animation.Infinite; NumberAnimation { from: -bar.width * .3; to: bar.width; duration: 1300; easing.type: Easing.InOutQuad } }
        }
    }
    component Input: Field { onActiveFocusChanged: if (activeFocus) setup.reveal(this) }
    component Choice: Select { onActiveFocusChanged: if (activeFocus) setup.reveal(this) }

    // Step indicator: done, current, and upcoming steps are visibly different.
    RowLayout {
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
            // Step: choose a paired computer.
            ColumnLayout {
                visible: setup.step === 0
                Layout.fillWidth: true; spacing: 14
                Body { text: "Choose a computer you have paired in Moonlight."; color: theme.colors.text; font.pointSize: theme.type.lead }
                ColumnLayout {
                    visible: manager.setupBusy && !setup.paired.length
                    Layout.fillWidth: true; spacing: 10
                    Body { text: "Looking for paired computers…" }
                    Progress {}
                }
                ColumnLayout {
                    visible: setup.loaded && !setup.paired.length && !manager.setupBusy
                    Layout.fillWidth: true; spacing: 10
                    Rectangle {
                        Layout.fillWidth: true; radius: 12; color: theme.colors.surface; border.color: theme.colors.border
                        implicitHeight: emptyColumn.implicitHeight + 36
                        ColumnLayout {
                            id: emptyColumn
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 18; spacing: 8
                            Label { text: "No paired computers found"; color: theme.colors.text; font.weight: Font.DemiBold }
                            Body { text: "Pair your computer in Moonlight first: add it there, enter the PIN on the host, and confirm that its apps appear. Then refresh this list." }
                            RowLayout {
                                Layout.topMargin: 6; spacing: 8
                                ActionButton { visible: manager.moonlightAvailable || manager.demo; icon.source: "qrc:/qml/icons/external.svg"; text: "Open Moonlight"; onClicked: manager.openMoonlight() }
                                ActionButton { quiet: true; icon.source: "qrc:/qml/icons/refresh.svg"; text: "Refresh list"; enabled: !manager.setupBusy; onClicked: manager.setup("catalog") }
                            }
                        }
                    }
                }
                Repeater {
                    model: setup.paired
                    delegate: ItemDelegate {
                        id: candidate
                        required property var modelData
                        Layout.fillWidth: true; implicitHeight: 66
                        hoverEnabled: true
                        enabled: !modelData.configured && !manager.setupBusy
                        Accessible.name: modelData.name + (modelData.configured ? ", already added" : "")
                        onClicked: setup.choose(modelData)
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
                            Icon { visible: candidate.enabled; glyph: "chevron-down"; rotation: -90; color: theme.colors.muted }
                        }
                    }
                }
                Hint { visible: setup.paired.length > 0; text: "Pairing and certificates stay in Moonlight. Remote Desktops uses the same trusted computer." }
            }
            // Step: name, address, and quality.
            ColumnLayout {
                visible: setup.step === 1 && setup.loaded
                enabled: !manager.setupBusy
                Layout.fillWidth: true; spacing: 8
                Body { text: setup.editing ? "Change how this computer connects." : "A few details, then a quick check."; color: theme.colors.text; font.pointSize: theme.type.lead; Layout.bottomMargin: 6 }
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
                        Choice { Layout.fillWidth: true; model: [{label: "Not specified", value: "unknown"}, {label: "macOS", value: "macos"}, {label: "Windows", value: "windows"}, {label: "Linux", value: "linux"}]; textRole: "label"; valueRole: "value"; currentIndex: Math.max(0, ["unknown", "macos", "windows", "linux"].indexOf(setup.draft.platform)); Accessible.name: "Operating system"; onActivated: setup.set("platform", currentValue) }
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
                                    for (const key of ["stream_resolution", "fps", "bitrate", "codec", "input", "audio"])
                                        setup.set(key, p[key] === undefined ? ({fps: 60, bitrate: 60000, codec: "HEVC", input: "absolute", audio: "focus"})[key] : p[key])
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
                        Input { Layout.fillWidth: true; text: setup.draft.stream_resolution || ""; placeholderText: "2560x1440"; invalid: setup.fieldError("stream_resolution", setup.resolutionError).length > 0; Accessible.name: "Stream resolution"; onTextEdited: setup.set("stream_resolution", text) }
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
                }
                Hint { Layout.topMargin: 8; text: setup.editing ? "Display management for this computer is preserved. Changes apply after disconnecting and starting a new connection." : "The host keeps its current display settings. You can tune stream quality later." }
            }
            ColumnLayout {
                visible: setup.step === 1 && !setup.loaded
                Layout.fillWidth: true; spacing: 10
                Body { text: "Loading settings…" }
                Progress {}
            }
            // Step: check and save.
            ColumnLayout {
                visible: setup.step === 2
                Layout.fillWidth: true; spacing: 16
                Body { text: setup.tested ? (setup.editing ? "Your changes are ready to save." : "Ready to add this computer.") : setup.checking ? "Checking the connection…" : "Checking the connection"; color: theme.colors.text; font.pointSize: theme.type.lead }
                Rectangle {
                    Layout.fillWidth: true; radius: 12; color: theme.colors.surface; border.color: theme.colors.border
                    implicitHeight: summaryGrid.implicitHeight + 32
                    GridLayout {
                        id: summaryGrid
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16
                        columns: 2; columnSpacing: 20; rowSpacing: 8
                        Repeater {
                            model: [["Name", setup.draft.name || ""], ["Address", setup.draft.host || ""], ["Operating system", ({macos: "macOS", windows: "Windows", linux: "Linux"})[setup.draft.platform] || "Not specified"], ["Quality", setup.summary()], ["Mouse", setup.valueLabel(setup.inputs, setup.draft.input || "absolute")], ["Audio", setup.valueLabel(setup.audios, setup.draft.audio || "focus")]]
                            delegate: Repeater {
                                required property var modelData
                                model: 2
                                delegate: Label {
                                    required property int index
                                    Layout.fillWidth: index === 1
                                    text: modelData[index]; textFormat: Text.PlainText; wrapMode: Text.WordWrap
                                    color: index === 0 ? theme.colors.muted : theme.colors.text
                                    font.pointSize: index === 0 ? theme.type.caption : theme.type.body
                                }
                            }
                        }
                    }
                }
                ColumnLayout {
                    visible: setup.checking
                    Layout.fillWidth: true; spacing: 10
                    Body { text: "Checking reachability, Moonlight pairing, and the Desktop app. This does not start a stream or change the host display." }
                    Progress {}
                }
                RowLayout {
                    visible: setup.tested && !setup.checking
                    Layout.fillWidth: true; spacing: 10
                    Icon { glyph: "check"; color: theme.colors.success; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 4
                        Label { text: "Connection check passed"; color: theme.colors.success; font.weight: Font.DemiBold }
                        Body { text: manager.demo ? "Simulated check. No real computer was contacted." : "Moonlight authenticated and found the Desktop app. Video and input are verified when you connect." }
                    }
                }
                Rectangle {
                    visible: setup.error.length > 0 && setup.step === 2
                    Layout.fillWidth: true; radius: 12; color: theme.colors.warningBg; border.color: theme.colors.warningBorder
                    implicitHeight: problemColumn.implicitHeight + 32
                    ColumnLayout {
                        id: problemColumn
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16; spacing: 8
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
                }
                Check { id: launcher; text: setup.editing ? "Update the app launcher entry" : "Add to the app launcher"; checked: true; enabled: !manager.setupBusy }
                Hint { text: "Opens this computer directly from your launcher, and lets Hypertile Scenes treat it as an ordinary app." }
            }
        }
    }
    // Errors outside the check step stay near the controls that caused them.
    Rectangle {
        visible: setup.error.length > 0 && setup.step !== 2
        Layout.fillWidth: true; radius: 10; color: theme.colors.warningBg; border.color: theme.colors.warningBorder
        implicitHeight: earlyError.implicitHeight + 24
        RowLayout {
            id: earlyError
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12; spacing: 10
            Icon { glyph: "alert"; size: 16; color: theme.colors.warning }
            Body { text: setup.error; color: theme.colors.warning; font.pointSize: theme.type.caption }
            ActionButton { visible: setup.conflict; quiet: true; text: "Reload"; onClicked: setup.reload() }
        }
    }
    // The test button is always present so keyboard users and tests can reach it.
    ActionButton { objectName: "setupTest"; visible: false; text: "Check again"; onClicked: setup.check() }
    footer: Sheet.Footer {
        ActionButton { text: "Cancel"; enabled: !manager.setupBusy; onClicked: setup.requestClose() }
        ActionButton { visible: setup.step === 0; quiet: true; icon.source: "qrc:/qml/icons/refresh.svg"; text: "Refresh list"; enabled: !manager.setupBusy; onClicked: manager.setup("catalog") }
        Item { Layout.fillWidth: true }
        ActionButton { text: "Back"; icon.source: "qrc:/qml/icons/arrow-left.svg"; visible: setup.step > (setup.editing ? 1 : 0); enabled: !manager.setupBusy; onClicked: { setup.step--; setup.error = "" } }
        ActionButton {
            objectName: "setupNext"; primary: true; visible: setup.step > 0
            text: setup.step === 2 ? "Save computer" : "Continue"
            icon.source: setup.step === 2 ? "qrc:/qml/icons/check.svg" : ""
            enabled: !manager.setupBusy && setup.loaded && (setup.step !== 2 || setup.tested)
            onClicked: { if (setup.step === 2) manager.setup("save", setup.draft); else setup.advance() }
        }
    }
}
