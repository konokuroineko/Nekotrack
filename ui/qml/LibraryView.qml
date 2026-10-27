import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts

Item {
    id: root
    property var bridge: qmlBridge

    ColumnLayout {
        anchors.fill: parent
        spacing: 18

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 38
            Layout.rightMargin: 38
            Layout.topMargin: 32
            spacing: 2

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    text: "Library"
                    color: bridge.primaryColor
                    font.pixelSize: 32
                    font.weight: Font.Black
                }
                Text {
                    text: bridge.visibleCount + (bridge.visibleCount === 1 ? " title" : " titles")
                    color: bridge.mutedColor
                    font.pixelSize: 12
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 38
            Layout.rightMargin: 38
            Layout.preferredHeight: 58
            radius: 14
            color: bridge.surfaceColor

            Row {
                anchors.fill: parent
                anchors.leftMargin: 9
                anchors.rightMargin: 9
                anchors.topMargin: 8
                anchors.bottomMargin: 8
                spacing: 6

                Repeater {
                    model: ["All", "Watching", "Completed", "Planned"]
                    delegate: Item {
                        required property string modelData
                        width: label.implicitWidth + 30
                        height: parent.height

                        Rectangle {
                            anchors.fill: parent
                            radius: 9
                            color: bridge.libraryFilter === modelData ? bridge.accentSoftColor : "transparent"
                            border.width: bridge.libraryFilter === modelData ? 1 : 0
                            border.color: bridge.selectedFrameColor
                        }
                        Text {
                            id: label
                            anchors.centerIn: parent
                            text: modelData
                            color: bridge.libraryFilter === modelData ? bridge.selectedTextColor : bridge.secondaryColor
                            font.pixelSize: 13
                            font.weight: bridge.libraryFilter === modelData ? Font.Bold : Font.DemiBold
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: bridge.setLibraryFilter(modelData)
                        }
                    }
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 38
            Layout.rightMargin: 38
            Layout.bottomMargin: 30

            GridView {
                id: grid
                anchors.fill: parent
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: bridge.libraryModel
                cellWidth: bridge.cardSize + bridge.cardGap + 8
                cellHeight: bridge.coverHeight + 8 + bridge.titleHeight + bridge.seriesHeight + bridge.metadataHeight + 4 + 30
                reuseItems: true

                delegate: Item {
                    id: card
                    required property int workId
                    required property string title
                    required property string fullTitle
                    required property string mediaType
                    required property string format
                    required property int startYear
                    required property string coverSource
                    required property int coverCacheWorkId
                    required property string status
                    required property int seriesCount
                    required property string bundleSummary
                    width: grid.cellWidth - bridge.cardGap
                    height: grid.cellHeight - 30
                    property bool hovered: false
                    property bool hasMetadata: format.length > 0 || startYear > 0
                    property real visualHeight: bridge.coverHeight + 8 + bridge.titleHeight
                        + ((seriesCount > 1 || hasMetadata) ? bridge.seriesHeight : 0)
                        + (hasMetadata ? bridge.metadataHeight : 0) + 4

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: card.visualHeight
                        radius: bridge.cornerRadius + 2
                        color: card.hovered && bridge.hoverHighlight ? bridge.surfaceHoverColor : "transparent"
                        border.width: 2
                        border.color: bridge.frameColor
                    }

                    Column {
                        anchors.fill: parent
                        anchors.margins: 2
                        spacing: 0

                        Item {
                            width: bridge.cardSize
                            height: bridge.coverHeight

                            Image {
                                id: cover
                                x: 2
                                y: 2
                                width: parent.width - 4
                                height: parent.height - 4
                                source: card.coverSource
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                cache: true
                                visible: false
                                property bool cacheRequested: false
                                onSourceChanged: cacheRequested = false
                                onStatusChanged: {
                                    if (status === Image.Ready && !cacheRequested) {
                                        var sourceText = source.toString()
                                        if (sourceText.indexOf("http://") === 0 || sourceText.indexOf("https://") === 0) {
                                            cacheRequested = true
                                            bridge.requestCoverCache(card.coverCacheWorkId, sourceText)
                                        }
                                    }
                                }
                            }
                            MultiEffect {
                                id: roundedCover
                                x: cover.x
                                y: cover.y
                                width: cover.width
                                height: cover.height
                                source: cover
                                maskEnabled: true
                                autoPaddingEnabled: false
                                maskSource: Rectangle {
                                    width: cover.width
                                    height: cover.height
                                    radius: bridge.cornerRadius
                                    color: "white"
                                    antialiasing: true
                                    visible: false
                                    layer.enabled: true
                                }
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

                        Item {
                            width: 1
                            height: 8
                        }

                        Text {
                            width: bridge.cardSize - 4
                            height: bridge.titleHeight
                            text: card.title
                            color: bridge.primaryColor
                            font.pixelSize: bridge.fontSize
                            font.weight: Font.Bold
                            wrapMode: Text.NoWrap
                            elide: Text.ElideNone
                            verticalAlignment: Text.AlignTop
                            ToolTip.visible: card.hovered
                            ToolTip.text: card.fullTitle
                        }
                        Item {
                            width: 1
                            height: (card.seriesCount <= 1 && card.hasMetadata) ? bridge.seriesHeight : 0
                        }

                        Text {
                            width: bridge.cardSize - 4
                            height: visible ? bridge.seriesHeight : 0
                            visible: card.seriesCount > 1
                            text: card.bundleSummary.length > 0 ? card.bundleSummary : (card.seriesCount + " entries")
                            color: bridge.primaryColor
                            font.pixelSize: 10
                            font.weight: Font.Bold
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }
                        Text {
                            width: bridge.cardSize - 4
                            height: visible ? bridge.metadataHeight : 0
                            visible: card.hasMetadata
                            text: {
                                var parts = []
                                if (card.format.length > 0)
                                    parts.push(card.format.charAt(0) + card.format.slice(1).toLowerCase())
                                if (card.startYear > 0)
                                    parts.push(card.startYear.toString())
                                return parts.join("  ·  ")
                            }
                            color: bridge.mutedColor
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }

                    Menu {
                        id: cardMenu
                        MenuItem {
                            text: "Edit bundle appearance"
                            visible: card.seriesCount > 1
                            onTriggered: bridge.requestEditBundle(card.workId)
                        }
                        MenuItem {
                            text: "Delete from Library"
                            onTriggered: bridge.requestDeleteWork(card.workId)
                        }
                    }

                    MouseArea {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: card.visualHeight
                        z: 2
                        hoverEnabled: true
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onEntered: card.hovered = true
                        onExited: card.hovered = false
                        onClicked: {
                            if (mouse.button === Qt.LeftButton)
                                bridge.requestOpenWork(card.workId)
                            else if (mouse.button === Qt.RightButton)
                                cardMenu.popup()
                        }
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                width: Math.min(parent.width - 40, 420)
                visible: bridge.visibleCount === 0
                text: "Nothing here yet\n\nAdd titles from Search to build your collection."
                color: bridge.mutedColor
                font.pixelSize: 15
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }
        }
    }
}
