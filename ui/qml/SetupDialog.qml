import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: setup
    objectName: "setupDialog"
    anchors.centerIn: parent
    width: Math.min(parent.width - 48, 660)
    height: Math.min(parent.height - 48, step === 1 ? 650 : 560)
    padding: 24
    background: Rectangle { radius: 16; color: theme.colors.bg; border.color: theme.colors.border }
    header: Item {
        implicitHeight: 68
        Label { anchors.left: parent.left; anchors.leftMargin: 24; anchors.verticalCenter: parent.verticalCenter; text: setup.title; color: theme.colors.text; font.pixelSize: 21; font.weight: Font.DemiBold }
    }
    modal: true
    closePolicy: manager.setupBusy ? Popup.NoAutoClose : Popup.CloseOnEscape
    title: editing ? "Computer settings" : "Add a computer"
    property bool editing: false
    property int step: 0
    property var draft: ({})
    property var paired: []
    property string revision: ""
    property string error: ""
    property bool tested: false
    property bool loaded: false
    property bool advanced: false
    signal saved(string computer)
    function begin(computer) {
        if (manager.setupBusy) return
        editing = !!computer; step = editing ? 1 : 0; draft = {}; paired = []
        error = ""; tested = false; loaded = false; advanced = false
        launcher.checked = !editing
        open()
        manager.setup(editing ? "get" : "catalog", computer ? {computer:computer} : {})
    }
    function set(key, value) {
        const next = Object.assign({}, draft); next[key] = value; draft = next
        tested = false; error = ""
    }
    function choose(host) {
        const slug = host.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "computer"
        draft = {computer:slug + "-" + host.pairing_uuid.slice(0,8), pairing_uuid:host.pairing_uuid,
            revision:revision, name:host.name, host:host.host, platform:"unknown", profile:"desktop",
            stream_resolution:"1920x1080", fps:60, bitrate:30000, codec:"auto", input:"absolute", audio:"focus"}
        step = 1; tested = false; error = ""
    }
    readonly property bool valid: loaded && (draft.name || "").trim().length > 0
        && /^[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$/.test(draft.host || "")
        && /^[0-9]{3,5}x[0-9]{3,5}$/.test(draft.stream_resolution || "")
    Connections {
        target: manager
        function onSetupFinished(action, ok, result, message) {
            if (!setup.visible) return
            if (!ok) { setup.error = message; return }
            setup.error = ""
            if (action === "catalog") { setup.paired = result.paired; setup.revision = result.revision; setup.loaded = true }
            if (action === "get") { setup.draft = result; setup.loaded = true }
            if (action === "test") setup.tested = true
            if (action === "save") {
                const id = setup.draft.computer
                setup.close(); setup.saved(id)
                if (launcher.checked) manager.act(id, "launcher")
            }
        }
    }
    component Body: Label { textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.colors.secondary; lineHeight: 1.2 }
    component FieldLabel: Label { color: theme.colors.secondary; font.pixelSize: 12 }
    function reveal(item) {
        const flick = scroll.contentItem
        const p = item.mapToItem(flick.contentItem, 0, 0)
        if (p.y < flick.contentY) flick.contentY = p.y
        else if (p.y + item.height > flick.contentY + flick.height)
            flick.contentY = Math.min(flick.contentHeight - flick.height, p.y + item.height - flick.height)
    }
    component Input: TextField {
        onActiveFocusChanged: if (activeFocus) setup.reveal(this)
        implicitHeight: 44; leftPadding: 12; rightPadding: 12
        color: theme.colors.text; selectionColor: theme.colors.accent; selectedTextColor: theme.colors.onAccent
        background: Rectangle { radius: 8; color: theme.colors.surface; border.color: parent.activeFocus ? theme.colors.accent : theme.colors.border }
    }
    component Select: ComboBox {
        onActiveFocusChanged: if (activeFocus) setup.reveal(this)
        implicitHeight: 44
        background: Rectangle { radius: 8; color: theme.colors.surface; border.color: parent.visualFocus ? theme.colors.accent : theme.colors.border }
    }
    contentItem: ColumnLayout {
        spacing: 16
        RowLayout {
            spacing: 8
            Repeater {
                model: ["Computer", "Preferences", "Check & save"]
                delegate: Label {
                    required property string modelData
                    required property int index
                    text: (index + 1) + "  " + modelData
                    color: setup.step === index ? theme.colors.accentText : theme.colors.muted
                    font.weight: setup.step === index ? Font.DemiBold : Font.Normal
                    Layout.fillWidth: true
                }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: theme.colors.border }
        ScrollView {
            id: scroll
            ScrollBar.vertical.policy: setup.advanced ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: parent.width; spacing: 16
                ColumnLayout {
                    visible: setup.step === 0
                    Layout.fillWidth: true; spacing: 14
                    Body { text: "Choose a computer you have paired in Moonlight."; color: theme.colors.text; font.pixelSize: 18 }
                    Body { visible: !setup.paired.length && !manager.setupBusy; text: "No paired computers found. Open Moonlight, add your computer and complete pairing. Then refresh this list." }
                    Repeater {
                        model: setup.paired
                        delegate: ItemDelegate {
                            required property var modelData
                            Layout.fillWidth: true; implicitHeight: 68
                            enabled: !modelData.configured && !manager.setupBusy
                            Accessible.name: modelData.name + (modelData.configured ? ", already added" : "")
                            onClicked: setup.choose(modelData)
                            background: Rectangle { radius: 9; color: parent.hovered ? theme.colors.hover : theme.colors.surface; border.color: parent.visualFocus ? theme.colors.accent : theme.colors.border }
                            contentItem: ColumnLayout {
                                Label { textFormat: Text.PlainText; text: modelData.name; color: theme.colors.text; font.weight: Font.DemiBold }
                                Body { text: modelData.configured ? "Already added — edit it from your computer list" : modelData.host || "You’ll enter its address next"; font.pixelSize: 12 }
                            }
                        }
                    }
                    ActionButton { text: "Refresh paired computers"; enabled: !manager.setupBusy; onClicked: manager.setup("catalog") }
                    Body { text: "Pairing stays in Moonlight. Remote Desktops uses the same trusted computer."; font.pixelSize: 12 }
                }
                ColumnLayout {
                    visible: setup.step === 1 && setup.loaded
                    enabled: !manager.setupBusy
                    Layout.fillWidth: true; spacing: 10
                    Body { text: setup.editing ? "Make this computer feel right for your work." : "A few details, then you’re ready."; color: theme.colors.text; font.pixelSize: 18 }
                    FieldLabel { text: "Computer name" }
                    Input { objectName: "setupName"; Layout.fillWidth: true; text: setup.draft.name || ""; maximumLength: 100; Accessible.name: "Computer name"; onTextEdited: setup.set("name", text) }
                    FieldLabel { text: "Address" }
                    Input { Layout.fillWidth: true; text: setup.draft.host || ""; placeholderText: "Hostname or IP address"; maximumLength: 253; Accessible.name: "Computer address"; onTextEdited: setup.set("host", text) }
                    Body { text: "Used to check reachability. Moonlight’s saved address is used for the stream."; font.pixelSize: 11 }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 16
                        ColumnLayout {
                            Layout.fillWidth: true
                            FieldLabel { text: "Operating system" }
                            Select { Layout.fillWidth: true; model: [{label:"Not specified",value:"unknown"},{label:"macOS",value:"macos"},{label:"Windows",value:"windows"},{label:"Linux",value:"linux"}]; textRole: "label"; valueRole: "value"; currentIndex: Math.max(0, ["unknown","macos","windows","linux"].indexOf(setup.draft.platform)); Accessible.name: "Operating system"; onActivated: setup.set("platform", currentValue) }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            FieldLabel { text: setup.editing ? "Default profile" : "Desktop quality" }
                            Select {
                                Layout.fillWidth: true
                                model: setup.editing ? Object.keys(setup.draft.profiles || {}) : ["Balanced · 1080p / 60 fps", "Sharper · 1440p / 60 fps", "Detailed · 4K / 60 fps", "Custom"]
                                currentIndex: {
                                    if (setup.editing) return Math.max(0, model.indexOf(setup.draft.profile))
                                    const i = ["1920x1080", "2560x1440", "3840x2160"].indexOf(setup.draft.stream_resolution)
                                    return i >= 0 && setup.draft.fps === 60 && setup.draft.bitrate === [30000,45000,80000][i] ? i : 3
                                }
                                Accessible.name: "Default profile"
                                onActivated: {
                                    if (setup.editing) {
                                        const p = setup.draft.profiles[currentText]
                                        setup.set("profile", currentText)
                                        for (const key of ["stream_resolution", "fps", "bitrate", "codec", "input", "audio"])
                                            setup.set(key, p[key] === undefined ? ({fps:60,bitrate:60000,codec:"HEVC",input:"absolute",audio:"focus"})[key] : p[key])
                                    } else if (currentIndex === 3) setup.advanced = true
                                    else {
                                        const i = currentIndex
                                        setup.set("fps", 60)
                                        setup.set("stream_resolution", ["1920x1080", "2560x1440", "3840x2160"][i])
                                        setup.set("bitrate", [30000, 45000, 80000][i])
                                    }
                                }
                            }
                        }
                    }
                    Button { text: setup.advanced ? "▾  Advanced stream settings" : "▸  Advanced stream settings"; flat: true; onClicked: setup.advanced = !setup.advanced }
                    GridLayout {
                        visible: setup.advanced
                        Layout.fillWidth: true; columns: 2; columnSpacing: 16; rowSpacing: 8
                        FieldLabel { text: "Resolution" }
                        FieldLabel { text: "Frame rate" }
                        Input { Layout.fillWidth: true; text: setup.draft.stream_resolution || ""; Accessible.name: "Stream resolution"; onTextEdited: setup.set("stream_resolution", text) }
                        SpinBox { onActiveFocusChanged: if (activeFocus) setup.reveal(this); Layout.fillWidth: true; from: 20; to: 240; value: setup.draft.fps || 60; editable: true; Accessible.name: "Frames per second"; onValueModified: setup.set("fps", value) }
                        FieldLabel { text: "Bitrate (kbps)" }
                        FieldLabel { text: "Codec" }
                        SpinBox { onActiveFocusChanged: if (activeFocus) setup.reveal(this); Layout.fillWidth: true; from: 1000; to: 200000; stepSize: 1000; value: setup.draft.bitrate || 30000; editable: true; Accessible.name: "Bitrate in kilobits per second"; onValueModified: setup.set("bitrate", value) }
                        Select { Layout.fillWidth: true; model: ["auto", "HEVC", "H.264", "AV1"]; currentIndex: Math.max(0,model.indexOf(setup.draft.codec)); Accessible.name: "Codec"; onActivated: setup.set("codec", currentText) }
                        FieldLabel { text: "Mouse mode" }
                        FieldLabel { text: "Audio" }
                        Select { Layout.fillWidth: true; model: ["absolute", "relative"]; currentIndex: Math.max(0,model.indexOf(setup.draft.input)); Accessible.name: "Mouse mode"; onActivated: setup.set("input", currentText) }
                        Select { Layout.fillWidth: true; model: ["focus", "continuous", "host"]; currentIndex: Math.max(0,model.indexOf(setup.draft.audio)); Accessible.name: "Audio policy"; onActivated: setup.set("audio", currentText) }
                    }
                    Body { text: setup.editing ? "Existing display management is preserved. Changes apply after disconnecting and starting a new connection." : "The host keeps its current display settings. You can tune stream quality later."; font.pixelSize: 12 }
                }
                ColumnLayout {
                    visible: setup.step === 2
                    Layout.fillWidth: true; spacing: 16
                    Body { text: setup.tested ? (setup.editing ? "Your changes are ready to save." : "Your computer is ready to add.") : "Let’s check the connection."; color: theme.colors.text; font.pixelSize: 22; font.weight: Font.DemiBold }
                    Body { text: (setup.draft.name || "") + "\n" + (setup.draft.host || "") + "\n" + (setup.draft.stream_resolution || "") + " · " + (setup.draft.fps || 60) + " fps" }
                    Body { text: setup.tested ? (manager.demo ? "Simulated check passed. No real computer was contacted." : "Moonlight authenticated and found the Desktop app. Video and input will be checked when you connect.") : "This checks reachability, Moonlight pairing and the Desktop app. It won’t start a stream or change the host’s display."; color: setup.tested ? theme.colors.success : theme.colors.secondary }
                    ActionButton { objectName: "setupTest"; text: manager.setupBusy ? "Checking…" : setup.tested ? "Check again" : "Test connection"; enabled: !manager.setupBusy; onClicked: { setup.tested = false; manager.setup("test", setup.draft) } }
                    CheckBox { id: launcher; text: setup.editing ? "Update app launcher entry" : "Add to app launcher"; checked: true; enabled: !manager.setupBusy }
                    Body { text: "Open this computer directly from your launcher, or choose it as an app in a Hypertile Scene."; font.pixelSize: 12 }
                }
            }
        }
        Body { visible: manager.setupBusy && setup.step !== 2; text: "Working…" }
        Body { objectName: "setupError"; visible: !!setup.error; text: setup.error; color: theme.colors.warning }
    }
    footer: Item {
        implicitHeight: 76
        RowLayout {
        anchors.fill: parent; anchors.margins: 16
        spacing: 10
        ActionButton { text: "Cancel"; enabled: !manager.setupBusy; onClicked: setup.close() }
        Item { Layout.fillWidth: true }
        ActionButton { text: "Back"; visible: setup.step > (setup.editing ? 1 : 0); enabled: !manager.setupBusy; onClicked: { setup.step--; setup.error = "" } }
        ActionButton {
            objectName: "setupNext"; primary: true; visible: setup.step > 0
            text: setup.step === 2 ? "Save computer" : "Continue"
            enabled: !manager.setupBusy && setup.valid && (setup.step !== 2 || setup.tested)
            onClicked: { if (setup.step === 2) manager.setup("save", setup.draft); else setup.step = 2 }
        }
    }
    }
}
