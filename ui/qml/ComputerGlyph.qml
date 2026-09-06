import QtQuick
Item {
    id: icon
    property color ink: "#b2c2ba"
    property bool laptop: false
    implicitWidth: 28
    implicitHeight: 28
    Rectangle { x: 3; y: 4; width: 22; height: 15; radius: 3; color: "transparent"; border.color: icon.ink; border.width: 1.5 }
    Rectangle { x: icon.laptop ? 1 : 12; y: 20; width: icon.laptop ? 26 : 4; height: 2; radius: 1; color: icon.ink }
    Rectangle { visible: !icon.laptop; x: 8; y: 23; width: 12; height: 1.5; radius: 1; color: icon.ink }
}
