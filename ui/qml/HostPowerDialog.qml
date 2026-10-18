import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Sheet {
    id: dialog
    objectName: "hostPowerDialog"
    title: "Host power"
    subtitle: "Keep this Omarchy Linux computer awake while streaming"
    width: Math.min(parent.width - 48, 590)
    height: Math.min(parent.height - 40, 640)
    closePolicy: Popup.NoAutoClose
    onEscapeRequested: if (!manager.setupBusy) close()
    property string computer: ""
    property string revision: ""
    property string sshAlias: ""
    property string policy: "ac"
    property var hostStatus: ({})
    property bool inspected: false
    property string error: ""
    property string notice: ""
    property bool selectionEdited: false
    readonly property bool validAlias: /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(sshAlias)
    readonly property string appliedPolicy: hostStatus.installed ? hostStatus.policy : "off"
    readonly property bool pendingPolicy: inspected && policy !== appliedPolicy
    function policyName(value) {
        return value === "ac" ? "On AC power" : value === "always" ? "Always, including on battery" : "Off"
    }
    function begin(id) {
        if (manager.setupBusy) return
        computer = id; revision = ""; sshAlias = ""; policy = "ac"
        inspected = false; hostStatus = {}; error = ""; notice = ""; selectionEdited = false
        open(); manager.setup("get", {computer: id})
    }
    function inspect() {
        inspected = false; error = ""
        manager.setup("power-status", {computer: computer, ssh: {alias: sshAlias}})
    }
    function apply() {
        error = ""; notice = ""
        manager.setup("power-set", {computer: computer, revision: revision, ssh: {alias: sshAlias}, policy: policy})
    }
    Connections {
        target: manager
        function onSetupFinished(action, ok, result, message) {
            if (!dialog.visible || ["get", "power-status", "power-set"].indexOf(action) < 0) return
            if (!ok) { dialog.error = message; if (action !== "get") dialog.inspected = false; return }
            if (action === "get") {
                dialog.revision = result.revision
                dialog.sshAlias = result.ssh ? result.ssh.alias || "" : ""
                if (dialog.validAlias) dialog.inspect()
            } else {
                dialog.hostStatus = result; dialog.inspected = true
                if (action === "power-set") dialog.selectionEdited = false
                if (!dialog.selectionEdited) dialog.policy = result.installed ? result.policy : "ac"
                if (action === "power-set") {
                    dialog.notice = "Applied on host: " + dialog.policyName(result.policy) + "."
                    // Applying the host policy also saves its transport; obtain the new revision.
                    manager.setup("get", {computer: dialog.computer})
                }
            }
        }
    }
    component Copy: Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; textFormat: Text.PlainText; color: theme.colors.secondary }
    Copy {
        objectName: "hostPowerApplied"
        text: dialog.inspected
            ? (dialog.hostStatus.installed ? "On host: " + dialog.policyName(dialog.appliedPolicy) : "On host: Not installed — normal lid and sleep behavior")
            : "Check the host to see its installed policy."
        color: theme.colors.text; font.weight: Font.DemiBold
    }
    ScrollView {
        Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
        ColumnLayout {
            width: parent.width; spacing: 14
            Copy { text: "This setting lives on the host and applies to every Sunshine client. Closing Remote Desktops does not turn it off." }
            Copy { text: "SSH alias"; color: theme.colors.text; font.weight: Font.Medium }
            Field {
                objectName: "hostPowerSsh"; Layout.fillWidth: true; maximumLength: 64
                text: dialog.sshAlias; placeholderText: "Alias from ~/.ssh/config"
                Accessible.name: "Host power SSH alias"
                enabled: !manager.setupBusy
                onTextEdited: { dialog.sshAlias = text; dialog.inspected = false; dialog.error = ""; dialog.notice = ""; dialog.selectionEdited = false }
            }
            Copy { text: "Uses your existing SSH key and known hosts. The account must own the host's Omarchy and Sunshine session."; font.pointSize: theme.type.caption }
            ActionButton { objectName: "hostPowerInspect"; text: "Check host"; enabled: dialog.validAlias && !manager.setupBusy; onClicked: dialog.inspect() }
            Copy { text: "Choose a policy to apply"; color: theme.colors.text; font.weight: Font.Medium }
            Select {
                objectName: "hostPowerPolicy"; Layout.fillWidth: true
                model: [{label: "Off — normal lid and sleep behavior", value: "off"},
                        {label: "On AC power (recommended)", value: "ac"},
                        {label: "Always, including on battery", value: "always"}]
                textRole: "label"; valueRole: "value"
                currentIndex: Math.max(0, ["off", "ac", "always"].indexOf(dialog.policy))
                enabled: !manager.setupBusy
                Accessible.name: "Keep host awake while streaming"
                onActivated: { dialog.policy = currentValue; dialog.selectionEdited = true; dialog.notice = "" }
            }
            Copy { text: "Selecting an option does not change the host. Use the apply button below to install or update its policy." }
            Copy { text: "During streaming, this policy prevents sleep and lid-close locking. Normal behavior resumes after the last stream ends. Disconnect every Sunshine client before applying a change." }
            Copy { text: "After connecting, use Check host to confirm it is keeping the host awake before closing the lid."; font.pointSize: theme.type.caption }
            Copy { text: "Keeping the host awake does not create a virtual display. Lid-closed video capture still depends on the host's display and driver."; font.pointSize: theme.type.caption }
            Copy { visible: dialog.inspected; text: "Host status (last check)"; color: theme.colors.text; font.weight: Font.Medium }
            Copy {
                objectName: "hostPowerStatus"; visible: dialog.inspected
                text: dialog.hostStatus.active ? "Keeping the host awake while streaming"
                    : dialog.hostStatus.installed && dialog.hostStatus.policy !== "off"
                    ? (dialog.hostStatus.running ? "Policy enabled · waiting for an eligible stream" : "Policy installed · host helper is not reporting")
                    : "No keep-awake policy enabled"
                color: dialog.hostStatus.active ? theme.colors.success : theme.colors.secondary
            }
            Copy { visible: dialog.inspected && dialog.hostStatus.stream_workers > 0; text: "The host has active streams. Disconnect them before applying."; color: theme.colors.warning }
            Copy { visible: dialog.inspected && !!dialog.hostStatus.error; text: dialog.hostStatus.error || ""; color: theme.colors.warning }
            Copy { text: "Apply on host installs or updates a small user service and the Omarchy lid handler. Off stops the service and restores the default lid handler. No administrator password or Sunshine web password is stored."; font.pointSize: theme.type.caption }
            Copy { objectName: "hostPowerError"; visible: !!dialog.error; text: dialog.error; color: theme.colors.danger; Accessible.role: Accessible.AlertMessage }
        }
    }
    footer: ColumnLayout {
        spacing: 0
        Copy {
            objectName: "hostPowerPending"
            Layout.leftMargin: 16; Layout.rightMargin: 16
            text: dialog.pendingPolicy ? "Not applied: " + dialog.policyName(dialog.policy) + "."
                : dialog.notice || (dialog.inspected ? "The selected policy matches the host." : "Check the host before applying a policy.")
            color: dialog.pendingPolicy ? theme.colors.warning : dialog.notice ? theme.colors.success : theme.colors.secondary
        }
        Copy {
            Layout.leftMargin: 16; Layout.rightMargin: 16; Layout.topMargin: 4
            visible: dialog.inspected && dialog.hostStatus.stream_workers > 0
            text: "Disconnect all streams to enable the apply button."
            color: theme.colors.warning
        }
        Sheet.Footer {
            Layout.fillWidth: true
            ActionButton { text: dialog.pendingPolicy ? "Close without applying" : "Close"; quiet: true; enabled: !manager.setupBusy; onClicked: dialog.close() }
            Item { Layout.fillWidth: true }
            ActionButton {
                objectName: "hostPowerApply"; primary: true
                text: manager.setupBusy ? "Working…" : !dialog.hostStatus.installed && dialog.policy !== "off" ? "Install and apply on host" : "Apply on host"
                enabled: dialog.inspected && dialog.validAlias && !manager.setupBusy
                    && (dialog.hostStatus.supported ? dialog.hostStatus.stream_workers === 0 : dialog.policy === "off")
                onClicked: dialog.apply()
            }
        }
    }
}
