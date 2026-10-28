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
            color: bridge.surfaceFillColor

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
                    id: libraryCard
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

                    PosterCard {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        bridge: root.bridge
                        workId: libraryCard.workId
                        title: libraryCard.title
                        fullTitle: libraryCard.fullTitle
                        coverSource: libraryCard.coverSource
                        coverCacheWorkId: libraryCard.coverCacheWorkId
                        mediaType: libraryCard.mediaType
                        format: libraryCard.format
                        startYear: libraryCard.startYear
                        status: libraryCard.status
                        seriesCount: libraryCard.seriesCount
                        bundleSummary: libraryCard.bundleSummary
                        isInLibrary: true
                        showMenu: true
                        onActivated: function(workId) { bridge.requestOpenWork(workId) }
                        onEditBundleRequested: function(workId) { bridge.requestEditBundle(workId) }
                        onDeleteRequested: function(workId) { bridge.requestDeleteWork(workId) }
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                width: Math.min(parent.width - 40, 420)
                visible: bridge.libraryLoading
                text: "Loading your Library…"
                color: bridge.mutedColor
                font.pixelSize: 15
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }

            Text {
                anchors.centerIn: parent
                width: Math.min(parent.width - 40, 420)
                visible: bridge.visibleCount === 0 && !bridge.libraryLoading
                text: "Nothing here yet\n\nAdd titles from Search to build your collection."
                color: bridge.mutedColor
                font.pixelSize: 15
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }
        }
    }
}
