import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

ApplicationWindow {
    id: root

    visible: true
    width: 1050
    height: 760
    minimumWidth: 650
    minimumHeight: 540
    title: qsTr("NekoTrack — QML prototype")
    color: "#101117"

    property string statusMessage: qsTr("Prototype only — sample data, no changes are saved.")
    property var allResults: [
        {
            title: "Frieren: Beyond Journey's End",
            mediaFormat: "Anime",
            descriptionText: "An elf mage reflects on friendship and time after the end of a hero's journey.",
            progressText: "Watching · Episode 17 of 28",
            accentGlyph: "F"
        },
        {
            title: "The Apothecary Diaries",
            mediaFormat: "Anime",
            descriptionText: "A sharp-minded apothecary solves mysteries in the imperial palace.",
            progressText: "Completed · 24 of 24 episodes",
            accentGlyph: "A"
        },
        {
            title: "Witch Hat Atelier",
            mediaFormat: "Manga",
            descriptionText: "A young girl discovers the hidden rules behind the magic in her world.",
            progressText: "Reading · Volume 6, Chapter 33",
            accentGlyph: "W"
        },
        {
            title: "Re:ZERO -Starting Life in Another World-",
            mediaFormat: "Light Novel",
            descriptionText: "A fantasy story about difficult choices, unexpected allies, and repeated journeys.",
            progressText: "Planned · Volume 1",
            accentGlyph: "R"
        }
    ]

    function refreshResults() {
        const query = searchField.text.trim().toLocaleLowerCase()
        resultsModel.clear()
        for (let index = 0; index < allResults.length; ++index) {
            const entry = allResults[index]
            const searchable = (entry.title + " " + entry.mediaFormat + " " +
                                entry.descriptionText).toLocaleLowerCase()
            if (query.length === 0 || searchable.indexOf(query) !== -1)
                resultsModel.append(entry)
        }
        statusMessage = resultsModel.count === 0
            ? qsTr("No sample titles match this search.")
            : qsTr("%1 sample results · select a card to preview keyboard and focus behavior.")
                .arg(resultsModel.count)
    }

    ListModel {
        id: resultsModel
    }

    Component.onCompleted: refreshResults()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 28
        spacing: 18

        RowLayout {
            Layout.fillWidth: true
            spacing: 14

            Rectangle {
                Layout.preferredWidth: 48
                Layout.preferredHeight: 48
                radius: 15
                color: "#8B6DE0"

                Text {
                    anchors.centerIn: parent
                    text: "N"
                    color: "#FFFFFF"
                    font.pixelSize: 25
                    font.bold: true
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3

                Text {
                    text: "NekoTrack"
                    color: "#F4F1FF"
                    font.pixelSize: 25
                    font.weight: Font.DemiBold
                }

                Text {
                    text: qsTr("Search · experimental Qt Quick interface")
                    color: "#B8B2C8"
                    font.pixelSize: 13
                }
            }

            Rectangle {
                radius: 8
                color: "#29243E"
                border.color: "#514477"
                Layout.preferredHeight: 30
                Layout.preferredWidth: prototypeLabel.implicitWidth + 22

                Text {
                    id: prototypeLabel
                    anchors.centerIn: parent
                    text: qsTr("EXPERIMENT")
                    color: "#D8C8FF"
                    font.pixelSize: 10
                    font.bold: true
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: "#303142"
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 7

            Text {
                text: qsTr("Find something to watch or read")
                color: "#F4F1FF"
                font.pixelSize: 22
                font.weight: Font.DemiBold
            }

            Text {
                text: qsTr("This isolated prototype uses sample data. It does not connect to or modify your library.")
                color: "#B8B2C8"
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            TextField {
                id: searchField
                Layout.fillWidth: true
                implicitHeight: 48
                placeholderText: qsTr("Search titles, formats, or descriptions…")
                Accessible.name: qsTr("Search sample titles")
                Accessible.description: qsTr("Type to filter the sample anime, manga, and light novel results.")
                selectByMouse: true
                focusPolicy: Qt.StrongFocus
                color: "#F4F1FF"
                placeholderTextColor: "#908AA3"
                font.pixelSize: 14
                leftPadding: 14
                rightPadding: 14
                onTextChanged: root.refreshResults()

                background: Rectangle {
                    radius: 10
                    color: "#191B27"
                    border.color: searchField.activeFocus ? "#D0C1FF" : "#3A3B4D"
                    border.width: searchField.activeFocus ? 2 : 1
                }
            }

            Button {
                id: clearButton
                text: qsTr("Clear")
                Accessible.name: qsTr("Clear search")
                Accessible.description: qsTr("Remove the search filter and show every sample result.")
                focusPolicy: Qt.StrongFocus
                implicitHeight: 48
                onClicked: {
                    searchField.clear()
                    searchField.forceActiveFocus()
                }

                contentItem: Text {
                    text: clearButton.text
                    color: clearButton.visualFocus ? "#FFFFFF" : "#E4D9FF"
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }

                background: Rectangle {
                    radius: 10
                    color: clearButton.down ? "#40365B" : (clearButton.hovered ? "#322A48" : "#29243E")
                    border.color: clearButton.visualFocus ? "#E0D5FF" : "#514477"
                    border.width: clearButton.visualFocus ? 2 : 1
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true

            Text {
                text: qsTr("SAMPLE TITLES")
                color: "#B8B2C8"
                font.pixelSize: 11
                font.bold: true
                font.letterSpacing: 1.2
            }

            Item { Layout.fillWidth: true }

            Text {
                text: qsTr("%1 results").arg(resultsModel.count)
                color: "#B8B2C8"
                font.pixelSize: 12
            }
        }

        ListView {
            id: resultsList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 10
            model: resultsModel
            visible: resultsModel.count > 0
            keyNavigationEnabled: true
            keyNavigationWraps: false
            boundsBehavior: Flickable.StopAtBounds
            Accessible.name: qsTr("Search results")
            Accessible.description: qsTr("Filtered sample media results. Tab to a card and press Enter or Space to select it.")

            delegate: NekoResultCard {
                width: ListView.view.width

                onClicked: {
                    root.statusMessage = qsTr("%1 selected — prototype only; no library changes were made.")
                        .arg(title)
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: resultsModel.count === 0

            Column {
                anchors.centerIn: parent
                spacing: 8

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr("No matching sample titles")
                    color: "#F4F1FF"
                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr("Try another search or clear the filter.")
                    color: "#B8B2C8"
                    font.pixelSize: 13
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: "#303142"
        }

        Text {
            Layout.fillWidth: true
            text: root.statusMessage
            color: "#B8B2C8"
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }
    }
}
