import QtQuick
import QtQuick.Controls.impl

// Tinted line icon from the bundled SVG set.
IconImage {
    property string glyph: ""
    property int size: 18
    source: glyph ? "qrc:/qml/icons/" + glyph + ".svg" : ""
    sourceSize: Qt.size(size, size)
    width: size; height: size
    color: theme.colors.secondary
    fillMode: Image.PreserveAspectFit
}
