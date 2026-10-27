import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts

Item {
    id: root
    property var bridge: appBridge
    property string selectedNavigationPage: {
        if (bridge.currentPage === "work_detail" || bridge.currentPage === "entity_profile" || bridge.currentPage === "relation")
            return "collections"
        return bridge.currentPage
    }

    Rectangle {
        anchors.fill: parent
        color: bridge.backgroundColor
    }

    Image {
        id: backgroundArtwork
        anchors.fill: parent
        source: bridge.backgroundSource
        visible: bridge.backgroundSource.length > 0
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
    }

    Rectangle {
        anchors.fill: parent
        visible: backgroundArtwork.visible
        color: bridge.backgroundOverlayColor
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            id: sidebar
            Layout.preferredWidth: 270
            Layout.minimumWidth: 270
            Layout.maximumWidth: 270
            Layout.fillHeight: true
            color: bridge.sidebarFillColor
            border.width: 0

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.topMargin: 22
                anchors.bottomMargin: 20
                spacing: 5

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 72

                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 4
                        spacing: 0
                        Text {
                            text: "Neko"
                            color: bridge.accentColor
                            font.pixelSize: 29
                            font.weight: Font.Black
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "Track"
                            color: bridge.primaryColor
                            font.pixelSize: 29
                            font.weight: Font.Bold
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: bridge.borderColor
                        opacity: 0.65
                    }
                }

                Item { Layout.preferredHeight: 22 }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 5

                    Repeater {
                        model: [
                            {key: "home", label: "Home", glyph: "⌂"},
                            {key: "collections", label: "Library", glyph: "▣"},
                            {key: "search", label: "Search", glyph: "⌕"},
                            {key: "calendar", label: "Calendar", glyph: "▦"},
                            {key: "favorites", label: "Favorites", glyph: "☆"}
                        ]

                        delegate: Item {
                            id: navItem
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 48

                            Rectangle {
                                anchors.fill: parent
                                radius: 11
                                color: root.selectedNavigationPage === navItem.modelData.key
                                    ? bridge.accentSoftColor : "transparent"
                                border.width: root.selectedNavigationPage === navItem.modelData.key ? 1 : 1
                                border.color: root.selectedNavigationPage === navItem.modelData.key
                                    ? bridge.selectedFrameColor : "transparent"
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 15
                                anchors.rightMargin: 14
                                spacing: 13
                                Text {
                                    text: navItem.modelData.glyph
                                    color: root.selectedNavigationPage === navItem.modelData.key
                                        ? bridge.selectedTextColor : bridge.secondaryColor
                                    font.pixelSize: 21
                                    Layout.preferredWidth: 22
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                Text {
                                    text: navItem.modelData.label
                                    color: root.selectedNavigationPage === navItem.modelData.key
                                        ? bridge.selectedTextColor : bridge.secondaryColor
                                    font.pixelSize: 14
                                    font.weight: root.selectedNavigationPage === navItem.modelData.key
                                        ? Font.Bold : Font.DemiBold
                                    Layout.fillWidth: true
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: bridge.navigate(navItem.modelData.key)
                            }
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 48

                    Rectangle {
                        anchors.fill: parent
                        radius: 11
                        color: root.selectedNavigationPage === "settings"
                            ? bridge.accentSoftColor : "transparent"
                        border.width: 1
                        border.color: root.selectedNavigationPage === "settings"
                            ? bridge.selectedFrameColor : "transparent"
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 15
                        anchors.rightMargin: 14
                        spacing: 13
                        Text {
                            text: "⚙"
                            color: root.selectedNavigationPage === "settings"
                                ? bridge.selectedTextColor : bridge.secondaryColor
                            font.pixelSize: 20
                            Layout.preferredWidth: 22
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        Text {
                            text: "Settings"
                            color: root.selectedNavigationPage === "settings"
                                ? bridge.selectedTextColor : bridge.secondaryColor
                            font.pixelSize: 14
                            font.weight: root.selectedNavigationPage === "settings"
                                ? Font.Bold : Font.DemiBold
                            Layout.fillWidth: true
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bridge.navigate("settings")
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "transparent"

            StackLayout {
                id: pages
                anchors.fill: parent
                currentIndex: {
                    switch (bridge.currentPage) {
                    case "home": return 0
                    case "collections": return 1
                    case "search": return 2
                    case "calendar": return 3
                    case "favorites": return 4
                    case "settings": return 5
                    case "work_detail": return 6
                    case "entity_profile": return 7
                    case "relation": return 6
                    default: return 0
                    }
                }

                // Home
                Item {
                    id: homePage
                    property int homeCardWidth: bridge.cardSize + bridge.cardGap + 8

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 38
                        anchors.rightMargin: 38
                        anchors.topMargin: 32
                        anchors.bottomMargin: 30
                        spacing: 24

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3
                            Text {
                                text: "Home"
                                color: bridge.primaryColor
                                font.pixelSize: 32
                                font.weight: Font.Black
                            }
                            Text {
                                text: "Your anime, manga and light novels in one place."
                                color: bridge.mutedColor
                                font.pixelSize: 12
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 3
                            columnSpacing: 12
                            rowSpacing: 12

                            Repeater {
                                model: [
                                    {title: "In progress", value: bridge.homeStats.inProgress},
                                    {title: "Completed", value: bridge.homeStats.completed},
                                    {title: "Planned", value: bridge.homeStats.planned}
                                ]
                                delegate: Rectangle {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 82
                                    radius: 13
                                    color: bridge.surfaceFillColor
                                    border.width: 1
                                    border.color: bridge.frameColor
                                    Column {
                                        anchors.left: parent.left
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.leftMargin: 17
                                        spacing: 4
                                        Text {
                                            text: modelData.value
                                            color: bridge.primaryColor
                                            font.pixelSize: 24
                                            font.weight: Font.Black
                                        }
                                        Text {
                                            text: modelData.title
                                            color: bridge.mutedColor
                                            font.pixelSize: 11
                                        }
                                    }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: "Continue watching & reading"
                                color: bridge.primaryColor
                                font.pixelSize: 20
                                font.weight: Font.Bold
                                Layout.fillWidth: true
                            }
                            Button {
                                text: "View Library"
                                onClicked: bridge.navigate("collections")
                            }
                        }

                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true

                            GridView {
                                id: continueGrid
                                anchors.fill: parent
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                cellWidth: homePage.homeCardWidth
                                cellHeight: bridge.coverHeight + bridge.titleHeight + bridge.seriesHeight + bridge.metadataHeight + 48
                                model: bridge.homeItems

                                delegate: Item {
                                    required property var modelData
                                    width: continueGrid.cellWidth - bridge.cardGap
                                    height: continueGrid.cellHeight - 24
                                    PosterCard {
                                        bridge: root.bridge
                                        workId: modelData.workId
                                        title: modelData.title
                                        fullTitle: modelData.fullTitle || modelData.title
                                        coverSource: modelData.coverSource || ""
                                        coverCacheWorkId: modelData.coverCacheWorkId || modelData.workId
                                        format: modelData.format || ""
                                        startYear: modelData.startYear || 0
                                        mediaType: modelData.mediaType || ""
                                        seriesCount: modelData.seriesCount || 1
                                        bundleSummary: modelData.bundleSummary || ""
                                        status: modelData.status || ""
                                        progressEpisodes: modelData.progressEpisodes || 0
                                        episodeTotal: modelData.episodeTotal || 0
                                        onActivated: function(workId) { bridge.requestOpenWork(workId) }
                                        onEditBundleRequested: function(workId) { bridge.requestEditBundle(workId) }
                                        onDeleteRequested: function(workId) { bridge.requestDeleteWork(workId) }
                                    }
                                }
                            }

                            Text {
                                anchors.centerIn: parent
                                visible: bridge.homeItems.length === 0
                                width: Math.min(parent.width - 50, 420)
                                text: "Nothing in progress yet.\n\nAdd titles from Search to start tracking them."
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.WordWrap
                                color: bridge.mutedColor
                                font.pixelSize: 15
                            }
                        }
                    }
                }

                // Library; Loader keeps the app shell alive while this view loads.
                Loader {
                    id: libraryLoader
                    active: true
                    source: Qt.resolvedUrl("LibraryView.qml")
                    onLoaded: {
                        if (item)
                            item.bridge = root.bridge
                    }
                }

                // Search
                Item {
                    id: searchPage
                    property string selectedType: ""
                    property string selectedFormat: ""

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 38
                        anchors.rightMargin: 38
                        anchors.topMargin: 32
                        anchors.bottomMargin: 30
                        spacing: 18

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3
                            Text {
                                text: "Search"
                                color: bridge.primaryColor
                                font.pixelSize: 32
                                font.weight: Font.Black
                            }
                            Text {
                                text: "Search AniList and MangaBaka together."
                                color: bridge.mutedColor
                                font.pixelSize: 12
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            TextField {
                                id: searchInput
                                Layout.fillWidth: true
                                placeholderText: "Search titles…"
                                selectByMouse: true
                                onAccepted: bridge.searchCatalog(text, searchPage.selectedType, searchPage.selectedFormat)
                            }
                            ComboBox {
                                Layout.preferredWidth: 125
                                model: ["All media", "ANIME", "MANGA"]
                                currentIndex: 0
                                onActivated: searchPage.selectedType = currentIndex === 0 ? "" : currentText
                            }
                            ComboBox {
                                Layout.preferredWidth: 135
                                model: ["All formats", "TV", "TV_SHORT", "MOVIE", "OVA", "ONA", "SPECIAL", "MANGA", "NOVEL", "ONE_SHOT"]
                                currentIndex: 0
                                onActivated: searchPage.selectedFormat = currentIndex === 0 ? "" : currentText
                            }
                            Button {
                                text: "Search"
                                onClicked: bridge.searchCatalog(searchInput.text, searchPage.selectedType, searchPage.selectedFormat)
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: bridge.searchError.length > 0
                            text: bridge.searchError
                            color: bridge.dangerColor
                            wrapMode: Text.WordWrap
                            font.pixelSize: 12
                        }

                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true

                            GridView {
                                id: searchGrid
                                anchors.fill: parent
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                cellWidth: bridge.cardSize + bridge.cardGap + 8
                                cellHeight: bridge.coverHeight + bridge.titleHeight + bridge.seriesHeight + bridge.metadataHeight + 84
                                model: bridge.searchItems

                                delegate: Item {
                                    required property var modelData
                                    width: searchGrid.cellWidth - bridge.cardGap
                                    height: searchGrid.cellHeight - 38
                                    PosterCard {
                                        bridge: root.bridge
                                        workId: modelData.workId || modelData.id
                                        title: modelData.title || "Untitled"
                                        fullTitle: modelData.fullTitle || modelData.title || "Untitled"
                                        coverSource: modelData.coverSource || ""
                                        coverCacheWorkId: modelData.coverCacheWorkId || modelData.workId || modelData.id
                                        format: modelData.format || ""
                                        startYear: modelData.startYear || 0
                                        mediaType: modelData.mediaType || modelData.type || ""
                                        seriesCount: modelData.seriesCount || 1
                                        bundleSummary: modelData.bundleSummary || ""
                                        isInLibrary: modelData.isInLibrary || false
                                        showAddButton: true
                                        onActivated: function(workId) { bridge.requestOpenSearchWork(workId) }
                                        onAddRequested: function(workId) { bridge.requestAddSearchWork(workId) }
                                    }
                                }
                            }

                            Text {
                                anchors.centerIn: parent
                                visible: !bridge.searchLoading && bridge.searchItems.length === 0
                                text: "Search for a title to see results."
                                color: bridge.mutedColor
                                font.pixelSize: 14
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: bridge.searchLoading ? "Searching…" : (bridge.searchItems.length + " results")
                                color: bridge.mutedColor
                                font.pixelSize: 11
                                Layout.fillWidth: true
                            }
                            Button {
                                text: "Load more"
                                enabled: bridge.searchHasNext && !bridge.searchLoading
                                visible: bridge.searchHasNext
                                onClicked: bridge.loadMoreSearchResults()
                            }
                        }
                    }
                }

                // Release calendar
                Item {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 34
                        anchors.rightMargin: 34
                        anchors.topMargin: 28
                        anchors.bottomMargin: 30
                        spacing: 15

                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Text {
                                    text: "Release calendar"
                                    color: bridge.primaryColor
                                    font.pixelSize: 28
                                    font.weight: Font.Black
                                }
                                Text {
                                    text: "Upcoming episode dates from your locally cached schedule."
                                    color: bridge.secondaryColor
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }
                            }
                            Button {
                                text: "Refresh"
                                onClicked: bridge.refreshCalendar()
                            }
                        }

                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 10
                            model: bridge.calendarItems

                            delegate: Rectangle {
                                required property var modelData
                                width: ListView.view.width
                                height: 94
                                radius: 13
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 13
                                    Rectangle {
                                        Layout.preferredWidth: 52
                                        Layout.fillHeight: true
                                        radius: 9
                                        color: bridge.accentSoftColor
                                        Column {
                                            anchors.centerIn: parent
                                            spacing: 0
                                            Text {
                                                text: modelData.month
                                                color: bridge.accentColor
                                                font.pixelSize: 10
                                                font.weight: Font.Black
                                                anchors.horizontalCenter: parent.horizontalCenter
                                            }
                                            Text {
                                                text: modelData.day
                                                color: bridge.primaryColor
                                                font.pixelSize: 22
                                                font.weight: Font.Black
                                                anchors.horizontalCenter: parent.horizontalCenter
                                            }
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 3
                                        Text {
                                            text: modelData.workTitle
                                            color: bridge.primaryColor
                                            font.pixelSize: 13
                                            font.weight: Font.Bold
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                        Text {
                                            text: modelData.episodeTitle.length > 0
                                                ? modelData.episodeTitle : ("Episode " + modelData.episodeNumber)
                                            color: bridge.secondaryColor
                                            font.pixelSize: 11
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            text: modelData.dateLabel
                                            color: bridge.mutedColor
                                            font.pixelSize: 10
                                        }
                                    }
                                    Button {
                                        text: modelData.reminderEnabled ? "Reminder on" : "Remind me"
                                        onClicked: bridge.setReminder(modelData.workId, modelData.episodeNumber, !modelData.reminderEnabled)
                                    }
                                }
                            }
                        }

                        Text {
                            anchors.centerIn: parent
                            visible: bridge.calendarItems.length === 0
                            text: "No upcoming episode dates cached.\n\nThe calendar populates from saved episode air dates."
                            color: bridge.mutedColor
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                            width: Math.min(parent.width - 40, 450)
                        }
                    }
                }

                // Favorites
                Item {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 34
                        anchors.rightMargin: 34
                        anchors.topMargin: 28
                        anchors.bottomMargin: 30
                        spacing: 15

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Text {
                                text: "Favorites"
                                color: bridge.primaryColor
                                font.pixelSize: 28
                                font.weight: Font.Black
                            }
                            Text {
                                text: "Your saved characters, voice actors, and production staff."
                                color: bridge.secondaryColor
                                font.pixelSize: 12
                            }
                        }

                        GridView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            cellWidth: Math.max(240, width / 3)
                            cellHeight: 106
                            model: bridge.favoritesItems

                            delegate: Rectangle {
                                required property var modelData
                                width: GridView.view.cellWidth - 12
                                height: GridView.view.cellHeight - 12
                                radius: 13
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 13
                                    spacing: 12
                                    Rectangle {
                                        Layout.preferredWidth: 54
                                        Layout.preferredHeight: 68
                                        radius: 9
                                        color: bridge.accentSoftColor
                                        Text {
                                            anchors.centerIn: parent
                                            text: (modelData.entity_name || "?").slice(0, 1).toUpperCase()
                                            color: bridge.accentColor
                                            font.pixelSize: 24
                                            font.weight: Font.Black
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 4
                                        Text {
                                            text: modelData.entity_name || "Unknown profile"
                                            color: bridge.primaryColor
                                            font.pixelSize: 13
                                            font.weight: Font.Bold
                                            wrapMode: Text.WordWrap
                                            maximumLineCount: 2
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                        Text {
                                            text: modelData.kindLabel
                                            color: bridge.mutedColor
                                            font.pixelSize: 10
                                        }
                                        RowLayout {
                                            spacing: 6
                                            Button {
                                                text: "Open"
                                                onClicked: bridge.requestOpenProfile(modelData.entity_type, modelData.entity_id, modelData.entity_name)
                                            }
                                            Button {
                                                text: "Remove"
                                                onClicked: bridge.removeFavorite(modelData.entity_type, modelData.entity_id, false)
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            anchors.centerIn: parent
                            visible: bridge.favoritesItems.length === 0
                            width: Math.min(parent.width - 40, 450)
                            text: "No saved profiles yet.\n\nOpen a character or staff profile and favorite it to keep it here."
                            color: bridge.mutedColor
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                // Settings
                Flickable {
                    clip: true
                    contentHeight: settingsColumn.implicitHeight + 60

                    ColumnLayout {
                        id: settingsColumn
                        width: parent.width
                        anchors.leftMargin: 34
                        anchors.rightMargin: 34
                        anchors.topMargin: 28
                        spacing: 18

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Text {
                                text: "Settings"
                                color: bridge.primaryColor
                                font.pixelSize: 28
                                font.weight: Font.Black
                            }
                            Text {
                                text: "Personalize NekoTrack's appearance and behavior."
                                color: bridge.secondaryColor
                                font.pixelSize: 12
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 144
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 12
                                Text {
                                    text: "Theme"
                                    color: bridge.primaryColor
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Repeater {
                                        model: bridge.themePresets
                                        delegate: Button {
                                            required property string modelData
                                            Layout.fillWidth: true
                                            text: modelData
                                            highlighted: bridge.themePreset === modelData
                                            onClicked: bridge.setPreference("theme_preset", modelData)
                                        }
                                    }
                                }
                                CheckBox {
                                    text: "Light mode"
                                    checked: bridge.lightMode
                                    onToggled: bridge.setPreference("light_mode", checked)
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 156
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 7
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Poster size"
                                        color: bridge.primaryColor
                                        font.pixelSize: 14
                                        font.weight: Font.Bold
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        text: bridge.cardSize + " px"
                                        color: bridge.mutedColor
                                        font.pixelSize: 12
                                    }
                                }
                                Slider {
                                    Layout.fillWidth: true
                                    from: 80
                                    to: 270
                                    stepSize: 5
                                    value: bridge.cardSize
                                    onPressedChanged: if (!pressed) bridge.setPreference("card_size", value)
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Text size"
                                        color: bridge.primaryColor
                                        font.pixelSize: 14
                                        font.weight: Font.Bold
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        text: bridge.fontSize + " px"
                                        color: bridge.mutedColor
                                        font.pixelSize: 12
                                    }
                                }
                                Slider {
                                    Layout.fillWidth: true
                                    from: 8
                                    to: 36
                                    stepSize: 1
                                    value: bridge.fontSize
                                    onPressedChanged: if (!pressed) bridge.setPreference("font_size", value)
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 130
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 9
                                Text {
                                    text: "Background"
                                    color: bridge.primaryColor
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                Text {
                                    text: bridge.backgroundSource.length > 0 ? "Custom background enabled" : "Using the default background"
                                    color: bridge.secondaryColor
                                    font.pixelSize: 12
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Button {
                                        text: "Choose images…"
                                        onClicked: bridge.chooseBackgroundImages()
                                    }
                                    Button {
                                        text: "Remove current image"
                                        enabled: bridge.backgroundPaths.length > 0
                                        onClicked: {
                                            if (bridge.backgroundPaths.length > 0)
                                                bridge.removeBackgroundImage(bridge.backgroundPaths[0])
                                        }
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 160
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 8
                                Text {
                                    text: "Application"
                                    color: bridge.primaryColor
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                RowLayout {
                                    Button { text: "Setup"; onClicked: bridge.requestSetup() }
                                    Button { text: "Check for updates"; onClicked: bridge.requestUpdateCheck() }
                                    Button { text: "Export diagnostics"; onClicked: bridge.requestDiagnosticsExport() }
                                }
                            }
                        }
                    }
                }

                // Work details
                Item {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 34
                        anchors.rightMargin: 34
                        anchors.topMargin: 28
                        anchors.bottomMargin: 30
                        spacing: 16

                        RowLayout {
                            Layout.fillWidth: true
                            Button {
                                text: "← Back"
                                onClicked: bridge.goBack()
                            }
                            Item { Layout.fillWidth: true }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 225
                            spacing: 20

                            Image {
                                Layout.preferredWidth: 166
                                Layout.preferredHeight: 225
                                source: bridge.selectedWork.coverSource || ""
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                cache: true
                                layer.enabled: true
                                layer.effect: MultiEffect {
                                    maskEnabled: true
                                    autoPaddingEnabled: false
                                    maskSource: Rectangle {
                                        width: 166
                                        height: 225
                                        radius: bridge.cornerRadius
                                        color: "white"
                                        layer.enabled: true
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                spacing: 8
                                Text {
                                    text: bridge.selectedWork.title || "Select a title"
                                    color: bridge.primaryColor
                                    font.pixelSize: 27
                                    font.weight: Font.Black
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                                Text {
                                    text: [bridge.selectedWork.format || "", bridge.selectedWork.startYear || ""].filter(Boolean).join(" · ")
                                    color: bridge.mutedColor
                                    font.pixelSize: 12
                                }
                                Text {
                                    text: (bridge.selectedWork.mediaType || "") + (bridge.selectedWork.status ? " · " + bridge.selectedWork.status : "")
                                    color: bridge.secondaryColor
                                    font.pixelSize: 12
                                }
                                Text {
                                    text: bridge.selectedWork.isInLibrary
                                        ? ("Progress: " + bridge.selectedWork.progressEpisodes + (bridge.selectedWork.episodeTotal ? " / " + bridge.selectedWork.episodeTotal + " episodes" : " episodes"))
                                        : "Not in your Library yet"
                                    color: bridge.secondaryColor
                                    font.pixelSize: 12
                                }
                                RowLayout {
                                    Button {
                                        visible: !bridge.selectedWork.isInLibrary
                                        text: "Add to Library"
                                        onClicked: bridge.requestAddSearchWork(bridge.selectedWork.id)
                                    }
                                    Button {
                                        visible: bridge.selectedWork.isInLibrary && bridge.selectedWork.mediaType === "ANIME"
                                        text: "Mark all watched"
                                        onClicked: bridge.markAllEpisodesWatched(bridge.selectedWork.id, true)
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 1
                            color: bridge.frameColor
                        }

                        Text {
                            text: "Synopsis"
                            color: bridge.primaryColor
                            font.pixelSize: 17
                            font.weight: Font.Bold
                        }
                        Text {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(130, implicitHeight)
                            text: bridge.selectedWork.synopsis || "No synopsis available."
                            color: bridge.secondaryColor
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            clip: true
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            visible: bridge.selectedWork.mediaType === "MANGA"
                                || bridge.selectedWork.format === "NOVEL"
                                || bridge.selectedWork.format === "LIGHT_NOVEL"
                            spacing: 12
                            Text {
                                text: "Chapters read"
                                color: bridge.primaryColor
                                font.pixelSize: 12
                                Layout.fillWidth: true
                            }
                            SpinBox {
                                from: 0
                                to: 100000
                                editable: true
                                value: bridge.selectedWork.progressChapters || 0
                                onValueModified: bridge.setReadingProgress(bridge.selectedWork.id, "chapter", value)
                            }
                            Text {
                                text: "Volumes read"
                                color: bridge.primaryColor
                                font.pixelSize: 12
                            }
                            SpinBox {
                                from: 0
                                to: 100000
                                editable: true
                                value: bridge.selectedWork.progressVolumes || 0
                                onValueModified: bridge.setReadingProgress(bridge.selectedWork.id, "volume", value)
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: "Episodes"
                                color: bridge.primaryColor
                                font.pixelSize: 17
                                font.weight: Font.Bold
                                Layout.fillWidth: true
                            }
                            Text {
                                text: bridge.episodeItems.length + " saved"
                                color: bridge.mutedColor
                                font.pixelSize: 11
                            }
                        }

                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 6
                            model: bridge.episodeItems

                            delegate: Rectangle {
                                required property var modelData
                                width: ListView.view.width
                                height: 76
                                radius: 10
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 9
                                    spacing: 10
                                    Image {
                                        Layout.preferredWidth: 44
                                        Layout.preferredHeight: 58
                                        source: modelData.coverSource || ""
                                        fillMode: Image.PreserveAspectCrop
                                        asynchronous: true
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 3
                                        Text {
                                            text: modelData.title
                                            color: bridge.primaryColor
                                            font.pixelSize: 12
                                            font.weight: Font.Bold
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            text: modelData.description || modelData.airDate || ("Episode " + modelData.episodeNumber)
                                            color: bridge.mutedColor
                                            font.pixelSize: 10
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                    }
                                    CheckBox {
                                        checked: modelData.watched
                                        enabled: bridge.selectedWork.isInLibrary
                                        onToggled: bridge.setEpisodeWatched(bridge.selectedWork.id, modelData.episodeNumber, checked)
                                    }
                                }
                            }
                        }
                    }
                }

                // Entity profile
                Item {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 34
                        anchors.rightMargin: 34
                        anchors.topMargin: 28
                        anchors.bottomMargin: 30
                        spacing: 15

                        RowLayout {
                            Button { text: "← Back"; onClicked: bridge.goBack() }
                            Item { Layout.fillWidth: true }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 18
                            Rectangle {
                                Layout.preferredWidth: 92
                                Layout.preferredHeight: 110
                                radius: 12
                                color: bridge.accentSoftColor
                                Image {
                                    anchors.fill: parent
                                    anchors.margins: 2
                                    source: bridge.selectedProfile.image && bridge.selectedProfile.image.large
                                        ? bridge.selectedProfile.image.large : ""
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    visible: source.toString().length > 0
                                }
                                Text {
                                    anchors.centerIn: parent
                                    visible: !bridge.selectedProfile.image || !bridge.selectedProfile.image.large
                                    text: (bridge.selectedProfile.name || "?").toString().slice(0, 1).toUpperCase()
                                    color: bridge.accentColor
                                    font.pixelSize: 30
                                    font.weight: Font.Black
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 5
                                Text {
                                    text: {
                                        var name = bridge.selectedProfile.name
                                        if (name && typeof name === "object")
                                            return name.full || name.native || "Profile"
                                        return name || bridge.selectedProfile.entity_name || "Profile"
                                    }
                                    color: bridge.primaryColor
                                    font.pixelSize: 25
                                    font.weight: Font.Black
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                                Text {
                                    text: (bridge.selectedProfile.entity_type || "profile").toString().replace("_", " ")
                                    color: bridge.mutedColor
                                    font.pixelSize: 12
                                }
                                Text {
                                    text: bridge.selectedProfile.siteUrl || ""
                                    color: bridge.accentColor
                                    font.pixelSize: 11
                                }
                            }
                        }

                        Rectangle { Layout.fillWidth: true; height: 1; color: bridge.frameColor }

                        Text {
                            text: "About"
                            color: bridge.primaryColor
                            font.pixelSize: 17
                            font.weight: Font.Bold
                        }
                        Text {
                            Layout.fillWidth: true
                            text: (bridge.selectedProfile.description || "").toString().replace(/<[^>]*>/g, "")
                            color: bridge.secondaryColor
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }
}
