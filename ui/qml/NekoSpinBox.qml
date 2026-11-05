import QtQuick
import QtQuick.Controls

SpinBox {
    id: control
    property var bridge: null
    implicitWidth: 120
    implicitHeight: 36
    padding: 3
    leftPadding: 32
    rightPadding: 32
    font.family: "Segoe UI"
    font.pixelSize: 13

    background: Rectangle {
        radius: 8
        color: control.bridge ? control.bridge.surfaceAltFillColor : "#241d2d"
        border.width: control.activeFocus ? 1.5 : 1
        border.color: control.activeFocus
            ? (control.bridge ? control.bridge.accentColor : "#9271c5")
            : (control.bridge ? control.bridge.frameColor : "#51475f")
        antialiasing: true
    }

    contentItem: TextInput {
        z: 1
        text: control.displayText
        font: control.font
        color: control.bridge ? control.bridge.primaryColor : "#f4f0fa"
        selectionColor: control.bridge ? control.bridge.accentColor : "#9271c5"
        selectedTextColor: "#ffffff"
        horizontalAlignment: TextInput.AlignHCenter
        verticalAlignment: TextInput.AlignVCenter
        readOnly: !control.editable
        validator: control.validator
        inputMethodHints: Qt.ImhFormattedNumbersOnly
        selectByMouse: true
        clip: true
    }

    down.indicator: Rectangle {
        x: 3
        y: 3
        width: 26
        height: control.height - 6
        radius: 6
        color: control.down.pressed
            ? (control.bridge ? control.bridge.accentColor : "#9271c5")
            : (control.down.hovered && control.bridge
                ? control.bridge.surfaceHoverColor
                : (control.bridge ? control.bridge.surfaceFillColor : "#30263b"))
        border.width: 1
        border.color: control.bridge ? control.bridge.frameColor : "#51475f"
        Text {
            anchors.centerIn: parent
            text: "−"
            color: control.down.pressed ? "#ffffff"
                : (control.bridge ? control.bridge.primaryColor : "#f4f0fa")
            font.family: "Segoe UI"
            font.pixelSize: 17
            font.weight: Font.DemiBold
        }
    }

    up.indicator: Rectangle {
        x: control.width - width - 3
        y: 3
        width: 26
        height: control.height - 6
        radius: 6
        color: control.up.pressed
            ? (control.bridge ? control.bridge.accentColor : "#9271c5")
            : (control.up.hovered && control.bridge
                ? control.bridge.surfaceHoverColor
                : (control.bridge ? control.bridge.surfaceFillColor : "#30263b"))
        border.width: 1
        border.color: control.bridge ? control.bridge.frameColor : "#51475f"
        Text {
            anchors.centerIn: parent
            text: "+"
            color: control.up.pressed ? "#ffffff"
                : (control.bridge ? control.bridge.primaryColor : "#f4f0fa")
            font.family: "Segoe UI"
            font.pixelSize: 16
            font.weight: Font.DemiBold
        }
    }
}
