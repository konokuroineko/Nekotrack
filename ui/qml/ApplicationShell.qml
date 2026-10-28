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

    NekoImage {

        imageBridge: root.bridge
        id: backgroundArtwork
        anchors.fill: parent
        url: bridge.backgroundSource
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
        id: shellContent
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

                    NekoImage {

                        imageBridge: root.bridge
                        anchors.left: parent.left
                        anchors.leftMargin: 4
                        anchors.verticalCenter: parent.verticalCenter
                        width: 222
                        height: 58
                        url: bridge.brandWordmarkSource
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        cache: true
                        asynchronous: false
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
                    clip: true
                    property int homeCardWidth: bridge.cardSize + bridge.cardGap + 8

                    Flickable {
                        id: homeScroll
                        anchors.fill: parent
                        clip: true
                        contentWidth: width
                        contentHeight: homeColumn.implicitHeight + 40
                        boundsBehavior: Flickable.StopAtBounds
                        onContentYChanged: {
                            if (contentHeight > height
                                    && contentY >= contentHeight - height * 1.35
                                    && bridge.recommendationItems.length > 0
                                    && bridge.recommendationHasNext
                                    && !bridge.recommendationLoading) {
                                bridge.loadMoreRecommendations()
                            }
                        }

                        ColumnLayout {
                            id: homeColumn
                            x: 18
                            y: 18
                            width: Math.max(1, homeScroll.width - 36)
                            spacing: 12

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: bridge.homeItems.length > 0
                                    ? bridge.coverHeight + bridge.titleHeight + bridge.seriesHeight + bridge.metadataHeight + 124
                                    : 150
                                radius: 16
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 7

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 4
                                        Text {
                                            text: "Continue watching or reading"
                                            color: bridge.primaryColor
                                            font.pixelSize: 16
                                            font.weight: Font.Black
                                        }
                                        Text {
                                            text: "Pick up from your locally saved progress."
                                            color: bridge.mutedColor
                                            font.pixelSize: 11
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                        }
                                    }

                                    Item {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: bridge.homeItems.length > 0
                                            ? bridge.coverHeight + bridge.titleHeight + bridge.seriesHeight + bridge.metadataHeight + 54
                                            : 68

                                        ListView {
                                            id: continueList
                                            anchors.fill: parent
                                            visible: bridge.homeItems.length > 0
                                            clip: true
                                            orientation: ListView.Horizontal
                                            spacing: 10
                                            boundsBehavior: Flickable.StopAtBounds
                                            model: bridge.homeItems.slice(0, 4)

                                            delegate: Item {
                                                required property var modelData
                                                width: homePage.homeCardWidth
                                                height: continueList.height

                                                Column {
                                                    anchors.left: parent.left
                                                    anchors.top: parent.top
                                                    spacing: 3

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
                                                        status: modelData.homeStatus || modelData.status || ""
                                                        progressEpisodes: modelData.progressEpisodes || 0
                                                        episodeTotal: modelData.episodeTotal || 0
                                                        isInLibrary: true
                                                        showMenu: true
                                                        onActivated: function(workId) { bridge.requestOpenWork(workId) }
                                                        onEditBundleRequested: function(workId) { bridge.requestEditBundle(workId) }
                                                        onDeleteRequested: function(workId) { bridge.requestDeleteWork(workId) }
                                                    }

                                                    Text {
                                                        width: bridge.cardSize
                                                        height: 12
                                                        text: (modelData.homeStatus || modelData.status || "IN PROGRESS")
                                                            .replace(/_/g, " ").toUpperCase()
                                                        color: bridge.accentColor
                                                        font.pixelSize: 9
                                                        font.weight: Font.Black
                                                        elide: Text.ElideRight
                                                    }

                                                    Text {
                                                        width: bridge.cardSize
                                                        height: 36
                                                        text: modelData.progressCaption || ""
                                                        color: bridge.secondaryColor
                                                        font.pixelSize: 10
                                                        wrapMode: Text.WordWrap
                                                        maximumLineCount: 3
                                                        elide: Text.ElideRight
                                                        clip: true
                                                    }
                                                }
                                            }
                                        }

                                        Text {
                                            anchors.centerIn: parent
                                            visible: bridge.homeLoading
                                            width: Math.min(parent.width - 30, 420)
                                            text: "Loading your Library…"
                                            horizontalAlignment: Text.AlignHCenter
                                            wrapMode: Text.WordWrap
                                            color: bridge.mutedColor
                                            font.pixelSize: 13
                                        }

                                        Text {
                                            anchors.centerIn: parent
                                            visible: !bridge.homeLoading && bridge.homeItems.length === 0
                                            width: Math.min(parent.width - 30, 420)
                                            text: "Nothing in progress yet. Add a title to your Library, then your saved progress will appear here."
                                            horizontalAlignment: Text.AlignHCenter
                                            wrapMode: Text.WordWrap
                                            color: bridge.mutedColor
                                            font.pixelSize: 12
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 138
                                    + Math.min(3, bridge.calendarItems.length) * 62
                                    + (bridge.calendarItems.length === 0 ? 38 : 0)
                                    + (bridge.calendarItems.length > 3 ? 16 : 0)
                                radius: 16
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 7

                                    RowLayout {
                                        Layout.fillWidth: true
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 4
                                            Text {
                                                text: "Upcoming releases"
                                                color: bridge.primaryColor
                                                font.pixelSize: 16
                                                font.weight: Font.Black
                                            }
                                            Text {
                                                text: "Cached episode dates for the next 60 days. Reminders notify while NekoTrack is running."
                                                color: bridge.mutedColor
                                                font.pixelSize: 11
                                                wrapMode: Text.WordWrap
                                                Layout.fillWidth: true
                                            }
                                        }
                                        Button {
                                            text: "Open calendar"
                                            onClicked: bridge.navigate("calendar")
                                        }
                                    }

                                    Text {
                                        text: bridge.calendarItems.length
                                            + " upcoming episode"
                                            + (bridge.calendarItems.length === 1 ? "" : "s")
                                            + " · next 60 days"
                                        color: bridge.secondaryColor
                                        font.pixelSize: 10
                                        Layout.fillWidth: true
                                    }

                                    Repeater {
                                        model: bridge.calendarItems.slice(0, 3)
                                        delegate: Rectangle {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 62
                                            radius: 11
                                            color: bridge.surfaceAltFillColor
                                            border.width: 1
                                            border.color: bridge.borderColor

                                            RowLayout {
                                                anchors.fill: parent
                                                anchors.margins: 7
                                                spacing: 9
                                                Rectangle {
                                                    Layout.preferredWidth: 48
                                                    Layout.fillHeight: true
                                                    radius: 9
                                                    color: bridge.accentSoftColor
                                                    border.width: 1
                                                    border.color: bridge.borderColor
                                                    Column {
                                                        anchors.centerIn: parent
                                                        spacing: 0
                                                        Text {
                                                            text: modelData.month
                                                            color: bridge.accentColor
                                                            font.pixelSize: 9
                                                            font.weight: Font.Black
                                                            anchors.horizontalCenter: parent.horizontalCenter
                                                        }
                                                        Text {
                                                            text: modelData.day
                                                            color: bridge.primaryColor
                                                            font.pixelSize: 20
                                                            font.weight: Font.Black
                                                            anchors.horizontalCenter: parent.horizontalCenter
                                                        }
                                                    }
                                                }
                                                ColumnLayout {
                                                    Layout.fillWidth: true
                                                    spacing: 1
                                                    Text {
                                                        text: (modelData.workTitle || "Untitled")
                                                            + " · "
                                                            + (modelData.episodeTitle.length > 0
                                                                ? modelData.episodeTitle
                                                                : ("Episode " + modelData.episodeNumber))
                                                        color: bridge.primaryColor
                                                        font.pixelSize: 11
                                                        font.weight: Font.Bold
                                                        maximumLineCount: 1
                                                        elide: Text.ElideRight
                                                        Layout.fillWidth: true
                                                    }
                                                    Text {
                                                        text: modelData.dateLabel
                                                        color: bridge.mutedColor
                                                        font.pixelSize: 10
                                                        elide: Text.ElideRight
                                                        Layout.fillWidth: true
                                                    }
                                                }
                                                Button {
                                                    text: modelData.reminderEnabled ? "On" : "Remind"
                                                    implicitWidth: 62
                                                    onClicked: bridge.setReminder(
                                                        modelData.workId,
                                                        modelData.episodeNumber,
                                                        !modelData.reminderEnabled
                                                    )
                                                }
                                            }
                                        }
                                    }

                                    Text {
                                        visible: bridge.calendarItems.length === 0
                                        text: "No upcoming episode dates cached. This preview won't guess release dates."
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }

                                    Text {
                                        visible: bridge.calendarItems.length > 3
                                        text: (bridge.calendarItems.length - 3) + " more release dates in Calendar."
                                        color: bridge.mutedColor
                                        font.pixelSize: 10
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 96
                                radius: 16
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 14
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 5
                                        Text {
                                            text: "For your next watch or read"
                                            color: bridge.primaryColor
                                            font.pixelSize: 20
                                            font.weight: Font.Black
                                            Layout.fillWidth: true
                                        }
                                        Text {
                                            text: "A learning feed built from your collection, saved favorites, feedback, and the wider anime catalog."
                                            color: bridge.mutedColor
                                            font.pixelSize: 11
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                        }
                                    }
                                    Button {
                                        text: bridge.recommendationLoading ? "Finding…" : "Refresh"
                                        enabled: !bridge.recommendationLoading
                                        onClicked: bridge.refreshRecommendations()
                                    }
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: bridge.recommendationError.length > 0
                                text: bridge.recommendationError
                                color: bridge.dangerColor
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: bridge.recommendationLoading && bridge.recommendationItems.length === 0
                                text: "Finding recommendations from your saved titles…"
                                color: bridge.mutedColor
                                font.pixelSize: 12
                            }

                            Item {
                                Layout.fillWidth: true
                                Layout.preferredHeight: Math.max(
                                    bridge.coverHeight + bridge.titleHeight + bridge.seriesHeight + bridge.metadataHeight + 126,
                                    recommendationGrid.contentHeight + 8
                                )

                                GridView {
                                    id: recommendationGrid
                                    anchors.fill: parent
                                    visible: bridge.recommendationItems.length > 0
                                    clip: true
                                    boundsBehavior: Flickable.StopAtBounds
                                    cellWidth: homePage.homeCardWidth
                                    cellHeight: bridge.coverHeight + bridge.titleHeight + bridge.seriesHeight
                                        + bridge.metadataHeight + 116
                                    model: bridge.recommendationItems

                                    delegate: Item {
                                        required property var modelData
                                        width: recommendationGrid.cellWidth - bridge.cardGap
                                        height: recommendationGrid.cellHeight - bridge.cardGap
                                        PosterCard {
                                            anchors.left: parent.left
                                            bridge: root.bridge
                                            impressionViewport: recommendationGrid
                                            workId: modelData.workId || modelData.id
                                            title: modelData.title || "Untitled"
                                            fullTitle: modelData.fullTitle || modelData.title || "Untitled"
                                            coverSource: modelData.coverSource || ""
                                            coverCacheWorkId: modelData.coverCacheWorkId || modelData.workId || modelData.id
                                            format: modelData.format || ""
                                            startYear: modelData.startYear || 0
                                            mediaType: modelData.mediaType || ""
                                            seriesCount: modelData.seriesCount || 1
                                            bundleSummary: modelData.bundleSummary || ""
                                            recommendationReason: modelData.recommendationReason || ""
                                            isInLibrary: modelData.isInLibrary || false
                                            showAddButton: true
                                            showMenu: true
                                            showRecommendationFeedback: true
                                            onActivated: function(workId) { bridge.requestOpenRecommendation(workId) }
                                            onAddRequested: function(workId) { bridge.requestAddRecommendation(workId) }
                                            onRecommendationFeedbackRequested: function(workId, feedback) {
                                                bridge.requestRecommendationFeedback(workId, feedback)
                                            }
                                        }
                                    }
                                }

                                Row {
                                    anchors.fill: parent
                                    spacing: bridge.cardGap
                                    clip: true
                                    visible: bridge.recommendationLoading && bridge.recommendationItems.length === 0

                                    Repeater {
                                        model: 4
                                        delegate: Rectangle {
                                            required property int index
                                            width: bridge.cardSize
                                            height: bridge.coverHeight + bridge.titleHeight + bridge.seriesHeight + bridge.metadataHeight + 116
                                            radius: bridge.cornerRadius
                                            color: bridge.surfaceFillColor
                                            border.width: 1
                                            border.color: bridge.frameColor

                                            Column {
                                                anchors.fill: parent
                                                anchors.margins: 8
                                                spacing: 8
                                                Rectangle {
                                                    width: parent.width
                                                    height: bridge.coverHeight - 8
                                                    radius: bridge.cornerRadius
                                                    color: bridge.surfaceAltFillColor
                                                }
                                                Rectangle {
                                                    width: parent.width * 0.82
                                                    height: 11
                                                    radius: 5
                                                    color: bridge.surfaceAltFillColor
                                                }
                                                Rectangle {
                                                    width: parent.width * 0.56
                                                    height: 8
                                                    radius: 4
                                                    color: bridge.surfaceAltFillColor
                                                }
                                                Rectangle {
                                                    width: parent.width * 0.68
                                                    height: 8
                                                    radius: 4
                                                    color: bridge.surfaceAltFillColor
                                                }
                                            }
                                        }
                                    }
                                }

                                Text {
                                    anchors.centerIn: parent
                                    visible: !bridge.recommendationLoading && bridge.recommendationItems.length === 0
                                        && bridge.recommendationError.length === 0
                                    width: Math.min(parent.width - 50, 420)
                                    text: "No recommendations yet.\n\nRefresh to discover titles from your library and the wider catalog."
                                    color: bridge.mutedColor
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.WordWrap
                                    font.pixelSize: 14
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: bridge.recommendationLoading && bridge.recommendationItems.length > 0
                                        ? "Finding more titles…" : (bridge.recommendationItems.length + " suggestions")
                                    color: bridge.mutedColor
                                    font.pixelSize: 11
                                    Layout.fillWidth: true
                                }
                                Button {
                                    text: "Load more"
                                    visible: bridge.recommendationHasNext
                                    enabled: bridge.recommendationHasNext && !bridge.recommendationLoading
                                    onClicked: bridge.loadMoreRecommendations()
                                }
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
                    property var allFormatOptions: [
                        "All", "TV", "TV Short", "Movie", "OVA", "ONA", "Special",
                        "Music", "Manga", "Novel", "One Shot"
                    ]
                    property bool seasonEnabled: true
                    property bool providerFiltersEnabled: true

                    function refreshFormatFilter() {
                        var previous = formatFilter.currentText
                        var options = allFormatOptions
                        if (mediaFilter.currentText === "Anime") {
                            options = ["All", "TV", "TV Short", "Movie", "OVA", "ONA", "Special", "Music"]
                        } else if (mediaFilter.currentText === "Manga") {
                            options = ["All", "Manga", "One Shot"]
                        } else if (mediaFilter.currentText === "Novels") {
                            options = ["All", "Novel"]
                        }
                        formatFilter.model = options
                        var restored = options.indexOf(previous)
                        formatFilter.currentIndex = restored >= 0 ? restored : 0
                        refreshFilterAvailability()
                    }

                    function refreshFilterAvailability() {
                        var mediaChoice = mediaFilter.currentText
                        var formatChoice = formatFilter.currentText
                        var animeFormats = ["TV", "TV Short", "Movie", "OVA", "ONA", "Special", "Music"]
                        var mangaFormats = ["Manga", "Novel", "One Shot"]
                        var animeSpecific = mediaChoice === "Anime"
                            || animeFormats.indexOf(formatChoice) >= 0
                            || seasonFilter.currentText !== "All"
                        var mangaSpecific = mediaChoice === "Manga"
                            || mediaChoice === "Novels"
                            || mangaFormats.indexOf(formatChoice) >= 0
                        if (mangaSpecific && seasonFilter.currentText !== "All")
                            seasonFilter.currentIndex = 0
                        seasonEnabled = !mangaSpecific
                        providerFiltersEnabled = !animeSpecific && formatChoice !== "One Shot"
                        if (!providerFiltersEnabled) {
                            publisherFilter.clear()
                            licensingFilter.currentIndex = 0
                        }
                    }

                    Component.onCompleted: refreshFormatFilter()

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

                        function runSearch() {
                            var mediaChoice = mediaFilter.currentText
                            var mediaType = ""
                            if (mediaChoice === "Anime")
                                mediaType = "ANIME"
                            else if (mediaChoice === "Manga" || mediaChoice === "Novels")
                                mediaType = "MANGA"

                            var formatMap = {
                                "TV": "TV", "TV Short": "TV_SHORT", "Movie": "MOVIE",
                                "OVA": "OVA", "ONA": "ONA", "Special": "SPECIAL", "Music": "MUSIC",
                                "Manga": "MANGA", "Novel": "NOVEL", "One Shot": "ONE_SHOT"
                            }
                            var selectedFormat = formatMap[formatFilter.currentText] || ""
                            if (formatFilter.currentText === "All") {
                                if (mediaChoice === "Manga")
                                    selectedFormat = "MANGA"
                                else if (mediaChoice === "Novels")
                                    selectedFormat = "NOVEL"
                            }

                            var statusMap = {
                                "Finished": "FINISHED", "Releasing": "RELEASING",
                                "Not Yet Released": "NOT_YET_RELEASED", "Cancelled": "CANCELLED",
                                "Hiatus": "HIATUS"
                            }
                            var seasonMap = {
                                "Winter": "WINTER", "Spring": "SPRING",
                                "Summer": "SUMMER", "Fall": "FALL"
                            }
                            var sortMap = {
                                "Relevance": "SEARCH_MATCH", "Popularity": "POPULARITY_DESC",
                                "Score": "SCORE_DESC", "Newest": "START_DATE_DESC",
                                "Oldest": "START_DATE", "Title A–Z": "TITLE_ROMAJI",
                                "Title Z–A": "TITLE_ROMAJI_DESC"
                            }
                            var scoreText = scoreFilter.currentText
                            var scoreValue = scoreText.endsWith("+") ? parseInt(scoreText.slice(0, -1)) : null
                            var yearText = yearFilter.text.trim()
                            var publisherText = publisherFilter.text.trim()
                            var licensing = licensingFilter.currentText

                            var filters = {
                                "format_filter": formatFilter.currentText === "All" ? null : selectedFormat,
                                "status": statusMap[statusFilter.currentText] || null,
                                "season": (mediaChoice === "All media" || mediaChoice === "Anime")
                                    ? (seasonMap[seasonFilter.currentText] || null) : null,
                                "year": /^[0-9]{4}$/.test(yearText) ? yearText : null,
                                "sort": sortMap[sortFilter.currentText] || "SEARCH_MATCH",
                                "min_score": isNaN(scoreValue) ? null : scoreValue,
                                "genre": genreFilter.text.trim() || null,
                                "tag": tagFilter.text.trim() || null,
                                "publisher_id": /^[0-9]+$/.test(publisherText) ? publisherText : null,
                                "is_licensed": licensing === "Licensed only" ? true
                                    : (licensing === "Unlicensed only" ? false : null),
                                "fast_search": fastSearch.checked
                            }

                            bridge.searchCatalogWithFilters(searchInput.text, mediaType, selectedFormat, filters)
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            TextField {
                                id: searchInput
                                Layout.fillWidth: true
                                placeholderText: "Title, character, franchise, or AniList link…"
                                selectByMouse: true
                                onAccepted: searchPage.runSearch()
                            }
                            Button {
                                text: filtersPanel.visible ? "Hide filters" : "Filters"
                                onClicked: filtersPanel.visible = !filtersPanel.visible
                            }
                            Button {
                                text: "Search"
                                onClicked: searchPage.runSearch()
                            }
                        }

                        ColumnLayout {
                            id: filtersPanel
                            Layout.fillWidth: true
                            visible: false
                            spacing: 9

                            GridLayout {
                                Layout.fillWidth: true
                                columns: 4
                                columnSpacing: 10
                                rowSpacing: 7

                                ComboBox {
                                    id: mediaFilter
                                    Layout.fillWidth: true
                                    model: ["All media", "Anime", "Manga", "Novels"]
                                    onActivated: searchPage.refreshFormatFilter()
                                }
                                ComboBox {
                                    id: formatFilter
                                    Layout.fillWidth: true
                                    model: searchPage.allFormatOptions
                                    onActivated: searchPage.refreshFilterAvailability()
                                }
                                ComboBox {
                                    id: statusFilter
                                    Layout.fillWidth: true
                                    model: ["All", "Finished", "Releasing", "Not Yet Released", "Cancelled", "Hiatus"]
                                }
                                ComboBox {
                                    id: seasonFilter
                                    Layout.fillWidth: true
                                    enabled: searchPage.seasonEnabled
                                    model: ["All", "Winter", "Spring", "Summer", "Fall"]
                                    onActivated: searchPage.refreshFilterAvailability()
                                }
                                TextField {
                                    id: yearFilter
                                    Layout.fillWidth: true
                                    placeholderText: "Year (e.g. 2024)"
                                    validator: RegularExpressionValidator { regularExpression: /^[0-9]{0,4}$/ }
                                }
                                ComboBox {
                                    id: scoreFilter
                                    Layout.fillWidth: true
                                    model: ["Any score", "50+", "60+", "70+", "80+", "90+"]
                                }
                                ComboBox {
                                    id: sortFilter
                                    Layout.fillWidth: true
                                    model: ["Relevance", "Popularity", "Score", "Newest", "Oldest", "Title A–Z", "Title Z–A"]
                                }
                                TextField {
                                    id: genreFilter
                                    Layout.fillWidth: true
                                    placeholderText: "Genre"
                                }
                                TextField {
                                    id: tagFilter
                                    Layout.fillWidth: true
                                    placeholderText: "Tag"
                                }
                                TextField {
                                    id: publisherFilter
                                    Layout.fillWidth: true
                                    placeholderText: "MangaBaka publisher ID"
                                    validator: RegularExpressionValidator { regularExpression: /^[0-9]*$/ }
                                    enabled: searchPage.providerFiltersEnabled
                                }
                                ComboBox {
                                    id: licensingFilter
                                    Layout.fillWidth: true
                                    model: ["Any licensing", "Licensed only", "Unlicensed only"]
                                    enabled: searchPage.providerFiltersEnabled
                                }
                                NekoCheckBox {
                                    bridge: root.bridge
                                    id: fastSearch
                                    text: "Fast Search (skip franchise grouping)"
                                    Layout.columnSpan: 2
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Button {
                                    text: "Clear filters"
                                    onClicked: {
                                        mediaFilter.currentIndex = 0
                                        formatFilter.currentIndex = 0
                                        statusFilter.currentIndex = 0
                                        seasonFilter.currentIndex = 0
                                        yearFilter.clear()
                                        scoreFilter.currentIndex = 0
                                        sortFilter.currentIndex = 0
                                        genreFilter.clear()
                                        tagFilter.clear()
                                        publisherFilter.clear()
                                        licensingFilter.currentIndex = 0
                                        fastSearch.checked = false
                                        searchPage.refreshFormatFilter()
                                    }
                                }
                                Item { Layout.fillWidth: true }
                                Text {
                                    text: "All filters are applied by the existing Python search backend."
                                    color: bridge.mutedColor
                                    font.pixelSize: 10
                                }
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
                            text: "No upcoming episode dates cached.\n\nThe calendar populates from saved episode air dates.\n\n"
                                + bridge.releaseReminderCount + " saved reminder"
                                + (bridge.releaseReminderCount === 1 ? "" : "s")
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
                                        clip: true
                                        NekoImage {
                                            imageBridge: root.bridge
                                            anchors.fill: parent
                                            url: modelData.imageSource || ""
                                            fillMode: Image.PreserveAspectCrop
                                            asynchronous: true
                                            cache: true
                                            visible: source.toString().length > 0
                                        }
                                        Text {
                                            anchors.centerIn: parent
                                            visible: !modelData.imageSource || modelData.imageSource.length === 0
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
                                        Text {
                                            visible: modelData.entity_type === "voice_actor"
                                                && modelData.languageLabel.length > 0
                                            text: modelData.languageLabel
                                            color: bridge.mutedColor
                                            font.pixelSize: 9
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

                        ColumnLayout {
                            anchors.centerIn: parent
                            visible: bridge.favoritesItems.length === 0
                            width: Math.min(parent.width - 40, 450)
                            spacing: 12
                            Text {
                                Layout.fillWidth: true
                                text: "No saved profiles yet.\n\nOpen a character, voice actor, or production staff profile and favorite it to keep it here."
                                color: bridge.mutedColor
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.WordWrap
                            }
                            Button {
                                text: "Explore titles"
                                Layout.alignment: Qt.AlignHCenter
                                onClicked: bridge.navigate("search")
                            }
                        }
                    }
                }

                // Settings
                Flickable {
                    id: settingsPage
                    property string settingsCategory: "General"
                    clip: true
                    contentWidth: width
                    contentHeight: settingsColumn.implicitHeight + 60
                    boundsBehavior: Flickable.StopAtBounds

                    ColumnLayout {
                        id: settingsColumn
                        x: 34
                        y: 28
                        width: Math.max(1, settingsPage.width - 68)
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

                        Flow {
                            id: settingsCategoryTabs
                            Layout.fillWidth: true
                            spacing: 8

                            Repeater {
                                model: ["General", "Appearance", "Library", "Discovery", "Integrations", "Data & Storage", "Advanced"]
                                delegate: Button {
                                    required property string modelData
                                    text: modelData
                                    width: Math.max(84, implicitWidth)
                                    height: 36
                                    checkable: true
                                    checked: settingsPage.settingsCategory === modelData
                                    font.pixelSize: 12
                                    onClicked: {
                                        settingsPage.settingsCategory = modelData
                                        settingsPage.contentY = 0
                                    }
                                }
                            }
                        }

                        Rectangle {
                            visible: settingsPage.settingsCategory === "General"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 258
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 9
                                Text {
                                    text: "Startup and updates"
                                    color: bridge.primaryColor
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                NekoCheckBox {
                                    bridge: root.bridge
                                    text: "Open maximized"
                                    checked: bridge.maximized
                                    onToggled: bridge.setPreference("maximized", checked)
                                }
                                NekoCheckBox {
                                    bridge: root.bridge
                                    text: "Check for updates at startup"
                                    checked: bridge.autoCheckUpdates
                                    onToggled: bridge.setPreference("auto_check_updates", checked)
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Update channel"
                                        color: bridge.secondaryColor
                                        font.pixelSize: 12
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        Layout.preferredWidth: 215
                                        model: ["Stable releases only", "Preview releases (testing)"]
                                        currentIndex: bridge.updateChannel === "preview" ? 1 : 0
                                        onActivated: bridge.setPreference("update_channel", ["stable", "preview"][currentIndex])
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Button {
                                        text: "Check for updates now"
                                        onClicked: bridge.requestUpdateCheck()
                                    }
                                    Button {
                                        text: "Restore previous version"
                                        onClicked: bridge.requestRollback()
                                    }
                                }
                            }
                        }

                        Rectangle {
                            visible: settingsPage.settingsCategory === "Appearance"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(160, bridge.themePresetItems.length * 86 + 98)
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 10
                                Text {
                                    text: "Theme"
                                    color: bridge.primaryColor
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Repeater {
                                        model: bridge.themePresetItems
                                        delegate: Button {
                                            id: themePresetButton
                                            required property var modelData
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 78
                                            checkable: true
                                            checked: bridge.themePreset === modelData.name
                                            background: Rectangle {
                                                radius: 12
                                                color: themePresetButton.checked ? bridge.accentSoftColor : bridge.surfaceAltFillColor
                                                border.width: themePresetButton.checked ? 2 : 1
                                                border.color: themePresetButton.checked ? bridge.accentColor : modelData.border
                                            }
                                            contentItem: RowLayout {
                                                spacing: 12
                                                Rectangle {
                                                    Layout.preferredWidth: 56
                                                    Layout.preferredHeight: 56
                                                    radius: 12
                                                    color: modelData.background
                                                    border.width: 1
                                                    border.color: modelData.border
                                                    ColumnLayout {
                                                        anchors.fill: parent
                                                        anchors.margins: 7
                                                        spacing: 5
                                                        Rectangle {
                                                            Layout.fillWidth: true
                                                            Layout.fillHeight: true
                                                            radius: 4
                                                            color: modelData.accent
                                                        }
                                                        Rectangle {
                                                            Layout.fillWidth: true
                                                            Layout.fillHeight: true
                                                            radius: 4
                                                            color: modelData.surface
                                                        }
                                                    }
                                                }
                                                ColumnLayout {
                                                    Layout.fillWidth: true
                                                    spacing: 2
                                                    Text {
                                                        text: modelData.name
                                                        color: bridge.primaryColor
                                                        font.pixelSize: 13
                                                        font.weight: Font.Bold
                                                    }
                                                    Text {
                                                        text: modelData.description
                                                        color: bridge.secondaryColor
                                                        font.pixelSize: 10
                                                        wrapMode: Text.WordWrap
                                                        Layout.fillWidth: true
                                                    }
                                                }
                                                Text {
                                                    text: themePresetButton.checked ? "✓" : ""
                                                    color: bridge.accentColor
                                                    font.pixelSize: 18
                                                    font.weight: Font.Bold
                                                }
                                            }
                                            onClicked: bridge.setPreference("theme_preset", modelData.name)
                                        }
                                    }
                                }
                                NekoCheckBox {
                                    bridge: root.bridge
                                    text: "White mode"
                                    checked: bridge.lightMode
                                    onToggled: bridge.setPreference("light_mode", checked)
                                }
                            }
                        }
                        Rectangle {
                            visible: settingsPage.settingsCategory === "Appearance"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 480
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
                                        text: "Interface scale"
                                        color: bridge.primaryColor
                                        font.pixelSize: 14
                                        font.weight: Font.Bold
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        Layout.preferredWidth: 115
                                        model: ["80%", "90%", "100%", "110%", "125%", "150%", "175%", "200%"]
                                        currentIndex: Math.max(0, [80, 90, 100, 110, 125, 150, 175, 200].indexOf(bridge.uiScale))
                                        onActivated: bridge.setPreference("ui_scale", [80, 90, 100, 110, 125, 150, 175, 200][currentIndex])
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    visible: bridge.uiScale !== bridge.activeUiScale
                                    Text {
                                        text: "Saved. Restart NekoTrack to apply this scale."
                                        color: bridge.secondaryColor
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    Button {
                                        text: "Restart now"
                                        onClicked: bridge.requestRestart()
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Card size"
                                        color: bridge.primaryColor
                                        font.pixelSize: 14
                                        font.weight: Font.Bold
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        Layout.preferredWidth: 165
                                        model: ["Compact", "Default", "Large", "Huge"]
                                        currentIndex: {
                                            switch (bridge.cardSize) {
                                            case 180: return 0
                                            case 210: return 1
                                            case 240: return 2
                                            case 270: return 3
                                            default: return 1
                                            }
                                        }
                                        onActivated: bridge.setPreference("card_size", [180, 210, 240, 270][currentIndex])
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Interface text size"
                                        color: bridge.primaryColor
                                        font.pixelSize: 14
                                        font.weight: Font.Bold
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        Layout.preferredWidth: 165
                                        model: ["Small", "Default", "Large", "Very large"]
                                        currentIndex: Math.max(0, [12, 13, 14, 15].indexOf(bridge.fontSize))
                                        onActivated: bridge.setPreference("font_size", [12, 13, 14, 15][currentIndex])
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Poster gap"
                                        color: bridge.primaryColor
                                        font.pixelSize: 14
                                        font.weight: Font.Bold
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        text: bridge.cardGap + " px"
                                        color: bridge.mutedColor
                                        font.pixelSize: 12
                                    }
                                }
                                Slider {
                                    Layout.fillWidth: true
                                    from: 0
                                    to: 120
                                    stepSize: 2
                                    value: bridge.cardGap
                                    onPressedChanged: if (!pressed) bridge.setPreference("card_gap", value)
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Corner radius"
                                        color: bridge.primaryColor
                                        font.pixelSize: 14
                                        font.weight: Font.Bold
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        Layout.preferredWidth: 165
                                        model: ["Sharp", "Soft", "Rounded", "Very rounded", "Pill-like"]
                                        currentIndex: Math.max(0, [6, 10, 12, 16, 20].indexOf(bridge.cornerRadius))
                                        onActivated: bridge.setPreference("corner_radius", [6, 10, 12, 16, 20][currentIndex])
                                    }
                                }
                            }
                        }

                        Rectangle {
                            visible: settingsPage.settingsCategory === "Library"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 184
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 10
                                Text {
                                    text: "Animation"
                                    color: bridge.primaryColor
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                NekoCheckBox {
                                    bridge: root.bridge
                                    text: "Hover highlighting"
                                    checked: bridge.hoverHighlight
                                    onToggled: bridge.setPreference("hover_highlight", checked)
                                }
                                NekoCheckBox {
                                    bridge: root.bridge
                                    text: "Smooth resize animation"
                                    checked: bridge.resizeAnimation
                                    onToggled: bridge.setPreference("resize_animation", checked)
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Animation speed"
                                        color: bridge.primaryColor
                                        font.pixelSize: 13
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        Layout.preferredWidth: 165
                                        model: ["Instant", "Fast", "Default", "Smooth", "Slow"]
                                        currentIndex: Math.max(0, [0, 180, 260, 380, 520].indexOf(bridge.animationSpeed))
                                        onActivated: bridge.setPreference("animation_speed", [0, 180, 260, 380, 520][currentIndex])
                                    }
                                }
                            }
                        }

                        Rectangle {
                            visible: settingsPage.settingsCategory === "Library"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 405
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 9
                                Text {
                                    text: "Automatic bundle contents"
                                    color: bridge.primaryColor
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                Text {
                                    text: "TV seasons and TV Shorts are always grouped. Choose which related formats may join them."
                                    color: bridge.secondaryColor
                                    font.pixelSize: 11
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                                Repeater {
                                    model: bridge.bundleOptionGroups
                                    delegate: ColumnLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: 4
                                        Text {
                                            text: modelData.title
                                            color: bridge.mutedColor
                                            font.pixelSize: 10
                                            font.weight: Font.Bold
                                        }
                                        Repeater {
                                            model: parent.modelData.options
                                            delegate: CheckBox {
                                                required property var modelData
                                                text: modelData.label
                                                checked: modelData.checked
                                                ToolTip.visible: hovered
                                                ToolTip.text: modelData.description
                                                onToggled: bridge.setPreference(modelData.key, checked)
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            visible: settingsPage.settingsCategory === "Discovery"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 145
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 9
                                Text {
                                    text: "Recommendations"
                                    color: bridge.primaryColor
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Voice-actor language"
                                        color: bridge.secondaryColor
                                        font.pixelSize: 12
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        Layout.preferredWidth: 235
                                        model: ["Japanese audio / sub", "English dub", "All voice languages / no preference"]
                                        currentIndex: {
                                            switch (bridge.recommendationVoiceLanguage) {
                                            case "JA": return 0
                                            case "EN": return 1
                                            default: return 2
                                            }
                                        }
                                        onActivated: bridge.setPreference("recommendation_voice_language", ["JA", "EN", "ALL"][currentIndex])
                                    }
                                }
                            }
                        }

                        Rectangle {
                            visible: settingsPage.settingsCategory === "Integrations"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 150
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 8
                                Text {
                                    text: "TMDB episode metadata"
                                    color: bridge.primaryColor
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                Text {
                                    text: "Optional fallback token. A shared NEKOTRACK_TMDB_ACCESS_TOKEN takes priority."
                                    color: bridge.secondaryColor
                                    font.pixelSize: 11
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    TextField {
                                        id: tmdbTokenInput
                                        Layout.fillWidth: true
                                        echoMode: TextInput.Password
                                        placeholderText: "TMDB API Read Access Token"
                                        text: bridge.tmdbApiToken
                                        selectByMouse: true
                                    }
                                    Button {
                                        text: "Save token"
                                        onClicked: bridge.setPreference("tmdb_api_token", tmdbTokenInput.text)
                                    }
                                }
                            }
                        }

                        Rectangle {
                            visible: settingsPage.settingsCategory === "Appearance"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 292
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 10
                                Text {
                                    text: "Background"
                                    color: bridge.primaryColor
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                Text {
                                    text: bridge.backgroundSource.length > 0
                                        ? ("Showing: " + bridge.backgroundSelectedPath.split("/").pop())
                                        : "Using the default background"
                                    color: bridge.secondaryColor
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Selected background"
                                        color: bridge.secondaryColor
                                        font.pixelSize: 12
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        Layout.preferredWidth: 275
                                        model: bridge.backgroundPaths
                                        currentIndex: Math.max(0, bridge.backgroundPaths.indexOf(bridge.backgroundSelectedPath))
                                        enabled: bridge.backgroundPaths.length > 0
                                        onActivated: bridge.selectBackgroundImage(bridge.backgroundPaths[currentIndex])
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Button {
                                        text: "Choose images…"
                                        onClicked: bridge.chooseBackgroundImages()
                                    }
                                    Button {
                                        text: "Remove current image"
                                        enabled: bridge.backgroundSelectedPath.length > 0
                                        onClicked: {
                                            if (bridge.backgroundSelectedPath.length > 0)
                                                bridge.removeBackgroundImage(bridge.backgroundSelectedPath)
                                        }
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Slideshow"
                                        color: bridge.primaryColor
                                        font.pixelSize: 13
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        id: backgroundIntervalCombo
                                        Layout.preferredWidth: 185
                                        model: ["Disabled", "Static image", "30 seconds", "1 minute", "5 minutes", "15 minutes", "30 minutes"]
                                        currentIndex: {
                                            switch (bridge.backgroundInterval) {
                                            case -1: return 0
                                            case 0: return 1
                                            case 30: return 2
                                            case 60: return 3
                                            case 300: return 4
                                            case 900: return 5
                                            case 1800: return 6
                                            default: return 1
                                            }
                                        }
                                        onActivated: bridge.setPreference(
                                            "background_slideshow_interval",
                                            [-1, 0, 30, 60, 300, 900, 1800][currentIndex]
                                        )
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "Background overlay"
                                        color: bridge.primaryColor
                                        font.pixelSize: 13
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        text: bridge.backgroundOverlayOpacity + "%"
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                    }
                                }
                                Slider {
                                    Layout.fillWidth: true
                                    from: 35
                                    to: 90
                                    stepSize: 1
                                    value: bridge.backgroundOverlayOpacity
                                    onPressedChanged: if (!pressed)
                                        bridge.setPreference("background_overlay_opacity", value)
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: bridge.backgroundPaths.length + " background image(s) saved."
                                    color: bridge.mutedColor
                                    font.pixelSize: 11
                                }
                            }
                        }

                        Rectangle {
                            visible: settingsPage.settingsCategory === "Advanced"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 170
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
                                    Layout.fillWidth: true
                                    Button { text: "Run setup wizard again"; onClicked: bridge.requestSetup() }
                                    Button { text: "Restore defaults"; onClicked: bridge.resetPreferences() }
                                }
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 360
                            visible: settingsPage.settingsCategory === "Data & Storage"
                            radius: 13
                            color: bridge.surfaceFillColor
                            border.width: 1
                            border.color: bridge.frameColor
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 10
                                Text {
                                    text: "Local data"
                                    color: bridge.primaryColor
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                Text {
                                    text: "Your library and progress are stored in a local SQLite database. Downloaded artwork stays cached on this device."
                                    color: bridge.secondaryColor
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                                Repeater {
                                    model: [
                                        { label: "Library", value: bridge.homeStats.all + " saved titles" },
                                        { label: "Database", value: "Local SQLite · anime_tracker.db" },
                                        { label: "Artwork", value: "Cached on this device when downloaded" },
                                        { label: "Catalog metadata", value: "AniList + MangaBaka + TMDB" }
                                    ]
                                    delegate: RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: 12
                                        Text {
                                            text: modelData.label
                                            color: bridge.primaryColor
                                            font.pixelSize: 12
                                            font.weight: Font.DemiBold
                                            Layout.preferredWidth: 150
                                        }
                                        Text {
                                            text: modelData.value
                                            color: bridge.secondaryColor
                                            font.pixelSize: 12
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    height: 1
                                    color: bridge.frameColor
                                    opacity: 0.7
                                }
                                Text {
                                    text: "Troubleshooting report"
                                    color: bridge.primaryColor
                                    font.pixelSize: 13
                                    font.weight: Font.Bold
                                }
                                Text {
                                    text: "Exports the retained logs as one redacted report. The library database and cached artwork are excluded; review the report before sharing."
                                    color: bridge.secondaryColor
                                    font.pixelSize: 11
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Button {
                                        text: "Export diagnostics report"
                                        onClicked: bridge.requestDiagnosticsExport()
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                            }
                        }
                    }
                }

                // Work details
                Item {
                    id: workDetailsPage
                    readonly property bool selectedWorkIsReadingMedia: {
                        var mediaType = String(bridge.selectedWork.mediaType || "").toUpperCase()
                        var mediaFormat = String(bridge.selectedWork.format || "").toUpperCase()
                        return mediaType === "MANGA"
                            || ["MANGA", "NOVEL", "ONE_SHOT"].indexOf(mediaFormat) >= 0
                    }
                    Flickable {
                        id: detailScroll
                        anchors.fill: parent
                        clip: true
                        contentWidth: width
                        contentHeight: detailColumn.implicitHeight + 84
                        boundsBehavior: Flickable.StopAtBounds

                        ColumnLayout {
                            id: detailColumn
                            x: 42
                            y: 34
                            width: Math.max(1, detailScroll.width - 84)
                            spacing: 22

                            Button {
                                id: detailBackButton
                                text: "←"
                                Layout.preferredWidth: 42
                                Layout.preferredHeight: 42
                                padding: 0
                                font.pixelSize: 23
                                Accessible.name: "Back"
                                onClicked: bridge.goBack()
                                background: Rectangle {
                                    radius: 21
                                    color: detailBackButton.hovered ? bridge.surfaceAltFillColor : "transparent"
                                    border.width: detailBackButton.hovered ? 1 : 0
                                    border.color: bridge.borderColor
                                }
                            }

                            Rectangle {
                                id: detailHeroPanel
                                Layout.fillWidth: true
                                Layout.minimumHeight: 383
                                Layout.preferredHeight: Math.max(383, detailHeroRow.implicitHeight + 48)
                                radius: 22
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor

                                RowLayout {
                                    id: detailHeroRow
                                    anchors.fill: parent
                                    anchors.leftMargin: 24
                                    anchors.rightMargin: 28
                                    anchors.topMargin: 24
                                    anchors.bottomMargin: 24
                                    spacing: 30

                                    Rectangle {
                                        Layout.preferredWidth: 235
                                        Layout.preferredHeight: 335
                                        Layout.alignment: Qt.AlignTop
                                        radius: 14
                                        clip: true
                                        color: bridge.surfaceAltFillColor
                                        border.width: 1
                                        border.color: bridge.borderColor

                                        NekoRoundedImage {
                                            imageBridge: root.bridge
                                            id: detailHeroCover
                                            anchors.fill: parent
                                            url: bridge.selectedWork.coverSource || ""
                                            fillMode: Image.PreserveAspectCrop
                                            asynchronous: true
                                            cache: true
                                            radius: 14
                                        }
                                        Text {
                                            anchors.centerIn: parent
                                            visible: detailHeroCover.status !== Image.Ready
                                            text: {
                                                if (!String(bridge.selectedWork.coverSource || "").length)
                                                    return "NO COVER"
                                                return detailHeroCover.status === Image.Loading
                                                    ? "Loading artwork…" : "COVER UNAVAILABLE"
                                            }
                                            color: bridge.mutedColor
                                            font.pixelSize: 10
                                            font.weight: Font.Bold
                                        }
                                    }

                                    ColumnLayout {
                                        id: detailHeroInfo
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        Layout.alignment: Qt.AlignTop
                                        spacing: 10

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 10
                                            Text {
                                                Layout.fillWidth: true
                                                text: bridge.selectedWork.title || "Select a title"
                                                color: bridge.primaryColor
                                                font.pixelSize: 34
                                                font.weight: 850
                                                wrapMode: Text.WordWrap
                                            }
                                            ToolButton {
                                                id: detailHeroManageButton
                                                visible: (bridge.selectedWork.id || 0) !== 0
                                                Layout.preferredWidth: 42
                                                Layout.preferredHeight: 42
                                                padding: 0
                                                text: "⋮"
                                                font.pixelSize: 30
                                                font.weight: Font.Black
                                                onClicked: detailManagementMenu.open()
                                                background: Rectangle {
                                                    radius: bridge.cornerRadius + 2
                                                    color: detailHeroManageButton.hovered
                                                        ? bridge.surfaceAltFillColor : "transparent"
                                                    border.width: detailHeroManageButton.hovered ? 1 : 0
                                                    border.color: bridge.accentColor
                                                }
                                            }
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            visible: String(bridge.selectedWork.nativeTitle || "").length > 0
                                            text: bridge.selectedWork.nativeTitle || ""
                                            color: bridge.mutedColor
                                            font.pixelSize: 12
                                            wrapMode: Text.WordWrap
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            text: {
                                                var parts = []
                                                if (bridge.selectedWork.format)
                                                    parts.push(bridge.selectedWork.format)
                                                if (bridge.selectedWork.startYear)
                                                    parts.push(bridge.selectedWork.startYear)
                                                var isReading = workDetailsPage.selectedWorkIsReadingMedia
                                                if (isReading) {
                                                    if (bridge.selectedWork.chapterTotal)
                                                        parts.push(bridge.selectedWork.chapterTotal + " chapters")
                                                    if (bridge.selectedWork.volumeTotal)
                                                        parts.push(bridge.selectedWork.volumeTotal + " volumes")
                                                } else {
                                                    if (bridge.selectedWork.episodeTotal)
                                                        parts.push(bridge.selectedWork.episodeTotal + " eps")
                                                    if (bridge.selectedWork.chapterTotal)
                                                        parts.push(bridge.selectedWork.chapterTotal + " ch")
                                                }
                                                return parts.join("  ·  ")
                                            }
                                            color: bridge.secondaryColor
                                            font.pixelSize: 13
                                            wrapMode: Text.WordWrap
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            text: Number(bridge.selectedWork.score || 0) > 0
                                                ? "★  " + bridge.selectedWork.score + "%"
                                                : "—  No score"
                                            color: bridge.accentColor
                                            font.pixelSize: 18
                                            font.weight: 800
                                        }

                                        Item { Layout.preferredHeight: 10 }

                                        Text {
                                            Layout.fillWidth: true
                                            text: bridge.selectedWork.synopsis || "No description saved locally."
                                            color: bridge.secondaryColor
                                            font.pixelSize: 14
                                            wrapMode: Text.WordWrap
                                            textFormat: Text.RichText
                                        }

                                        Item { Layout.fillHeight: true }
                                    }
                                }
                            }

                            ColumnLayout {
                                id: readingProgressPanel
                                visible: workDetailsPage.selectedWorkIsReadingMedia
                                Layout.fillWidth: true
                                spacing: 0

                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: readingProgressColumn.implicitHeight + 38
                                    radius: 18
                                    color: bridge.surfaceFillColor
                                    border.width: 1
                                    border.color: bridge.frameColor

                                    ColumnLayout {
                                        id: readingProgressColumn
                                        anchors.fill: parent
                                        anchors.margins: 20
                                        spacing: 14

                                        RowLayout {
                                            Layout.fillWidth: true
                                            Text {
                                                text: "Reading progress"
                                                color: bridge.primaryColor
                                                font.pixelSize: 17
                                                font.weight: 800
                                            }
                                            Item { Layout.fillWidth: true }
                                            ToolButton {
                                                id: readingEntryButton
                                                visible: (bridge.selectedWork.readingMembers || []).length > 1
                                                text: {
                                                    var members = bridge.selectedWork.readingMembers || []
                                                    var selectedId = bridge.selectedWork.selectedEpisodeWorkId || 0
                                                    for (var i = 0; i < members.length; i++) {
                                                        if (members[i].id === selectedId)
                                                            return "Entry " + (i + 1) + "  ▾"
                                                    }
                                                    return "Entry 1  ▾"
                                                }
                                                onClicked: readingEntryMenu.open()
                                                background: Rectangle {
                                                    radius: 7
                                                    color: readingEntryButton.hovered
                                                        ? bridge.surfaceAltFillColor : "transparent"
                                                    border.width: 1
                                                    border.color: bridge.borderColor
                                                }
                                            }
                                            Menu {
                                                id: readingEntryMenu
                                                Repeater {
                                                    model: bridge.selectedWork.readingMembers || []
                                                    delegate: MenuItem {
                                                        required property var modelData
                                                        required property int index
                                                        text: "Entry " + (index + 1) + " — " + (modelData.title || "Untitled")
                                                        onTriggered: bridge.selectEpisodeMember(modelData.id)
                                                    }
                                                }
                                            }
                                        }

                                        Text {
                                            visible: !(bridge.selectedWork.isInLibrary || false)
                                            Layout.fillWidth: true
                                            text: "Reading progress is saved to your Library and restored when you return."
                                            color: bridge.mutedColor
                                            font.pixelSize: 11
                                            wrapMode: Text.WordWrap
                                        }
                                        Button {
                                            visible: !(bridge.selectedWork.isInLibrary || false)
                                            text: "＋  Track this work in Library"
                                            onClicked: bridge.requestAddSelectedWork()
                                        }

                                        ColumnLayout {
                                            id: readingProgressRow
                                            Layout.fillWidth: true
                                            spacing: 10
                                            property int readingMemberId: {
                                                var members = bridge.selectedWork.readingMembers || []
                                                var selectedId = bridge.selectedWork.selectedEpisodeWorkId || 0
                                                for (var i = 0; i < members.length; i++) {
                                                    if (members[i].id === selectedId)
                                                        return selectedId
                                                }
                                                return members.length > 0 ? members[0].id : (bridge.selectedWork.id || 0)
                                            }
                                            readonly property var selectedReadingProgress: {
                                                var progress = bridge.selectedWork.readingProgressByWork || {}
                                                return progress[readingProgressRow.readingMemberId.toString()] || {}
                                            }
                                            readonly property int chapterTotal: selectedReadingProgress.chapterTotal
                                                || bridge.selectedWork.chapterTotal || 0
                                            readonly property int volumeTotal: selectedReadingProgress.volumeTotal
                                                || bridge.selectedWork.volumeTotal || 0

                                            Rectangle {
                                                Layout.fillWidth: true
                                                implicitHeight: chapterProgressColumn.implicitHeight + 24
                                                radius: 12
                                                color: bridge.surfaceAltFillColor
                                                border.width: 1
                                                border.color: bridge.borderColor
                                                ColumnLayout {
                                                    id: chapterProgressColumn
                                                    anchors.fill: parent
                                                    anchors.margins: 12
                                                    spacing: 8
                                                    RowLayout {
                                                        Layout.fillWidth: true
                                                        Text {
                                                            text: "Chapters"
                                                            color: bridge.primaryColor
                                                            font.pixelSize: 14
                                                            font.weight: Font.Bold
                                                        }
                                                        Item { Layout.fillWidth: true }
                                                        Text {
                                                            text: (readingProgressRow.selectedReadingProgress.chapters || 0)
                                                                + " / " + (readingProgressRow.chapterTotal || "unknown") + " read"
                                                            color: bridge.accentColor
                                                            font.pixelSize: 11
                                                            font.weight: Font.Bold
                                                        }
                                                    }
                                                    Rectangle {
                                                        Layout.fillWidth: true
                                                        Layout.preferredHeight: 7
                                                        visible: readingProgressRow.chapterTotal > 0
                                                        radius: 3
                                                        color: bridge.backgroundColor
                                                        Rectangle {
                                                            width: parent.width * Math.min(1,
                                                                (readingProgressRow.selectedReadingProgress.chapters || 0)
                                                                / Math.max(1, readingProgressRow.chapterTotal))
                                                            height: parent.height
                                                            radius: 3
                                                            color: bridge.accentColor
                                                        }
                                                    }
                                                    RowLayout {
                                                        Layout.fillWidth: true
                                                        Text {
                                                            Layout.fillWidth: true
                                                            text: readingProgressRow.chapterTotal > 0
                                                                ? "How many have you read?"
                                                                : "Enter the number you've read; the total is not known."
                                                            color: bridge.mutedColor
                                                            font.pixelSize: 11
                                                            wrapMode: Text.WordWrap
                                                        }
                                                        NekoSpinBox {
                                                            bridge: root.bridge
                                                            id: chapterProgressSpin
                                                            Layout.preferredWidth: 110
                                                            from: 0
                                                            to: Math.max(100000, readingProgressRow.chapterTotal)
                                                            editable: true
                                                            enabled: bridge.selectedWork.isInLibrary || false
                                                            value: readingProgressRow.selectedReadingProgress.chapters || 0
                                                            onValueModified: bridge.setReadingProgressWithTotal(
                                                                readingProgressRow.readingMemberId,
                                                                "chapter", value, readingProgressRow.chapterTotal
                                                            )
                                                        }
                                                    }
                                                }
                                            }

                                            Rectangle {
                                                Layout.fillWidth: true
                                                implicitHeight: volumeProgressColumn.implicitHeight + 24
                                                radius: 12
                                                color: bridge.surfaceAltFillColor
                                                border.width: 1
                                                border.color: bridge.borderColor
                                                ColumnLayout {
                                                    id: volumeProgressColumn
                                                    anchors.fill: parent
                                                    anchors.margins: 12
                                                    spacing: 8
                                                    RowLayout {
                                                        Layout.fillWidth: true
                                                        Text {
                                                            text: "Volumes"
                                                            color: bridge.primaryColor
                                                            font.pixelSize: 14
                                                            font.weight: Font.Bold
                                                        }
                                                        Item { Layout.fillWidth: true }
                                                        Text {
                                                            text: (readingProgressRow.selectedReadingProgress.volumes || 0)
                                                                + " / " + (readingProgressRow.volumeTotal || "unknown") + " read"
                                                            color: bridge.accentColor
                                                            font.pixelSize: 11
                                                            font.weight: Font.Bold
                                                        }
                                                    }
                                                    Rectangle {
                                                        Layout.fillWidth: true
                                                        Layout.preferredHeight: 7
                                                        visible: readingProgressRow.volumeTotal > 0
                                                        radius: 3
                                                        color: bridge.backgroundColor
                                                        Rectangle {
                                                            width: parent.width * Math.min(1,
                                                                (readingProgressRow.selectedReadingProgress.volumes || 0)
                                                                / Math.max(1, readingProgressRow.volumeTotal))
                                                            height: parent.height
                                                            radius: 3
                                                            color: bridge.accentColor
                                                        }
                                                    }
                                                    RowLayout {
                                                        Layout.fillWidth: true
                                                        Text {
                                                            Layout.fillWidth: true
                                                            text: readingProgressRow.volumeTotal > 0
                                                                ? "How many have you read?"
                                                                : "Enter the number you've read; the total is not known."
                                                            color: bridge.mutedColor
                                                            font.pixelSize: 11
                                                            wrapMode: Text.WordWrap
                                                        }
                                                        NekoSpinBox {
                                                            bridge: root.bridge
                                                            id: volumeProgressSpin
                                                            Layout.preferredWidth: 110
                                                            from: 0
                                                            to: Math.max(100000, readingProgressRow.volumeTotal)
                                                            editable: true
                                                            enabled: bridge.selectedWork.isInLibrary || false
                                                            value: readingProgressRow.selectedReadingProgress.volumes || 0
                                                            onValueModified: bridge.setReadingProgressWithTotal(
                                                                readingProgressRow.readingMemberId,
                                                                "volume", value, readingProgressRow.volumeTotal
                                                            )
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                id: episodeSectionPanel
                                visible: !workDetailsPage.selectedWorkIsReadingMedia
                                Layout.fillWidth: true
                                implicitHeight: episodeSectionColumn.implicitHeight + 28
                                radius: 14
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor

                                ColumnLayout {
                                    id: episodeSectionColumn
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 10

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            Layout.fillWidth: true
                                            text: {
                                                var members = bridge.selectedWork.bundleMembers || []
                                                var selectedId = bridge.selectedWork.selectedEpisodeWorkId || 0
                                                if (members.length > 1) {
                                                    for (var i = 0; i < members.length; i++) {
                                                        if (members[i].id === selectedId)
                                                            return members[i].title || "Episodes"
                                                    }
                                                }
                                                return "Episodes"
                                            }
                                            color: bridge.primaryColor
                                            font.pixelSize: 19
                                            font.weight: 850
                                            wrapMode: Text.WordWrap
                                        }
                                        Text {
                                            text: {
                                                var total = bridge.episodeItems.length
                                                var watched = 0
                                                for (var i = 0; i < total; i++) {
                                                    if (bridge.episodeItems[i].watched)
                                                        watched++
                                                }
                                                return total > 0 ? watched + " / " + total + " watched" : "No episode list saved"
                                            }
                                            color: bridge.accentColor
                                            font.pixelSize: 13
                                            font.weight: 850
                                        }
                                        ToolButton {
                                            id: episodeMemberButton
                                            visible: (bridge.selectedWork.bundleMembers || []).length > 1
                                            text: {
                                                var members = bridge.selectedWork.bundleMembers || []
                                                var selectedId = bridge.selectedWork.selectedEpisodeWorkId || 0
                                                for (var i = 0; i < members.length; i++) {
                                                    if (members[i].id === selectedId)
                                                        return (members[i].title || "Choose title") + "  ▾"
                                                }
                                                return "Choose title  ▾"
                                            }
                                            onClicked: episodeMemberMenu.open()
                                            background: Rectangle {
                                                radius: 7
                                                color: episodeMemberButton.hovered
                                                    ? bridge.surfaceAltFillColor : "transparent"
                                                border.width: 1
                                                border.color: bridge.borderColor
                                            }
                                        }
                                        Menu {
                                            id: episodeMemberMenu
                                            Repeater {
                                                model: bridge.selectedWork.bundleMembers || []
                                                delegate: MenuItem {
                                                    required property var modelData
                                                    text: modelData.title || "Untitled"
                                                    onTriggered: bridge.selectEpisodeMember(modelData.id)
                                                }
                                            }
                                        }
                                    }

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 10
                                        Text {
                                            text: "Watched through"
                                            color: bridge.secondaryColor
                                            font.pixelSize: 13
                                            font.weight: Font.DemiBold
                                        }
                                        NekoSpinBox {
                                            bridge: root.bridge
                                            id: episodeProgressSpin
                                            from: 0
                                            to: bridge.episodeItems.length
                                            editable: true
                                            Layout.preferredWidth: 120
                                            value: {
                                                var count = 0
                                                for (var i = 0; i < bridge.episodeItems.length; i++) {
                                                    if (!bridge.episodeItems[i].watched)
                                                        break
                                                    count++
                                                }
                                                return count
                                            }
                                        }
                                        Text {
                                            text: "/ " + bridge.episodeItems.length
                                            color: bridge.mutedColor
                                            font.pixelSize: 11
                                        }
                                        Item { Layout.fillWidth: true }
                                        Button {
                                            text: "Apply progress"
                                            enabled: bridge.episodeItems.length > 0
                                            onClicked: bridge.setEpisodeProgressThrough(
                                                bridge.selectedWork.selectedEpisodeWorkId || bridge.selectedWork.id,
                                                episodeProgressSpin.value
                                            )
                                        }
                                        Button {
                                            text: "Mark all watched"
                                            enabled: bridge.episodeItems.length > 0
                                            onClicked: bridge.markAllEpisodesWatched(
                                                bridge.selectedWork.selectedEpisodeWorkId || bridge.selectedWork.id,
                                                true
                                            )
                                        }
                                    }

                                    GridView {
                                        id: episodesGrid
                                        Layout.fillWidth: true
                                        visible: bridge.episodeItems.length > 0
                                        Layout.preferredHeight: visible ? Math.max(
                                            260,
                                            Math.ceil(bridge.episodeItems.length
                                                / Math.max(1, Math.floor(width / cellWidth))) * cellHeight
                                        ) : 0
                                        cellWidth: 252
                                        cellHeight: 274
                                        clip: true
                                        boundsBehavior: Flickable.StopAtBounds
                                        interactive: false
                                        model: bridge.episodeItems

                                        delegate: Rectangle {
                                            required property var modelData
                                            width: 240
                                            height: 260
                                            radius: 12
                                            color: bridge.surfaceAltFillColor
                                            border.width: 1
                                            border.color: bridge.borderColor

                                            ColumnLayout {
                                                anchors.fill: parent
                                                anchors.margins: 8
                                                spacing: 6

                                                Rectangle {
                                                    Layout.preferredWidth: 220
                                                    Layout.preferredHeight: 124
                                                    Layout.alignment: Qt.AlignHCenter
                                                    radius: 8
                                                    clip: true
                                                    color: bridge.backgroundColor
                                                    NekoImage {
                                                        imageBridge: root.bridge
                                                        id: episodeArtwork
                                                        anchors.fill: parent
                                                        url: modelData.coverSource || ""
                                                        fillMode: Image.PreserveAspectCrop
                                                        asynchronous: true
                                                        cache: true
                                                    }
                                                    Text {
                                                        anchors.centerIn: parent
                                                        visible: episodeArtwork.status !== Image.Ready
                                                        text: "UNAVAILABLE"
                                                        color: bridge.mutedColor
                                                        font.pixelSize: 9
                                                        font.weight: Font.Bold
                                                    }
                                                }

                                                Text {
                                                    Layout.fillWidth: true
                                                    Layout.preferredHeight: 36
                                                    text: modelData.title || ("Episode " + modelData.episodeNumber)
                                                    color: bridge.primaryColor
                                                    font.pixelSize: 13
                                                    font.weight: Font.DemiBold
                                                    wrapMode: Text.WordWrap
                                                    maximumLineCount: 2
                                                    elide: Text.ElideRight
                                                    verticalAlignment: Text.AlignTop
                                                }

                                                Text {
                                                    Layout.fillWidth: true
                                                    Layout.preferredHeight: visible ? 32 : 0
                                                    visible: String(modelData.description || "").trim().length > 0
                                                    text: modelData.description || ""
                                                    color: bridge.secondaryColor
                                                    font.pixelSize: 10
                                                    wrapMode: Text.WordWrap
                                                    maximumLineCount: 2
                                                    elide: Text.ElideRight
                                                    verticalAlignment: Text.AlignTop
                                                }

                                                Item { Layout.fillHeight: true }

                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    Layout.preferredHeight: 18
                                                    spacing: 5
                                                    Text {
                                                        text: "EP " + ((modelData.episodeNumber || 0) < 10 ? "0" : "")
                                                            + (modelData.episodeNumber || 0)
                                                        color: bridge.accentColor
                                                        font.pixelSize: 9
                                                        font.weight: Font.Bold
                                                    }
                                                    Text {
                                                        Layout.fillWidth: true
                                                        visible: String(modelData.airDate || "").length > 0
                                                        text: modelData.airDate || ""
                                                        color: bridge.mutedColor
                                                        font.pixelSize: 9
                                                        elide: Text.ElideRight
                                                    }
                                                    NekoCheckBox {
                                                        bridge: root.bridge
                                                        text: "Watched"
                                                        checked: modelData.watched
                                                        enabled: bridge.selectedWork.isInLibrary || false
                                                        font.pixelSize: 10
                                                        onToggled: bridge.setEpisodeWatched(
                                                            modelData.workId || bridge.selectedWork.selectedEpisodeWorkId || bridge.selectedWork.id,
                                                            modelData.episodeNumber,
                                                            checked
                                                        )
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    Text {
                                        visible: bridge.episodeItems.length === 0 && !(bridge.selectedWork.detailsLoading || bridge.selectedWork.metadataRefreshing || false)
                                        Layout.fillWidth: true
                                        text: "No episode data is available for this season."
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                    }
                                    Text {
                                        visible: bridge.episodeItems.length === 0 && (bridge.selectedWork.detailsLoading || false)
                                        Layout.fillWidth: true
                                        text: "Loading episode data…"
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                    }
                                }
                            }

                            Rectangle {
                                id: mangaBakaMetadataPanel
                                visible: Object.keys(bridge.selectedWork.mangabakaMetadata || {}).length > 0
                                    || (bridge.selectedWork.mangabakaVolumeRecords || []).length > 0
                                    || (bridge.selectedWork.mangabakaNews || []).length > 0
                                Layout.fillWidth: true
                                implicitHeight: mangaMetadataColumn.implicitHeight + 38
                                radius: 18
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor

                                ColumnLayout {
                                    id: mangaMetadataColumn
                                    anchors.fill: parent
                                    anchors.margins: 20
                                    spacing: 10
                                    Text {
                                        text: "MangaBaka metadata"
                                        color: bridge.primaryColor
                                        font.pixelSize: 17
                                        font.weight: 850
                                    }

                                    Repeater {
                                        model: {
                                            var m = bridge.selectedWork.mangabakaMetadata || {}
                                            var rows = []
                                            function values(raw, keys) {
                                                var entries = Array.isArray(raw) ? raw : ((raw === null || raw === undefined || raw === "") ? [] : [raw])
                                                var out = []
                                                for (var i = 0; i < entries.length; i++) {
                                                    var entry = entries[i]
                                                    var value = ""
                                                    if (entry && typeof entry === "object") {
                                                        for (var j = 0; j < keys.length; j++) {
                                                            if (entry[keys[j]]) {
                                                                value = String(entry[keys[j]])
                                                                break
                                                            }
                                                        }
                                                    } else {
                                                        value = String(entry || "").trim()
                                                    }
                                                    if (value && out.indexOf(value) < 0)
                                                        out.push(value)
                                                }
                                                return out
                                            }
                                            var published = m.published || {}
                                            var publishedText = typeof published === "object"
                                                ? [published.start_date || published.start || "", published.end_date || published.end || ""].filter(Boolean).join(" – ")
                                                : String(published || "")
                                            var series = []
                                            if (m.type) series.push(String(m.type).replace(/_/g, " ").replace(/\b\w/g, function(c) { return c.toUpperCase() }))
                                            if (m.status) series.push(String(m.status).replace(/_/g, " ").replace(/\b\w/g, function(c) { return c.toUpperCase() }))
                                            if (m.state) series.push("Catalog record: " + String(m.state).replace(/_/g, " "))
                                            if (m.rating !== undefined && m.rating !== null) series.push("Rating " + m.rating + "/100")
                                            if (m.content_rating) series.push("Content: " + m.content_rating)
                                            if (m.is_licensed !== undefined && m.is_licensed !== null) series.push(m.is_licensed ? "Licensed" : "Unlicensed")
                                            if (publishedText) series.push("Published " + publishedText)
                                            if (m.last_updated_at) series.push("Metadata updated " + m.last_updated_at)
                                            if (series.length) rows.push({label: "Series", value: series.join(" · ")})
                                            if (m.total_chapters !== undefined && m.total_chapters !== null) rows.push({label: "Chapters", value: String(m.total_chapters)})
                                            if (m.final_volume !== undefined && m.final_volume !== null) rows.push({label: "Final volume", value: String(m.final_volume)})
                                            var authors = values(m.authors, ["name", "title", "name_path"])
                                            if (authors.length) rows.push({label: "Authors", value: authors.join(", ")})
                                            var artists = values(m.artists, ["name", "title", "name_path"])
                                            if (artists.length) rows.push({label: "Artists", value: artists.join(", ")})
                                            var publishers = values(m.publishers, ["name", "title", "name_path"])
                                            if (publishers.length) rows.push({label: "Publishers", value: publishers.join(", ")})
                                            var tags = Array.isArray(m.tags) ? m.tags : []
                                            var genres = values(m.genres, ["name", "title", "name_path"])
                                            var otherTags = []
                                            for (var t = 0; t < tags.length; t++) {
                                                var tag = tags[t]
                                                if (!tag || typeof tag !== "object" || tag.is_explicit)
                                                    continue
                                                var tagName = String(tag.name_path || tag.name || "").trim()
                                                if (!tagName) continue
                                                if (tag.is_genre) {
                                                    if (genres.indexOf(tagName) < 0) genres.push(tagName)
                                                } else if (otherTags.indexOf(tagName) < 0) {
                                                    otherTags.push(tagName)
                                                }
                                            }
                                            if (genres.length) rows.push({label: "Genres", value: genres.join(", ")})
                                            if (otherTags.length) rows.push({label: "Tags", value: otherTags.join(", ")})
                                            var titles = Array.isArray(m.titles) ? m.titles : []
                                            titles = titles.filter(function(item) { return item && item.title })
                                            titles.sort(function(a, b) { return (b.is_primary ? 1 : 0) - (a.is_primary ? 1 : 0) })
                                            if (titles.length) rows.push({label: "Known titles", value: titles.slice(0, 14).map(function(item) {
                                                return String(item.language || "other") + ": " + String(item.title)
                                                    + ((item.traits || []).length ? " (" + item.traits.join(", ") + ")" : "")
                                            }).join(" | ")})
                                            var links = Array.isArray(m.links) ? m.links.slice(0, 12) : []
                                            if (links.length) rows.push({label: "External links", value: links.map(function(item) {
                                                return String(item.name_display || item.name || item.type || "Source")
                                                    + (item.url ? ": " + item.url : "")
                                            }).join(" | ")})
                                            return rows
                                        }
                                        delegate: RowLayout {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            spacing: 12
                                            Text {
                                                Layout.preferredWidth: 150
                                                text: modelData.label
                                                color: bridge.primaryColor
                                                font.pixelSize: 12
                                                font.weight: Font.DemiBold
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.value
                                                color: bridge.secondaryColor
                                                font.pixelSize: 12
                                                wrapMode: Text.WordWrap
                                            }
                                        }
                                    }

                                    Text {
                                        visible: (bridge.selectedWork.mangabakaVolumeRecords || []).length > 0
                                        Layout.fillWidth: true
                                        text: "Published volume records: " + (bridge.selectedWork.mangabakaVolumeRecords || []).slice(0, 16).map(function(item) {
                                            var label = item.title || ("Volume " + (item.number || "?"))
                                            var extras = []
                                            if (item.isbn) extras.push("ISBN " + item.isbn)
                                            if (item.published) extras.push(item.published)
                                            return label + (extras.length ? " (" + extras.join("; ") + ")" : "")
                                        }).join(" | ")
                                        color: bridge.secondaryColor
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                    }
                                    Text {
                                        visible: (bridge.selectedWork.mangabakaNews || []).length > 0
                                        Layout.fillWidth: true
                                        text: "MangaBaka news: " + (bridge.selectedWork.mangabakaNews || []).slice(0, 8).map(function(item) {
                                            return [item.title || item.headline || item.name || "",
                                                item.published_at || item.published || item.created_at || item.date || "",
                                                item.summary || item.description || item.excerpt || "",
                                                item.url || item.link || ""].filter(Boolean).join(" — ")
                                        }).join(" | ")
                                        color: bridge.secondaryColor
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Metadata aggregated by MangaBaka; source-site data remains subject to its own terms."
                                        color: bridge.mutedColor
                                        font.pixelSize: 10
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }

                            Rectangle {
                                id: charactersSectionPanel
                                Layout.fillWidth: true
                                implicitHeight: charactersSectionColumn.implicitHeight + 38
                                radius: 18
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor
                                ColumnLayout {
                                    id: charactersSectionColumn
                                    anchors.fill: parent
                                    anchors.margins: 20
                                    spacing: 12
                                    Text {
                                        text: "Characters"
                                        color: bridge.primaryColor
                                        font.pixelSize: 17
                                        font.weight: 800
                                    }
                                    Text {
                                        visible: (bridge.selectedWork.characters || []).length === 0
                                            && (bridge.selectedWork.detailsLoading || false)
                                        text: "Loading character credits…"
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                    }
                                    GridView {
                                        id: detailCharactersGrid
                                        Layout.fillWidth: true
                                        visible: (bridge.selectedWork.characters || []).length > 0
                                        cellWidth: Math.max(260, width / 4)
                                        cellHeight: 152
                                        Layout.preferredHeight: visible ? Math.ceil((bridge.selectedWork.characters || []).length
                                            / Math.max(1, Math.floor(width / cellWidth))) * cellHeight : 0
                                        clip: true
                                        interactive: false
                                        model: bridge.selectedWork.characters || []
                                        delegate: Rectangle {
                                            id: detailCharacterCard
                                            required property var modelData
                                            width: detailCharactersGrid.cellWidth - 8
                                            height: 140
                                            radius: bridge.cornerRadius
                                            color: characterCardMouseArea.containsMouse
                                                ? bridge.cardHoverFillColor : bridge.cardFillColor
                                            border.width: 2
                                            border.color: bridge.frameColor

                                            MouseArea {
                                                id: characterCardMouseArea
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: bridge.requestOpenProfile("character", modelData.id, modelData.name)
                                            }

                                            RowLayout {
                                                anchors.fill: parent
                                                anchors.margins: 12
                                                spacing: 8

                                                Item {
                                                    Layout.preferredWidth: 88
                                                    Layout.preferredHeight: 116
                                                    NekoRoundedImage {
                                                        imageBridge: root.bridge
                                                        id: characterPicture
                                                        anchors.fill: parent
                                                        url: modelData.coverSource || ""
                                                        fillMode: Image.PreserveAspectCrop
                                                        asynchronous: true
                                                        cache: true
                                                        radius: 14
                                                    }
                                                    Rectangle {
                                                        anchors.fill: parent
                                                        radius: 14
                                                        color: "transparent"
                                                        border.width: characterPicture.status === Image.Ready ? 3 : 0
                                                        border.color: bridge.frameColor
                                                    }
                                                }

                                                ColumnLayout {
                                                    Layout.fillWidth: true
                                                    Layout.fillHeight: true
                                                    Layout.minimumWidth: 0
                                                    spacing: 0
                                                    Text {
                                                        Layout.fillWidth: true
                                                        visible: String(modelData.role || "").length > 0
                                                        text: String(modelData.role || "")
                                                            .replace(/_/g, " ")
                                                            .toLowerCase()
                                                            .replace(/\b\w/g, function(c) { return c.toUpperCase() })
                                                        color: bridge.primaryColor
                                                        font.pixelSize: 13
                                                        font.weight: 700
                                                        wrapMode: Text.WordWrap
                                                        horizontalAlignment: Text.AlignHCenter
                                                        verticalAlignment: Text.AlignTop
                                                    }
                                                    RowLayout {
                                                        Layout.fillWidth: true
                                                        Layout.fillHeight: true
                                                        spacing: 18
                                                        Text {
                                                            Layout.fillWidth: true
                                                            text: modelData.name || "Unknown character"
                                                            color: bridge.primaryColor
                                                            font.pixelSize: 13
                                                            font.weight: 600
                                                            wrapMode: Text.WordWrap
                                                            verticalAlignment: Text.AlignVCenter
                                                        }
                                                        Text {
                                                            id: characterVoiceActorName
                                                            Layout.fillWidth: true
                                                            visible: String(modelData.voiceActorName || "").length > 0
                                                            text: modelData.voiceActorName || ""
                                                            color: bridge.primaryColor
                                                            font.pixelSize: 13
                                                            font.weight: 600
                                                            wrapMode: Text.WordWrap
                                                            horizontalAlignment: Text.AlignRight
                                                            verticalAlignment: Text.AlignVCenter
                                                            MouseArea {
                                                                anchors.fill: parent
                                                                enabled: (modelData.voiceActorId || 0) > 0
                                                                cursorShape: Qt.PointingHandCursor
                                                                onClicked: bridge.requestOpenProfile(
                                                                    "voice_actor",
                                                                    modelData.voiceActorId,
                                                                    modelData.voiceActorName
                                                                )
                                                            }
                                                        }
                                                    }
                                                }

                                                Item {
                                                    Layout.preferredWidth: 88
                                                    Layout.preferredHeight: 116
                                                    NekoRoundedImage {
                                                        imageBridge: root.bridge
                                                        id: voiceActorPicture
                                                        anchors.fill: parent
                                                        visible: String(modelData.voiceActorName || "").length > 0
                                                        url: modelData.voiceActorCoverSource || ""
                                                        fillMode: Image.PreserveAspectCrop
                                                        asynchronous: true
                                                        cache: true
                                                        radius: 14
                                                    }
                                                    Rectangle {
                                                        anchors.fill: parent
                                                        visible: String(modelData.voiceActorName || "").length > 0
                                                        radius: 14
                                                        color: "transparent"
                                                        border.width: voiceActorPicture.status === Image.Ready ? 3 : 0
                                                        border.color: bridge.frameColor
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Text {
                                        visible: (bridge.selectedWork.characters || []).length === 0
                                            && !(bridge.selectedWork.detailsLoading || false)
                                        Layout.fillWidth: true
                                        text: "Nothing stored locally yet."
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }

                            Rectangle {
                                id: staffSectionPanel
                                Layout.fillWidth: true
                                implicitHeight: staffSectionColumn.implicitHeight + 38
                                radius: 18
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor
                                ColumnLayout {
                                    id: staffSectionColumn
                                    anchors.fill: parent
                                    anchors.margins: 20
                                    spacing: 12
                                    Text {
                                        text: "Staff"
                                        color: bridge.primaryColor
                                        font.pixelSize: 17
                                        font.weight: 800
                                    }
                                    Text {
                                        visible: (bridge.selectedWork.staff || []).length === 0
                                            && (bridge.selectedWork.detailsLoading || false)
                                        text: "Loading staff credits…"
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                    }
                                    GridView {
                                        id: detailStaffGrid
                                        Layout.fillWidth: true
                                        visible: (bridge.selectedWork.staff || []).length > 0
                                        cellWidth: 196
                                        cellHeight: 235
                                        Layout.preferredHeight: visible ? Math.ceil((bridge.selectedWork.staff || []).length
                                            / Math.max(1, Math.floor(width / cellWidth))) * cellHeight : 0
                                        clip: true
                                        interactive: false
                                        model: bridge.selectedWork.staff || []
                                        delegate: Rectangle {
                                            id: detailStaffCard
                                            required property var modelData
                                            width: 180
                                            height: 215
                                            radius: bridge.cornerRadius
                                            color: staffCardMouseArea.containsMouse
                                                ? bridge.cardHoverFillColor : bridge.cardFillColor
                                            border.width: 2
                                            border.color: bridge.frameColor
                                            ColumnLayout {
                                                anchors.fill: parent
                                                anchors.margins: 12
                                                spacing: 8
                                                Item {
                                                    Layout.preferredWidth: 120
                                                    Layout.preferredHeight: 120
                                                    Layout.alignment: Qt.AlignHCenter
                                                    NekoRoundedImage {
                                                        imageBridge: root.bridge
                                                        id: staffPicture
                                                        anchors.fill: parent
                                                        url: modelData.coverSource || ""
                                                        fillMode: Image.PreserveAspectCrop
                                                        asynchronous: true
                                                        cache: true
                                                        radius: 14
                                                    }
                                                    Rectangle {
                                                        anchors.fill: parent
                                                        radius: 14
                                                        color: "transparent"
                                                        border.width: staffPicture.status === Image.Ready ? 3 : 0
                                                        border.color: bridge.frameColor
                                                    }
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: modelData.name || "Unknown staff"
                                                    color: bridge.primaryColor
                                                    font.pixelSize: 13
                                                    font.weight: 600
                                                    horizontalAlignment: Text.AlignHCenter
                                                    wrapMode: Text.WordWrap
                                                    maximumLineCount: 2
                                                    elide: Text.ElideRight
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: modelData.role || ""
                                                    color: bridge.mutedColor
                                                    font.pixelSize: 11
                                                    horizontalAlignment: Text.AlignHCenter
                                                    wrapMode: Text.WordWrap
                                                    maximumLineCount: 3
                                                    elide: Text.ElideRight
                                                }
                                            }
                                            MouseArea {
                                                id: staffCardMouseArea
                                                anchors.fill: parent
                                                z: 1
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: bridge.requestOpenProfile("staff", modelData.id, modelData.name)
                                            }
                                        }
                                    }
                                    Text {
                                        visible: (bridge.selectedWork.staff || []).length === 0
                                            && !(bridge.selectedWork.detailsLoading || false)
                                        Layout.fillWidth: true
                                        text: "Nothing stored locally yet."
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }

                            Rectangle {
                                id: relationsSectionPanel
                                Layout.fillWidth: true
                                implicitHeight: relationsSectionColumn.implicitHeight + 38
                                radius: 18
                                color: bridge.surfaceFillColor
                                border.width: 1
                                border.color: bridge.frameColor
                                ColumnLayout {
                                    id: relationsSectionColumn
                                    anchors.fill: parent
                                    anchors.margins: 20
                                    spacing: 12
                                    Text {
                                        text: "Relations"
                                        color: bridge.primaryColor
                                        font.pixelSize: 17
                                        font.weight: 800
                                    }
                                    Text {
                                        visible: (bridge.selectedWork.relations || []).length === 0
                                            && (bridge.selectedWork.detailsLoading || false)
                                        text: "Loading related works…"
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                    }
                                    GridView {
                                        id: detailRelationsGrid
                                        Layout.fillWidth: true
                                        visible: (bridge.selectedWork.relations || []).length > 0
                                        cellWidth: bridge.cardSize + 20
                                        cellHeight: bridge.coverHeight + 76
                                        Layout.preferredHeight: visible ? Math.ceil((bridge.selectedWork.relations || []).length
                                            / Math.max(1, Math.floor(width / cellWidth))) * cellHeight : 0
                                        clip: true
                                        interactive: false
                                        model: bridge.selectedWork.relations || []
                                        delegate: Rectangle {
                                            required property var modelData
                                            width: bridge.cardSize + 8
                                            height: bridge.coverHeight + 66
                                            radius: bridge.cornerRadius + 2
                                            color: "transparent"
                                            border.width: 2
                                            border.color: bridge.frameColor
                                            ColumnLayout {
                                                anchors.fill: parent
                                                anchors.margins: 2
                                                spacing: 8
                                                NekoRoundedImage {
                                                    imageBridge: root.bridge
                                                    Layout.preferredWidth: bridge.cardSize
                                                    Layout.preferredHeight: bridge.coverHeight
                                                    Layout.alignment: Qt.AlignHCenter
                                                    url: modelData.coverSource || ""
                                                    fillMode: Image.PreserveAspectCrop
                                                    asynchronous: true
                                                    cache: true
                                                    radius: bridge.cornerRadius
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    Layout.preferredHeight: bridge.titleHeight
                                                    text: modelData.title || "Related work"
                                                    color: bridge.primaryColor
                                                    font.pixelSize: bridge.fontSize
                                                    font.weight: Font.Bold
                                                    wrapMode: Text.WordWrap
                                                    maximumLineCount: 2
                                                    elide: Text.ElideRight
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: [modelData.title || "Related work",
                                                        String(modelData.relationTypes || "RELATED").replace(/_/g, " ").toLowerCase()]
                                                        .filter(Boolean).join("  →  ")
                                                    color: bridge.mutedColor
                                                    font.pixelSize: 10
                                                    wrapMode: Text.WordWrap
                                                    maximumLineCount: 2
                                                    elide: Text.ElideRight
                                                }
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                z: 1
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: bridge.requestOpenRelatedWork(
                                                    modelData.id, modelData.title, modelData.mediaType,
                                                    modelData.format, modelData.coverSource
                                                )
                                            }
                                        }
                                    }
                                    Text {
                                        visible: (bridge.selectedWork.relations || []).length === 0
                                            && !(bridge.selectedWork.detailsLoading || false)
                                        Layout.fillWidth: true
                                        text: "Nothing stored locally yet."
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }

                        }
                    }
                    Menu {
                        id: detailManagementMenu
                        title: "Manage title"
                        MenuItem {
                            text: "Auto-bundle related works"
                            enabled: bridge.selectedWork.isInLibrary || false
                            onTriggered: bridge.requestDetailAction("auto_bundle")
                        }
                        MenuItem {
                            text: "Add to bundle…"
                            enabled: bridge.selectedWork.isInLibrary || false
                            onTriggered: bridge.requestDetailAction("add_to_bundle")
                        }
                        MenuItem {
                            text: "Remove bundled item…"
                            visible: (bridge.selectedWork.seriesCount || 1) > 1
                            enabled: bridge.selectedWork.isInLibrary || false
                            onTriggered: bridge.requestDetailAction("remove_from_bundle")
                        }
                        MenuItem {
                            text: (bridge.selectedWork.seriesCount || 1) > 1
                                ? "Edit bundle appearance…" : "Customize title and cover…"
                            visible: (bridge.selectedWork.id || 0) !== 0
                            onTriggered: {
                                if ((bridge.selectedWork.seriesCount || 1) > 1
                                        && (bridge.selectedWork.isInLibrary || false))
                                    bridge.requestEditBundle(bridge.selectedWork.id)
                                else
                                    bridge.requestDetailAction("customize_identity")
                            }
                        }
                        MenuSeparator {}
                        MenuItem {
                            text: "Delete from Library"
                            visible: bridge.selectedWork.isInLibrary || false
                            onTriggered: bridge.requestDeleteWork(bridge.selectedWork.id)
                        }
                    }
                }

                // Entity profile
                Item {
                    id: entityProfilePage
                    Flickable {
                        id: profileScroll
                        anchors.fill: parent
                        clip: true
                        contentWidth: width
                        contentHeight: profileColumn.implicitHeight + 60
                        boundsBehavior: Flickable.StopAtBounds

                        ColumnLayout {
                            id: profileColumn
                            x: 34
                            y: 28
                            width: Math.max(1, profileScroll.width - 68)
                            spacing: 16

                            RowLayout {
                                Layout.fillWidth: true
                                Button { text: "← Back"; onClicked: bridge.goBack() }
                                Item { Layout.fillWidth: true }
                                Button {
                                    text: bridge.selectedProfile.isFavorite ? "★ Remove from favorites" : "☆ Add to favorites"
                                    enabled: (bridge.selectedProfile.id || 0) > 0
                                    onClicked: bridge.toggleSelectedProfileFavorite()
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 18
                                NekoRoundedImage {
                                    imageBridge: root.bridge
                                    Layout.preferredWidth: 180
                                    Layout.preferredHeight: 240
                                    url: bridge.selectedProfile.imageSource || ""
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    cache: true
                                    radius: bridge.cornerRadius
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    spacing: 8
                                    Text {
                                        text: bridge.selectedProfile.displayName || "Profile"
                                        color: bridge.primaryColor
                                        font.pixelSize: 25
                                        font.weight: Font.Black
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        text: (bridge.selectedProfile.entity_type || "profile").toString().replace("_", " ").toUpperCase()
                                        color: bridge.mutedColor
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        visible: !!bridge.selectedProfile.siteUrl
                                        text: bridge.selectedProfile.siteUrl || ""
                                        color: bridge.accentColor
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        visible: bridge.selectedProfile.profileLoading || false
                                        text: "Loading profile details…"
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                    }
                                    Text {
                                        visible: !!bridge.selectedProfile.profileError
                                        text: bridge.selectedProfile.profileError || ""
                                        color: bridge.dangerColor
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: (bridge.selectedProfile.factItems || []).length > 0
                                spacing: 8
                                Text {
                                    text: "Profile facts"
                                    color: bridge.primaryColor
                                    font.pixelSize: 17
                                    font.weight: Font.Bold
                                }
                                GridView {
                                    id: profileFactsGrid
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: Math.min(
                                        250,
                                        Math.ceil((bridge.selectedProfile.factItems || []).length
                                            / Math.max(1, Math.floor(width / Math.max(190, width / 3)))) * 58
                                    )
                                    cellWidth: Math.max(190, width / 3)
                                    cellHeight: 58
                                    interactive: false
                                    clip: true
                                    model: bridge.selectedProfile.factItems || []
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: profileFactsGrid.cellWidth - 8
                                        height: 52
                                        radius: 9
                                        color: bridge.surfaceFillColor
                                        border.width: 1
                                        border.color: bridge.frameColor
                                        Column {
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 2
                                            Text {
                                                text: modelData.label
                                                color: bridge.mutedColor
                                                font.pixelSize: 9
                                                font.weight: Font.Bold
                                                elide: Text.ElideRight
                                                width: parent.width
                                            }
                                            Text {
                                                text: modelData.value
                                                color: bridge.primaryColor
                                                font.pixelSize: 11
                                                wrapMode: Text.WordWrap
                                                maximumLineCount: 2
                                                elide: Text.ElideRight
                                                width: parent.width
                                            }
                                        }
                                    }
                                }
                            }

                            Rectangle { Layout.fillWidth: true; height: 1; color: bridge.frameColor }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 8
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

                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: bridge.selectedProfile.entity_type === "character"
                                    && (bridge.selectedProfile.voiceActorItems || []).length > 0
                                spacing: 8
                                Text {
                                    text: "Voice actors"
                                    color: bridge.primaryColor
                                    font.pixelSize: 17
                                    font.weight: Font.Bold
                                }
                                GridView {
                                    id: profileVoiceActorsGrid
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: Math.min(
                                        190,
                                        Math.max(1, Math.ceil((bridge.selectedProfile.voiceActorItems || []).length
                                            / Math.max(1, Math.floor(width / 220)))) * 92
                                    )
                                    cellWidth: Math.max(190, width / 3)
                                    cellHeight: 92
                                    clip: true
                                    interactive: false
                                    model: bridge.selectedProfile.voiceActorItems || []
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: profileVoiceActorsGrid.cellWidth - 8
                                        height: 84
                                        radius: 10
                                        color: bridge.surfaceFillColor
                                        border.width: 1
                                        border.color: bridge.frameColor
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 9
                                            NekoImage {
                                                imageBridge: root.bridge
                                                Layout.preferredWidth: 48
                                                Layout.preferredHeight: 64
                                                visible: !!modelData.imageSource
                                                url: modelData.imageSource || ""
                                                fillMode: Image.PreserveAspectCrop
                                                asynchronous: true
                                                cache: true
                                            }
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 3
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: modelData.name || "Unknown voice actor"
                                                    color: bridge.primaryColor
                                                    font.pixelSize: 11
                                                    font.weight: Font.DemiBold
                                                    wrapMode: Text.WordWrap
                                                    maximumLineCount: 2
                                                    elide: Text.ElideRight
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: modelData.languageLabel || ""
                                                    color: bridge.mutedColor
                                                    font.pixelSize: 9
                                                    elide: Text.ElideRight
                                                }
                                            }
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: bridge.requestOpenProfile(
                                                "voice_actor", modelData.personId, modelData.name
                                            )
                                        }
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: (bridge.selectedProfile.workItems || []).length > 0
                                spacing: 8
                                Text {
                                    text: "Appearances and credits"
                                    color: bridge.primaryColor
                                    font.pixelSize: 17
                                    font.weight: Font.Bold
                                }
                                GridView {
                                    id: profileWorksGrid
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: Math.min(
                                        560,
                                        Math.max(1, Math.ceil((bridge.selectedProfile.workItems || []).length
                                            / Math.max(1, Math.floor(width / cellWidth)))) * cellHeight
                                    )
                                    cellWidth: bridge.cardSize + bridge.cardGap + 8
                                    cellHeight: bridge.coverHeight + bridge.titleHeight
                                        + bridge.seriesHeight + bridge.metadataHeight + 42
                                    clip: true
                                    interactive: false
                                    model: bridge.selectedProfile.workItems || []
                                    delegate: Item {
                                        required property var modelData
                                        width: profileWorksGrid.cellWidth
                                        height: profileWorksGrid.cellHeight
                                        Column {
                                            anchors.fill: parent
                                            spacing: 2
                                            Text {
                                                width: parent.width
                                                height: 26
                                                text: [modelData.section || "", modelData.role || ""].filter(Boolean).join(" · ")
                                                color: bridge.mutedColor
                                                font.pixelSize: 9
                                                elide: Text.ElideRight
                                                verticalAlignment: Text.AlignVCenter
                                            }
                                            PosterCard {
                                                bridge: root.bridge
                                                workId: modelData.id
                                                title: modelData.title || "Untitled"
                                                fullTitle: modelData.title || "Untitled"
                                                coverSource: modelData.coverSource || ""
                                                coverCacheWorkId: modelData.id
                                                mediaType: modelData.mediaType || ""
                                                format: modelData.format || ""
                                                startYear: modelData.startYear || 0
                                                seriesCount: 1
                                                isInLibrary: false
                                                showMenu: false
                                                onActivated: function(workId) {
                                                    bridge.requestOpenRelatedWork(
                                                        workId,
                                                        modelData.title,
                                                        modelData.mediaType,
                                                        modelData.format,
                                                        modelData.coverSource
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: !(bridge.selectedProfile.workItems || []).length
                                    && !(bridge.selectedProfile.profileLoading || false)
                                text: "No related titles were returned for this profile."
                                color: bridge.mutedColor
                                font.pixelSize: 11
                            }
                        }
                    }
                }


            }
        }
    }
}
