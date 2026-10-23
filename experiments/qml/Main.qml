import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

ApplicationWindow {
    id: root

    visible: true
    width: 1240
    height: 820
    minimumWidth: 760
    minimumHeight: 600
    title: qsTr("NekoTrack — modernization preview")
    color: "#0D0E14"

    property int activePage: 0
    property string formatFilter: "All"
    property string statusFilter: "All"
    property string statusMessage: qsTr("Design preview · sample data only · nothing is saved.")
    property string selectedTitle: ""
    property string selectedFormat: ""
    property string selectedDescription: ""
    property string selectedProgress: ""
    property string selectedGlyph: ""
    property string selectedFilterContext: ""
    property var navItems: [
        { label: qsTr("Home"), glyph: "⌂" },
        { label: qsTr("Library"), glyph: "▤" },
        { label: qsTr("Search"), glyph: "⌕" },
        { label: qsTr("Calendar"), glyph: "▦" },
        { label: qsTr("Favorites"), glyph: "☆" },
        { label: qsTr("Settings"), glyph: "⚙" }
    ]
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
        const query = globalSearch.text.trim().toLocaleLowerCase()
        resultsModel.clear()
        progressModel.clear()

        for (let index = 0; index < allResults.length; ++index) {
            const entry = allResults[index]
            const searchable = (entry.title + " " + entry.mediaFormat + " " +
                                entry.descriptionText).toLocaleLowerCase()
            const status = entry.progressText.split(" · ")[0]
            const matchesQuery = query.length === 0 || searchable.indexOf(query) !== -1
            const matchesFormat = formatFilter === "All" || entry.mediaFormat === formatFilter
            const matchesStatus = statusFilter === "All" || status === statusFilter

            if (matchesQuery && matchesFormat && matchesStatus)
                resultsModel.append(entry)

            if (entry.progressText.indexOf("Watching ·") === 0 ||
                    entry.progressText.indexOf("Reading ·") === 0)
                progressModel.append(entry)
        }

        if (resultsModel.count === 0) {
            statusMessage = qsTr("No sample titles match the current search and filters.")
        } else {
            statusMessage = qsTr("%1 sample title(s) · local preview data only.")
                .arg(resultsModel.count)
        }
    }

    function openResult(title, mediaFormat, descriptionText, progressText, accentGlyph) {
        selectedTitle = title
        selectedFormat = mediaFormat
        selectedDescription = descriptionText
        selectedProgress = progressText
        selectedGlyph = accentGlyph
        selectedFilterContext = globalSearch.text
        activePage = 6
        statusMessage = qsTr("%1 selected · preview only; no library changes were made.").arg(title)
    }

    function titleForPage(index) {
        if (index === 6)
            return qsTr("Title details")
        return navItems[index].label
    }

    ListModel { id: resultsModel }
    ListModel { id: progressModel }

    Component.onCompleted: refreshResults()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 14

            Rectangle {
                id: sidebar
                Layout.preferredWidth: 190
                Layout.fillHeight: true
                radius: 16
                color: "#13141E"
                border.color: "#292A3A"
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Rectangle {
                            Layout.preferredWidth: 38
                            Layout.preferredHeight: 38
                            radius: 12
                            color: "#8B6DE0"

                            Text {
                                anchors.centerIn: parent
                                text: "N"
                                color: "#FFFFFF"
                                font.pixelSize: 21
                                font.bold: true
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1

                            Text {
                                text: "NekoTrack"
                                color: "#F4F1FF"
                                font.pixelSize: 16
                                font.weight: Font.DemiBold
                            }

                            Text {
                                text: qsTr("PERSONAL LIBRARY")
                                color: "#948BAE"
                                font.pixelSize: 8
                                font.letterSpacing: 1
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: "#292A3A"
                    }

                    Text {
                        text: qsTr("WORKSPACE")
                        color: "#827C97"
                        font.pixelSize: 10
                        font.bold: true
                        font.letterSpacing: 1.2
                        leftPadding: 8
                    }

                    Repeater {
                        model: root.navItems

                        delegate: Button {
                            id: navButton
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            implicitHeight: 42
                            text: modelData.glyph + "   " + modelData.label
                            checkable: true
                            checked: root.activePage === index
                            focusPolicy: Qt.StrongFocus
                            Accessible.name: modelData.label
                            Accessible.description: qsTr("Show the %1 page in the design preview.").arg(modelData.label)
                            onClicked: root.activePage = index

                            contentItem: Text {
                                text: navButton.text
                                color: navButton.checked ? "#F4F1FF" : "#B7B1CA"
                                font.pixelSize: 13
                                font.weight: navButton.checked ? Font.DemiBold : Font.Normal
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 8
                            }

                            background: Rectangle {
                                radius: 9
                                color: navButton.checked ? "#302747" :
                                       (navButton.hovered ? "#202131" : "transparent")
                                border.color: navButton.visualFocus ? "#E0D5FF" :
                                              (navButton.checked ? "#554477" : "transparent")
                                border.width: navButton.visualFocus || navButton.checked ? 1 : 0
                            }
                        }
                    }

                    Item { Layout.fillHeight: true }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 66
                        radius: 10
                        color: "#1B1C29"
                        border.color: "#343247"

                        Column {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 5

                            Text {
                                text: qsTr("PREVIEW BUILD")
                                color: "#D8C8FF"
                                font.pixelSize: 10
                                font.bold: true
                            }

                            Text {
                                width: parent.width
                                text: qsTr("Sample data · isolated from your library")
                                color: "#A7A0BA"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 10

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 66
                    radius: 14
                    color: "#13141E"
                    border.color: "#292A3A"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 18
                        anchors.rightMargin: 16
                        spacing: 14

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2

                            Text {
                                text: root.titleForPage(root.activePage)
                                color: "#F4F1FF"
                                font.pixelSize: 21
                                font.weight: Font.DemiBold
                            }

                            Text {
                                text: qsTr("Discover, track and revisit the stories you enjoy")
                                color: "#A7A0BA"
                                font.pixelSize: 11
                            }
                        }

                        TextField {
                            id: globalSearch
                            Layout.preferredWidth: 260
                            implicitHeight: 40
                            placeholderText: qsTr("Search sample titles…")
                            Accessible.name: qsTr("Search sample titles")
                            Accessible.description: qsTr("Filters the sample results by title, format or description.")
                            selectByMouse: true
                            focusPolicy: Qt.StrongFocus
                            color: "#F4F1FF"
                            placeholderTextColor: "#8D879F"
                            leftPadding: 12
                            rightPadding: 12
                            font.pixelSize: 12
                            onTextChanged: root.refreshResults()

                            background: Rectangle {
                                radius: 9
                                color: "#1A1B28"
                                border.color: globalSearch.activeFocus ? "#D0C1FF" : "#37374A"
                                border.width: globalSearch.activeFocus ? 2 : 1
                            }
                        }

                        Rectangle {
                            Layout.preferredWidth: 92
                            Layout.preferredHeight: 31
                            radius: 8
                            color: "#202A27"
                            border.color: "#354B43"

                            RowLayout {
                                anchors.centerIn: parent
                                spacing: 6

                                Rectangle {
                                    Layout.preferredWidth: 6
                                    Layout.preferredHeight: 6
                                    radius: 3
                                    color: "#7BD4A8"
                                }

                                Text {
                                    text: qsTr("Local preview")
                                    color: "#A7E0C2"
                                    font.pixelSize: 10
                                }
                            }
                        }
                    }
                }

                StackLayout {
                    id: pageStack
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: root.activePage

                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 16

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4

                                Text {
                                    text: qsTr("Your anime & reading space")
                                    color: "#F4F1FF"
                                    font.pixelSize: 25
                                    font.weight: Font.DemiBold
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: qsTr("Continue where you left off, then find your next favorite.")
                                    color: "#AAA4BD"
                                    font.pixelSize: 13
                                    wrapMode: Text.WordWrap
                                }
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                columns: 3
                                rowSpacing: 10
                                columnSpacing: 10

                                Repeater {
                                    model: [
                                        { value: "4", label: qsTr("SAMPLE TITLES"), glyph: "▤" },
                                        { value: "1", label: qsTr("IN PROGRESS"), glyph: "▶" },
                                        { value: "2", label: qsTr("MEDIA FORMATS"), glyph: "◈" }
                                    ]

                                    delegate: Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 76
                                        radius: 12
                                        color: "#171824"
                                        border.color: "#2E2D41"

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 12
                                            spacing: 10

                                            Rectangle {
                                                Layout.preferredWidth: 34
                                                Layout.preferredHeight: 34
                                                radius: 10
                                                color: "#2B2440"
                                                Text {
                                                    anchors.centerIn: parent
                                                    text: modelData.glyph
                                                    color: "#D8C8FF"
                                                    font.pixelSize: 17
                                                }
                                            }

                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 2
                                                Text {
                                                    text: modelData.value
                                                    color: "#F4F1FF"
                                                    font.pixelSize: 20
                                                    font.bold: true
                                                }
                                                Text {
                                                    text: modelData.label
                                                    color: "#9790AB"
                                                    font.pixelSize: 9
                                                    font.bold: true
                                                    font.letterSpacing: 0.6
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    text: qsTr("Continue watching & reading")
                                    color: "#F0ECFC"
                                    font.pixelSize: 17
                                    font.weight: Font.DemiBold
                                }

                                Item { Layout.fillWidth: true }

                                Button {
                                    text: qsTr("View library  ›")
                                    Accessible.name: qsTr("View the sample library")
                                    onClicked: root.activePage = 1
                                    flat: true
                                    contentItem: Text {
                                        text: parent.text
                                        color: "#D8C8FF"
                                        font.pixelSize: 11
                                        horizontalAlignment: Text.AlignRight
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                }
                            }

                            ListView {
                                id: continueList
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                spacing: 8
                                model: progressModel
                                boundsBehavior: Flickable.StopAtBounds
                                Accessible.name: qsTr("Continue watching and reading")
                                delegate: NekoResultCard {
                                    width: ListView.view.width
                                    onClicked: root.openResult(title, mediaFormat, descriptionText, progressText, accentGlyph)
                                }
                            }
                        }
                    }

                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 14

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Text {
                                    text: qsTr("Your library")
                                    color: "#F4F1FF"
                                    font.pixelSize: 24
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    text: qsTr("Filter and revisit your saved anime, manga and light novels.")
                                    color: "#AAA4BD"
                                    font.pixelSize: 12
                                }
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: 8

                                Repeater {
                                    model: ["All", "Watching", "Reading", "Completed", "Planned"]
                                    delegate: Button {
                                        required property string modelData
                                        text: modelData
                                        checkable: true
                                        checked: root.statusFilter === modelData
                                        Accessible.name: qsTr("Filter library by %1").arg(modelData)
                                        onClicked: {
                                            root.statusFilter = modelData
                                            root.refreshResults()
                                        }
                                        contentItem: Text {
                                            text: parent.text
                                            color: parent.checked ? "#F4F1FF" : "#B7B1CA"
                                            font.pixelSize: 11
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                        background: Rectangle {
                                            radius: 9
                                            color: parent.checked ? "#302747" : "#171824"
                                            border.color: parent.checked ? "#68558C" : "#303142"
                                        }
                                    }
                                }
                            }

                            ListView {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                spacing: 8
                                model: resultsModel
                                boundsBehavior: Flickable.StopAtBounds
                                Accessible.name: qsTr("Sample library results")
                                delegate: NekoResultCard {
                                    width: ListView.view.width
                                    onClicked: root.openResult(title, mediaFormat, descriptionText, progressText, accentGlyph)
                                }
                            }
                        }
                    }

                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 14

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Text {
                                    text: qsTr("Find something to watch or read")
                                    color: "#F4F1FF"
                                    font.pixelSize: 24
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    text: qsTr("Search all sample media by title, format or description.")
                                    color: "#AAA4BD"
                                    font.pixelSize: 12
                                }
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: 8
                                Repeater {
                                    model: ["All", "Anime", "Manga", "Light Novel"]
                                    delegate: Button {
                                        required property string modelData
                                        text: modelData
                                        checkable: true
                                        checked: root.formatFilter === modelData
                                        Accessible.name: qsTr("Filter search by %1").arg(modelData)
                                        onClicked: {
                                            root.formatFilter = modelData
                                            root.refreshResults()
                                        }
                                        contentItem: Text {
                                            text: parent.text
                                            color: parent.checked ? "#F4F1FF" : "#B7B1CA"
                                            font.pixelSize: 11
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                        background: Rectangle {
                                            radius: 9
                                            color: parent.checked ? "#302747" : "#171824"
                                            border.color: parent.checked ? "#68558C" : "#303142"
                                        }
                                    }
                                }

                                Button {
                                    text: qsTr("Clear filters")
                                    Accessible.name: qsTr("Clear search and filters")
                                    onClicked: {
                                        globalSearch.clear()
                                        root.formatFilter = "All"
                                        root.statusFilter = "All"
                                        root.refreshResults()
                                    }
                                }
                            }

                            ListView {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                spacing: 8
                                model: resultsModel
                                boundsBehavior: Flickable.StopAtBounds
                                Accessible.name: qsTr("Search results")
                                Accessible.description: qsTr("Use Tab to move through the result cards and press Enter or Space to open a title.")
                                delegate: NekoResultCard {
                                    width: ListView.view.width
                                    onClicked: root.openResult(title, mediaFormat, descriptionText, progressText, accentGlyph)
                                }
                            }
                        }
                    }

                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 14
                            Text {
                                text: qsTr("Upcoming releases")
                                color: "#F4F1FF"
                                font.pixelSize: 24
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                text: qsTr("A calendar-first layout for episode dates and reminders. These dates are illustrative sample data.")
                                color: "#AAA4BD"
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }

                            Repeater {
                                model: [
                                    { date: "FRI · 24", month: "OCT", title: "Frieren: Beyond Journey's End", detail: "Episode 18 · Reminder enabled", glyph: "F" },
                                    { date: "SAT · 25", month: "OCT", title: "The Apothecary Diaries", detail: "Next episode · No reminder", glyph: "A" },
                                    { date: "MON · 27", month: "OCT", title: "Witch Hat Atelier", detail: "Reading plan · Sample item", glyph: "W" }
                                ]

                                delegate: Rectangle {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 82
                                    radius: 12
                                    color: "#171824"
                                    border.color: "#2E2D41"

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 14

                                        Rectangle {
                                            Layout.preferredWidth: 54
                                            Layout.preferredHeight: 56
                                            radius: 9
                                            color: "#2B2440"
                                            Column {
                                                anchors.centerIn: parent
                                                spacing: 2
                                                Text {
                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                    text: modelData.month
                                                    color: "#D8C8FF"
                                                    font.pixelSize: 9
                                                    font.bold: true
                                                }
                                                Text {
                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                    text: modelData.date.split(" · ")[1]
                                                    color: "#F4F1FF"
                                                    font.pixelSize: 15
                                                    font.bold: true
                                                }
                                            }
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 5
                                            Text {
                                                text: modelData.title
                                                color: "#F4F1FF"
                                                font.pixelSize: 13
                                                font.weight: Font.DemiBold
                                                elide: Text.ElideRight
                                                Layout.fillWidth: true
                                            }
                                            Text {
                                                text: modelData.date.split(" · ")[0] + "  ·  " + modelData.detail
                                                color: "#A7A0BA"
                                                font.pixelSize: 11
                                                elide: Text.ElideRight
                                                Layout.fillWidth: true
                                            }
                                        }

                                        Button {
                                            text: qsTr("Remind me")
                                            Accessible.name: qsTr("Toggle sample reminder for %1").arg(modelData.title)
                                            onClicked: root.statusMessage = qsTr("Preview only · reminders are not saved.")
                                        }
                                    }
                                }
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 14
                            Text {
                                text: qsTr("People and characters")
                                color: "#F4F1FF"
                                font.pixelSize: 24
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                text: qsTr("Keep character, voice-actor and staff favorites separate from work progress.")
                                color: "#AAA4BD"
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }

                            Repeater {
                                model: [
                                    { glyph: "M", name: "Maomao", role: "Character · The Apothecary Diaries", detail: "Favorite profile · sample only" },
                                    { glyph: "F", name: "Frieren", role: "Character · Frieren: Beyond Journey's End", detail: "Favorite profile · sample only" },
                                    { glyph: "S", name: "Series composer", role: "Production staff", detail: "Favorite credit · sample only" }
                                ]

                                delegate: Rectangle {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 82
                                    radius: 12
                                    color: "#171824"
                                    border.color: "#2E2D41"
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 12
                                        Rectangle {
                                            Layout.preferredWidth: 46
                                            Layout.preferredHeight: 46
                                            radius: 23
                                            color: "#302747"
                                            border.color: "#554477"
                                            Text {
                                                anchors.centerIn: parent
                                                text: modelData.glyph
                                                color: "#E4D9FF"
                                                font.pixelSize: 19
                                                font.bold: true
                                            }
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 4
                                            Text {
                                                text: modelData.name
                                                color: "#F4F1FF"
                                                font.pixelSize: 14
                                                font.weight: Font.DemiBold
                                            }
                                            Text {
                                                text: modelData.role
                                                color: "#B8B2C8"
                                                font.pixelSize: 11
                                            }
                                            Text {
                                                text: modelData.detail
                                                color: "#8F88A5"
                                                font.pixelSize: 10
                                            }
                                        }
                                        Text {
                                            text: "☆"
                                            color: "#D8C8FF"
                                            font.pixelSize: 23
                                        }
                                    }
                                }
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 14
                            Text {
                                text: qsTr("Preferences")
                                color: "#F4F1FF"
                                font.pixelSize: 24
                                font.weight: Font.DemiBold
                            }
                            Text {
                                text: qsTr("A unified settings layout for appearance, accessibility and updates.")
                                color: "#AAA4BD"
                                font.pixelSize: 12
                            }

                            Repeater {
                                model: [
                                    { title: "Appearance", description: "Theme, light mode, accent color and background." },
                                    { title: "Accessibility", description: "Text scaling, keyboard focus, contrast and reduced motion." },
                                    { title: "Language", description: "Interface language, date format and right-to-left layout." },
                                    { title: "Updates", description: "Stable/preview channel, update checks and safe rollback." },
                                    { title: "Diagnostics", description: "Export one redacted diagnostic report when troubleshooting." }
                                ]

                                delegate: Rectangle {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 72
                                    radius: 12
                                    color: "#171824"
                                    border.color: "#2E2D41"
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 14
                                        spacing: 5
                                        Text {
                                            text: modelData.title
                                            color: "#F4F1FF"
                                            font.pixelSize: 13
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            text: modelData.description
                                            color: "#A7A0BA"
                                            font.pixelSize: 11
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                        }
                                    }
                                }
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 18

                            Button {
                                text: "‹  " + qsTr("Back")
                                Accessible.name: qsTr("Back to the previous page")
                                onClicked: root.activePage = root.navItems.findIndex(item => item.label === qsTr("Search"))
                                contentItem: Text {
                                    text: parent.text
                                    color: "#D8C8FF"
                                    font.pixelSize: 12
                                }
                                background: Rectangle {
                                    radius: 8
                                    color: "#29243E"
                                    border.color: "#514477"
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 20

                                Rectangle {
                                    Layout.preferredWidth: 150
                                    Layout.preferredHeight: 205
                                    radius: 16
                                    color: "#29243E"
                                    border.color: "#514477"
                                    Text {
                                        anchors.centerIn: parent
                                        text: root.selectedGlyph
                                        color: "#D9CCFF"
                                        font.pixelSize: 62
                                        font.bold: true
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 9
                                    Text {
                                        text: root.selectedTitle
                                        color: "#F4F1FF"
                                        font.pixelSize: 25
                                        font.weight: Font.DemiBold
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        text: root.selectedFormat
                                        color: "#D8C8FF"
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        text: root.selectedProgress
                                        color: "#BEB6D2"
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: root.selectedDescription
                                        color: "#AAA4BD"
                                        font.pixelSize: 13
                                        wrapMode: Text.WordWrap
                                    }
                                    Text {
                                        text: qsTr("Prototype detail view")
                                        color: "#7BD4A8"
                                        font.pixelSize: 11
                                        font.bold: true
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 1
                                color: "#303142"
                            }

                            Text {
                                text: qsTr("Future live sections")
                                color: "#F0ECFC"
                                font.pixelSize: 17
                                font.weight: Font.DemiBold
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                columns: 2
                                rowSpacing: 10
                                columnSpacing: 10
                                Repeater {
                                    model: [
                                        { title: "Description", detail: "Synopsis, format and release information" },
                                        { title: "Progress", detail: "Episodes, seasons, volumes and chapters" },
                                        { title: "Relations", detail: "Adaptations, sequels and user-managed bundles" },
                                        { title: "People", detail: "Characters, voice actors and production staff" }
                                    ]
                                    delegate: Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 76
                                        radius: 10
                                        color: "#171824"
                                        border.color: "#2E2D41"
                                        Column {
                                            anchors.fill: parent
                                            anchors.margins: 12
                                            spacing: 5
                                            Text {
                                                text: modelData.title
                                                color: "#F4F1FF"
                                                font.pixelSize: 12
                                                font.weight: Font.DemiBold
                                            }
                                            Text {
                                                text: modelData.detail
                                                color: "#A7A0BA"
                                                font.pixelSize: 10
                                                wrapMode: Text.WordWrap
                                                width: parent.width
                                            }
                                        }
                                    }
                                }
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            radius: 8
            color: "#13141E"
            border.color: "#292A3A"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8
                Rectangle {
                    Layout.preferredWidth: 5
                    Layout.preferredHeight: 5
                    radius: 3
                    color: "#B39AFF"
                }
                Text {
                    Layout.fillWidth: true
                    text: root.statusMessage
                    color: "#A7A0BA"
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
                Text {
                    text: qsTr("EXPERIMENTAL · NO LIVE DATA")
                    color: "#81799A"
                    font.pixelSize: 9
                    font.bold: true
                    font.letterSpacing: 0.7
                }
            }
        }
    }
}
