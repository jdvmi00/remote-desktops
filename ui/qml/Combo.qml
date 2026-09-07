import QtQuick
import QtQuick.Controls

// An editable Select: pick a suggestion from the list or type a value.
// The owner sets `value`; anything the user picks or types arrives as `edited`.
Select {
    id: control
    property bool invalid: false
    property string value: ""
    property string placeholder: ""
    signal edited(string text)
    editable: true
    property bool syncing: false
    // The combo box rewrites the edit text whenever the current index changes, so
    // the index is only aligned with the value while the user is not typing.
    function sync() {
        syncing = true
        if (!contentItem.activeFocus || popup.visible) { const i = find(value); if (currentIndex !== i) currentIndex = i }
        if (editText !== value) editText = value
        syncing = false
    }
    onValueChanged: sync()
    onModelChanged: sync()
    Component.onCompleted: sync()
    // Keyboard focus lands in the text editor so typing works after Tab as well as after a click.
    onActiveFocusChanged: { if (activeFocus && !contentItem.activeFocus) contentItem.forceActiveFocus(); if (!activeFocus) sync() }
    popup.onAboutToShow: sync()
    onEditTextChanged: if (!syncing && contentItem.activeFocus && editText !== value) edited(editText)
    onActivated: edited(currentText)
    contentItem: TextField {
        text: control.editText
        placeholderText: control.placeholder
        font: control.font
        color: control.enabled ? theme.colors.text : theme.colors.disabledText
        placeholderTextColor: theme.colors.muted
        selectionColor: theme.colors.accent; selectedTextColor: theme.colors.onAccent
        leftPadding: 0; rightPadding: 0; topPadding: 0; bottomPadding: 0
        verticalAlignment: Text.AlignVCenter
        validator: control.validator
        inputMethodHints: control.inputMethodHints
        background: null
    }
    background: Rectangle {
        radius: 9
        color: control.enabled ? theme.colors.surface : theme.colors.disabled
        border.width: control.activeFocus || control.invalid ? 2 : 1
        border.color: control.invalid ? theme.colors.danger : control.activeFocus ? theme.colors.accent : theme.colors.border
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
}
