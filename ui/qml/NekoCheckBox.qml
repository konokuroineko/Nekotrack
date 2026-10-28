import QtQuick
import QtQuick.Controls

CheckBox {
    id: control
    property var bridge: null
    spacing: 8
    font.family: "Segoe UI"
    font.pixelSize: 12

    indicator: Rectangle {
        implicitWidth: 18
        implicitHeight: 18
        x: control.leftPadding
        y: control.topPadding + (control.availableHeight - height) / 2
        radius: 5
        color: control.checked
            ? (control.bridge ? control.bridge.accentColor : "#9271c5")
            : (control.hovered && control.bridge
                ? control.bridge.surfaceHoverColor
                : (control.bridge ? control.bridge.surfaceAltFillColor : "#241d2d"))
        border.width: control.activeFocus ? 1.5 : 1
        border.color: control.checked
            ? (control.bridge ? control.bridge.accentColor : "#9271c5")
            : (control.bridge ? control.bridge.frameColor : "#51475f")
        antialiasing: true
        Text {
            anchors.centerIn: parent
            visible: control.checked
            text: "✓"
            color: "#ffffff"
            font.family: "Segoe UI"
            font.pixelSize: 13
            font.weight: Font.Bold
        }
    }

    contentItem: Text {
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        color: control.bridge ? control.bridge.primaryColor : "#f4f0fa"
        font: control.font
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
        opacity: control.enabled ? 1 : 0.52
    }
}
