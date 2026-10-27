import QtQuick
import QtQuick.Controls
import QtQuick.Effects

Item {
    id: root
    property var bridge
    property var impressionViewport: null
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
    property string recommendationReason: ""
    property string status: ""
    property int progressEpisodes: 0
    property int episodeTotal: 0
    property bool isInLibrary: false
    property bool showAddButton: false
    property bool showMenu: false
    property bool showRecommendationFeedback: false
    property bool isHovered: false

    signal activated(int workId)
    signal addRequested(int workId)
    signal editBundleRequested(int workId)
    signal deleteRequested(int workId)
    signal recommendationFeedbackRequested(int workId, string feedback)

    readonly property int posterWidth: bridge.cardSize
    readonly property int posterHeight: bridge.coverHeight
    readonly property int titleHeight: bridge.titleHeight
    readonly property int seriesHeight: bridge.seriesHeight
    readonly property int metaHeight: bridge.metadataHeight
    readonly property bool hasMetadata: format.length > 0 || startYear > 0
    readonly property int reasonHeight: recommendationReason.length > 0
        ? Math.min(48, reasonLabel.implicitHeight) : 0
    readonly property int contentHeight: posterHeight + 8 + titleHeight
        + (recommendationReason.length > 0
            ? 5 + reasonHeight + ((seriesCount > 1 || hasMetadata) ? 5 : 0)
                + (seriesCount > 1 ? seriesHeight : 0)
                + ((seriesCount > 1 && hasMetadata) ? 5 : 0)
            : ((seriesCount > 1 || hasMetadata) ? seriesHeight : 0))
        + (hasMetadata ? metaHeight : 0)
        + 4
    readonly property int fixedHeight: contentHeight + (showAddButton ? 38 : 0)

    width: posterWidth + 8
    height: fixedHeight

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: root.fixedHeight
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
                x: 2
                y: 2
                width: parent.width - 4
                height: parent.height - 4
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
                x: 2
                y: 2
                width: parent.width - 4
                height: parent.height - 4
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
            width: root.posterWidth - (root.showRecommendationFeedback ? 30 : 0)
            height: root.titleHeight
            text: root.title
            color: bridge.primaryColor
            font.pixelSize: bridge.fontSize
            font.weight: Font.Bold
            wrapMode: Text.NoWrap
            elide: Text.ElideRight
            verticalAlignment: Text.AlignTop
            ToolTip.visible: root.isHovered
            ToolTip.text: root.fullTitle
        }

        Item {
            width: 1
            height: root.recommendationReason.length > 0 ? 5
                : ((root.seriesCount <= 1 && root.hasMetadata) ? root.seriesHeight : 0)
        }

        Text {
            id: reasonLabel
            width: root.posterWidth
            height: root.reasonHeight
            visible: root.recommendationReason.length > 0
            text: root.recommendationReason
            color: bridge.secondaryColor
            font.pixelSize: Math.max(9, bridge.fontSize - 2)
            wrapMode: Text.WordWrap
            maximumLineCount: 3
            elide: Text.ElideRight
            clip: true
        }

        Item {
            width: 1
            height: (root.recommendationReason.length > 0
                     && (root.seriesCount > 1 || root.hasMetadata)) ? 5 : 0
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

        Item {
            width: 1
            height: (root.recommendationReason.length > 0
                     && root.seriesCount > 1 && root.hasMetadata) ? 5 : 0
        }

        Text {
            width: root.posterWidth
            height: visible ? root.metaHeight : 0
            visible: root.hasMetadata
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

    ToolButton {
        visible: root.showRecommendationFeedback
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.rightMargin: 5
        anchors.topMargin: root.posterHeight + 7
        width: 27
        height: root.titleHeight
        z: 4
        text: "⋮"
        font.pixelSize: 18
        ToolTip.visible: hovered
        ToolTip.text: "Recommendation preferences"
        onClicked: cardMenu.popup()
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
            text: "I want more like this"
            visible: root.showRecommendationFeedback
            onTriggered: root.recommendationFeedbackRequested(root.workId, "more_like_this")
        }
        MenuItem {
            text: "I don't want anything like this"
            visible: root.showRecommendationFeedback
            onTriggered: root.recommendationFeedbackRequested(root.workId, "less_like_this")
        }
        MenuItem {
            text: "Don't recommend this title"
            visible: root.showRecommendationFeedback
            onTriggered: root.recommendationFeedbackRequested(root.workId, "never_show")
        }
        MenuItem {
            text: "Edit bundle appearance"
            visible: root.showMenu && root.isInLibrary && root.seriesCount > 1
            onTriggered: root.editBundleRequested(root.workId)
        }
        MenuItem {
            text: "Delete from Library"
            visible: root.showMenu && root.isInLibrary
            onTriggered: root.deleteRequested(root.workId)
        }
    }

    Timer {
        id: impressionTimer
        interval: 220
        repeat: false
        running: root.showRecommendationFeedback
        onTriggered: {
            var viewport = root.impressionViewport
            if (viewport
                    && root.y + root.height > viewport.contentY
                    && root.y < viewport.contentY + viewport.height) {
                bridge.recordRecommendationImpression(root.workId)
            }
        }
    }

    Connections {
        target: root.impressionViewport
        function onContentYChanged() { impressionTimer.restart() }
    }

    onWorkIdChanged: impressionTimer.restart()

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
