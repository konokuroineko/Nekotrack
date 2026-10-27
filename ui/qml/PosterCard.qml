import QtQuick
import QtQuick.Controls
import QtQuick.Effects

Item {
    id: root

    property var bridge
    property int workId: 0
    property string title: "Untitled"
    property string fullTitle: title
    property string coverSource: ""
    property int coverCacheWorkId: workId
    property string mediaType: "UNKNOWN"
    property string format: ""
    property int startYear: 0
    property int seriesCount: 1
    property string bundleSummary: ""
    property string status: ""
    property int progressEpisodes: 0
    property int episodeTotal: 0
    property bool isInLibrary: false
    property bool showAddButton: false
    property bool showMenu: false
    property bool isHovered: false

    signal activated(int workId)
    signal addRequested(int workId)
    signal editBundleRequested(int workId)
    signal deleteRequested(int workId)

    readonly property int posterWidth: bridge.cardSize
    readonly property int posterHeight: bridge.coverHeight
    readonly property int titleHeight: bridge.titleHeight
    readonly property int seriesHeight: bridge.seriesHeight
    readonly property int metaHeight: bridge.metadataHeight
    readonly property int contentHeight: posterHeight + 8 + titleHeight
        + ((seriesCount > 1 || format.length > 0 || startYear > 0) ? seriesHeight : 0)
        + ((format.length > 0 || startYear > 0) ? metaHeight : 0) + 4
    readonly property int fixedHeight: contentHeight + (showAddButton ? 38 : 0)

    width: posterWidth + 8
    height: fixedHeight

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: root.contentHeight
        radius: bridge.cornerRadius + 2
        color: root.isHovered && bridge.hoverHighlight ? bridge.surfaceHoverColor : "transparent"
        border.width: 2
        border.color: bridge.frameColor
    }

    Column {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.leftMargin: 4
        spacing: 0

        Item {
            width: root.posterWidth
            height: root.posterHeight

            Image {
                id: cover
                anchors.fill: parent
                source: root.coverSource
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true

                layer.enabled: true
                layer.effect: MultiEffect {
                    maskEnabled: true
                    autoPaddingEnabled: false
                    maskSource: Rectangle {
                        width: cover.width
                        height: cover.height
                        radius: bridge.cornerRadius
                        color: "white"
                        layer.enabled: true
                    }
                }

                onStatusChanged: {
                    if (status === Image.Ready) {
                        var sourceText = source.toString()
                        if ((sourceText.indexOf("http://") === 0 || sourceText.indexOf("https://") === 0)
                                && !cacheRequested) {
                            cacheRequested = true
                            bridge.requestCoverCache(root.coverCacheWorkId, sourceText)
                        }
                    }
                }
                property bool cacheRequested: false
                onSourceChanged: cacheRequested = false
            }

            Rectangle {
                anchors.fill: parent
                radius: bridge.cornerRadius
                color: "transparent"
                border.width: 3
                border.color: bridge.frameColor
            }

            Text {
                anchors.centerIn: parent
                visible: cover.status === Image.Error || cover.status === Image.Null
                text: "No cover"
                color: bridge.mutedColor
                font.pixelSize: 12
            }
        }

        Item { width: 1; height: 8 }

        Text {
            width: root.posterWidth
            height: root.titleHeight
            text: root.title
            color: bridge.primaryColor
            font.pixelSize: bridge.fontSize
            font.weight: Font.Bold
            wrapMode: Text.NoWrap
            elide: Text.ElideNone
            verticalAlignment: Text.AlignTop
            ToolTip.visible: root.isHovered
            ToolTip.text: root.fullTitle
        }

        Item {
            width: 1
            height: ((root.seriesCount <= 1
                      && (root.format.length > 0 || root.startYear > 0))
                      || root.seriesCount > 1) ? root.seriesHeight : 0
        }

        Text {
            width: root.posterWidth
            height: visible ? root.seriesHeight : 0
            visible: root.seriesCount > 1
            text: root.bundleSummary.length > 0 ? root.bundleSummary : (root.seriesCount + " entries")
            color: bridge.primaryColor
            font.pixelSize: 10
            font.weight: Font.Bold
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }

        Text {
            width: root.posterWidth
            height: visible ? root.metaHeight : 0
            visible: root.format.length > 0 || root.startYear > 0
            text: {
                var parts = []
                if (root.format.length > 0)
                    parts.push(root.format.charAt(0) + root.format.slice(1).toLowerCase())
                if (root.startYear > 0)
                    parts.push(root.startYear.toString())
                return parts.join("  ·  ")
            }
            color: bridge.mutedColor
            font.pixelSize: 11
            elide: Text.ElideRight
        }
    }

    Button {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.topMargin: root.contentHeight + 2
        height: 32
        visible: root.showAddButton
        enabled: !root.isInLibrary
        z: 3
        text: root.isInLibrary ? "In Library" : "+  Add to Library"
        onClicked: root.addRequested(root.workId)
    }

    Menu {
        id: cardMenu
        MenuItem {
            text: "Edit bundle appearance"
            visible: root.seriesCount > 1
            onTriggered: root.editBundleRequested(root.workId)
        }
        MenuItem {
            text: "Delete from Library"
            onTriggered: root.deleteRequested(root.workId)
        }
    }

    MouseArea {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: root.contentHeight
        z: 2
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onEntered: root.isHovered = true
        onExited: root.isHovered = false
        onClicked: {
            if (mouse.button === Qt.LeftButton)
                root.activated(root.workId)
            else if (mouse.button === Qt.RightButton && root.showMenu)
                cardMenu.popup()
        }
    }
}
