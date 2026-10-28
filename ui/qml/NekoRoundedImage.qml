import QtQuick
import QtQuick.Effects

Item {
    id: root
    property var imageBridge: null
    property string url: ""
    property real radius: 12
    property int fillMode: Image.PreserveAspectCrop
    property bool asynchronous: true
    property bool cache: true
    readonly property int status: image.status

    implicitWidth: 120
    implicitHeight: 120

    NekoImage {
        id: image
        anchors.fill: parent
        imageBridge: root.imageBridge
        url: root.url
        fillMode: root.fillMode
        asynchronous: root.asynchronous
        cache: root.cache
        visible: false
    }

    // Match PosterCard's proven masking structure: keep the source and
    // mask textures independent, then composite them through MultiEffect.
    Item {
        id: mask
        anchors.fill: parent
        visible: false
        layer.enabled: true

        Rectangle {
            anchors.fill: parent
            radius: root.radius
            color: "#ffffff"
            antialiasing: true
        }
    }

    MultiEffect {
        anchors.fill: parent
        source: image
        maskEnabled: true
        maskSource: mask
        autoPaddingEnabled: false
        visible: image.status === Image.Ready
    }
}
