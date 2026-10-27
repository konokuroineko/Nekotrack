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
                    clip: true
                    property int homeCardWidth: bridge.cardSize + bridge.cardGap + 8

                    Flickable {
                        id: homeScroll
                        anchors.fill: parent
                        clip: true
                        contentWidth: width
                        contentHeight: homeColumn.implicitHeight + 64
                        boundsBehavior: Flickable.StopAtBounds

                        ColumnLayout {
                            id: homeColumn
                            x: 38
                            y: 32
                            width: Math.max(1, homeScroll.width - 76)
                            spacing: 22

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
                                Layout.preferredHeight: bridge.coverHeight + bridge.titleHeight
                                    + bridge.seriesHeight + bridge.metadataHeight + 66
                                GridView {
                                    id: continueGrid
                                    anchors.fill: parent
                                    clip: true
                                    boundsBehavior: Flickable.StopAtBounds
                                    cellWidth: homePage.homeCardWidth
                                    cellHeight: bridge.coverHeight + bridge.titleHeight + bridge.seriesHeight + bridge.metadataHeight + 66
                                    model: bridge.homeItems

                                    delegate: Item {
                                        required property var modelData
                                        width: continueGrid.cellWidth - bridge.cardGap
                                        height: continueGrid.cellHeight

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
                                                color: bridge.secondaryColor
                                                font.pixelSize: 9
                                                font.weight: Font.DemiBold
                                                elide: Text.ElideRight
                                            }

                                            Text {
                                                width: bridge.cardSize
                                                height: 36
                                                text: modelData.progressCaption || ""
                                                color: bridge.mutedColor
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
                                    width: Math.min(parent.width - 50, 420)
                                    text: "Loading your Library…"
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.WordWrap
                                    color: bridge.mutedColor
                                    font.pixelSize: 15
                                }

                                Text {
                                    anchors.centerIn: parent
                                    visible: !bridge.homeLoading && bridge.homeItems.length === 0
                                    width: Math.min(parent.width - 50, 420)
                                    text: "Nothing in progress yet.\n\nAdd titles from Search to start tracking them."
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.WordWrap
                                    color: bridge.mutedColor
                                    font.pixelSize: 15
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 9

                                RowLayout {
                                    Layout.fillWidth: true
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 3
                                        Text {
                                            text: "Upcoming releases"
                                            color: bridge.primaryColor
                                            font.pixelSize: 20
                                            font.weight: Font.Bold
                                        }
                                        Text {
                                            text: "Cached episode dates for the next 60 days."
                                            color: bridge.mutedColor
                                            font.pixelSize: 11
                                            wrapMode: Text.WordWrap
                                        }
                                    }
                                    Button {
                                        text: "Open calendar"
                                        onClicked: bridge.navigate("calendar")
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    radius: 13
                                    color: bridge.surfaceFillColor
                                    border.width: 1
                                    border.color: bridge.frameColor
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 9
                                        spacing: 7

                                        RowLayout {
                                            Layout.fillWidth: true
                                            Text {
                                                text: bridge.calendarItems.length
                                                    + " upcoming episode"
                                                    + (bridge.calendarItems.length === 1 ? "" : "s")
                                                    + " · next 60 days"
                                                color: bridge.mutedColor
                                                font.pixelSize: 10
                                                Layout.fillWidth: true
                                            }
                                        }

                                        Repeater {
                                            model: bridge.calendarItems.slice(0, 3)
                                            delegate: Rectangle {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 62
                                                radius: 9
                                                color: bridge.surfaceAltFillColor
                                                border.width: 1
                                                border.color: bridge.frameColor

                                                RowLayout {
                                                    anchors.fill: parent
                                                    anchors.margins: 7
                                                    spacing: 9
                                                    Rectangle {
                                                        Layout.preferredWidth: 46
                                                        Layout.fillHeight: true
                                                        radius: 7
                                                        color: bridge.accentSoftColor
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
                                                                font.pixelSize: 19
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
                                                            font.pixelSize: 9
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
                                            text: "No upcoming episode dates cached. NekoTrack will not guess release dates."
                                            color: bridge.mutedColor
                                            font.pixelSize: 11
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                        }

                                        Text {
                                            visible: bridge.calendarItems.length > 3
                                            text: (bridge.calendarItems.length - 3)
                                                + " more release dates in Calendar."
                                            color: bridge.mutedColor
                                            font.pixelSize: 10
                                        }
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: "For your next watch or read"
                                    color: bridge.primaryColor
                                    font.pixelSize: 20
                                    font.weight: Font.Bold
                                    Layout.fillWidth: true
                                }
                                Button {
                                    text: "Refresh"
                                    enabled: !bridge.recommendationLoading
                                    onClicked: bridge.refreshRecommendations()
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
                                Layout.preferredHeight: bridge.coverHeight + bridge.titleHeight
                                    + bridge.seriesHeight + bridge.metadataHeight + 126

                                GridView {
                                    id: recommendationGrid
                                    anchors.fill: parent
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
                                CheckBox {
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
                                        Image {
                                            anchors.fill: parent
                                            source: modelData.imageSource || ""
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

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 228
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
                                CheckBox {
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
                            Layout.fillWidth: true
                            Layout.preferredHeight: 150
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
                                        model: [80, 90, 100, 110, 125, 150, 175, 200]
                                        currentIndex: Math.max(0, model.indexOf(bridge.uiScale))
                                        onActivated: bridge.setPreference("ui_scale", model[currentIndex])
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
                                        text: "Poster size"
                                        color: bridge.primaryColor
                                        font.pixelSize: 14
                                        font.weight: Font.Bold
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        Layout.preferredWidth: 165
                                        model: ["Compact (180 px)", "Default (210 px)", "Large (240 px)", "Huge (270 px)"]
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
                                        text: "Text size"
                                        color: bridge.primaryColor
                                        font.pixelSize: 14
                                        font.weight: Font.Bold
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        Layout.preferredWidth: 165
                                        model: ["Small (12 px)", "Default (13 px)", "Large (14 px)", "Very large (15 px)"]
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
                                        model: ["Sharp (6)", "Soft (10)", "Rounded (12)", "Very rounded (16)", "Pill-like (20)"]
                                        currentIndex: Math.max(0, [6, 10, 12, 16, 20].indexOf(bridge.cornerRadius))
                                        onActivated: bridge.setPreference("corner_radius", [6, 10, 12, 16, 20][currentIndex])
                                    }
                                }
                                CheckBox {
                                    text: "Highlight cards on hover"
                                    checked: bridge.hoverHighlight
                                    onToggled: bridge.setPreference("hover_highlight", checked)
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 136
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
                                CheckBox {
                                    text: "Enable resize animations"
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
                                        model: ["Instant (0 ms)", "Fast (180 ms)", "Default (260 ms)", "Smooth (380 ms)", "Slow (520 ms)"]
                                        currentIndex: Math.max(0, [0, 180, 260, 380, 520].indexOf(bridge.animationSpeed))
                                        onActivated: bridge.setPreference("animation_speed", [0, 180, 260, 380, 520][currentIndex])
                                    }
                                }
                            }
                        }

                        Rectangle {
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
                                CheckBox {
                                    text: "Open maximized"
                                    checked: bridge.maximized
                                    onToggled: bridge.setPreference("maximized", checked)
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Button { text: "Setup wizard"; onClicked: bridge.requestSetup() }
                                    Button { text: "Restore defaults"; onClicked: bridge.resetPreferences() }
                                    Button { text: "Export diagnostics"; onClicked: bridge.requestDiagnosticsExport() }
                                }
                            }
                        }
                    }
                }

                // Work details
                Item {
                    id: workDetailsPage
                    Flickable {
                        id: detailScroll
                        anchors.fill: parent
                        clip: true
                        contentWidth: width
                        contentHeight: detailColumn.implicitHeight + 60
                        boundsBehavior: Flickable.StopAtBounds

                        ColumnLayout {
                            id: detailColumn
                            x: 34
                            y: 28
                            width: Math.max(1, detailScroll.width - 68)
                            spacing: 16

                            RowLayout {
                                Layout.fillWidth: true
                                Button { text: "← Back"; onClicked: bridge.goBack() }
                                Button {
                                    visible: (bridge.selectedWork.id || 0) !== 0
                                    text: "Manage"
                                    onClicked: detailManagementMenu.open()
                                }
                                Item { Layout.fillWidth: true }
                                Button {
                                    text: "Refresh details"
                                    enabled: !bridge.selectedWork.detailsLoading
                                    onClicked: bridge.refreshSelectedWork()
                                }
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
                                        text: (bridge.selectedWork.mediaType || "")
                                            + (bridge.selectedWork.status ? " · " + bridge.selectedWork.status : "")
                                        color: bridge.secondaryColor
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        text: {
                                            if (!(bridge.selectedWork.isInLibrary || false))
                                                return "Not in your Library yet"
                                            var parts = []
                                            if (bridge.selectedWork.mediaType === "ANIME") {
                                                parts.push("Episodes: " + (bridge.selectedWork.progressEpisodes || 0)
                                                    + (bridge.selectedWork.episodeTotal
                                                        ? " / " + bridge.selectedWork.episodeTotal
                                                        : ""))
                                            }
                                            if ((bridge.selectedWork.readingMembers || []).length > 0) {
                                                parts.push("Chapters: " + (bridge.selectedWork.progressChapters || 0)
                                                    + (bridge.selectedWork.chapterTotal
                                                        ? " / " + bridge.selectedWork.chapterTotal : ""))
                                                parts.push("Volumes: " + (bridge.selectedWork.progressVolumes || 0)
                                                    + (bridge.selectedWork.volumeTotal
                                                        ? " / " + bridge.selectedWork.volumeTotal : ""))
                                            }
                                            return parts.length > 0 ? parts.join(" · ") : "Saved in your Library"
                                        }
                                        color: bridge.secondaryColor
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        visible: bridge.selectedWork.detailsLoading || false
                                        text: "Loading saved details…"
                                        color: bridge.mutedColor
                                        font.pixelSize: 11
                                    }
                                    RowLayout {
                                        Button {
                                            visible: !(bridge.selectedWork.isInLibrary || false)
                                            text: "Add to Library"
                                            onClicked: bridge.requestAddSelectedWork()
                                        }
                                        Button {
                                            visible: bridge.selectedWork.isInLibrary
                                                && bridge.selectedWork.mediaType === "ANIME"
                                            text: "Mark all watched"
                                            onClicked: bridge.markAllEpisodesWatched(bridge.selectedWork.id, true)
                                        }
                                        Button {
                                            visible: bridge.selectedWork.isInLibrary
                                                && bridge.selectedWork.mediaType === "ANIME"
                                            text: "Clear progress"
                                            onClicked: bridge.markAllEpisodesWatched(bridge.selectedWork.id, false)
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
                                Layout.preferredHeight: Math.min(160, implicitHeight)
                                text: bridge.selectedWork.synopsis || "No synopsis available."
                                color: bridge.secondaryColor
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                                clip: true
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: (bridge.selectedWork.bundleMembers || []).length > 1
                                spacing: 8
                                Text {
                                    text: "Bundle members"
                                    color: bridge.primaryColor
                                    font.pixelSize: 17
                                    font.weight: Font.Bold
                                }
                                ListView {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 104
                                    clip: true
                                    orientation: ListView.Horizontal
                                    spacing: 10
                                    model: bridge.selectedWork.bundleMembers || []
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: 238
                                        height: 96
                                        radius: 11
                                        color: bridge.surfaceFillColor
                                        border.width: 1
                                        border.color: bridge.frameColor

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 10
                                            Image {
                                                Layout.preferredWidth: 50
                                                Layout.preferredHeight: 70
                                                source: modelData.coverSource || ""
                                                fillMode: Image.PreserveAspectCrop
                                                asynchronous: true
                                                cache: true
                                            }
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 3
                                                Text {
                                                    text: modelData.title || "Untitled"
                                                    color: bridge.primaryColor
                                                    font.pixelSize: 11
                                                    font.weight: Font.Bold
                                                    wrapMode: Text.WordWrap
                                                    maximumLineCount: 2
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                                Text {
                                                    text: [modelData.format || "", modelData.startYear || ""].filter(Boolean).join(" · ")
                                                    color: bridge.mutedColor
                                                    font.pixelSize: 10
                                                }
                                                Button {
                                                    text: "Open"
                                                    onClicked: bridge.requestOpenWork(modelData.id)
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            RowLayout {
                                id: readingProgressRow
                                Layout.fillWidth: true
                                property int trackedWorkId: bridge.selectedWork.id || 0
                                property int readingMemberId: {
                                    var members = bridge.selectedWork.readingMembers || []
                                    return members.length > 0 ? members[0].id : (bridge.selectedWork.id || 0)
                                }
                                readonly property var selectedReadingProgress: {
                                    var progress = bridge.selectedWork.readingProgressByWork || {}
                                    return progress[readingProgressRow.readingMemberId.toString()] || {}
                                }
                                visible: (bridge.selectedWork.readingMembers || []).length > 0
                                spacing: 12

                                Connections {
                                    target: bridge
                                    function onSelectedWorkChanged() {
                                        var nextId = bridge.selectedWork.id || 0
                                        if (nextId !== readingProgressRow.trackedWorkId) {
                                            readingProgressRow.trackedWorkId = nextId
                                            var members = bridge.selectedWork.readingMembers || []
                                            readingProgressRow.readingMemberId = members.length > 0
                                                ? members[0].id : nextId
                                        }
                                    }
                                }

                                Text {
                                    text: "Progress for"
                                    color: bridge.primaryColor
                                    font.pixelSize: 12
                                }
                                ComboBox {
                                    Layout.preferredWidth: 220
                                    visible: (bridge.selectedWork.readingMembers || []).length > 1
                                    model: bridge.selectedWork.readingMembers || []
                                    textRole: "title"
                                    currentIndex: {
                                        var members = bridge.selectedWork.readingMembers || []
                                        for (var i = 0; i < members.length; i++) {
                                            if (members[i].id === readingProgressRow.readingMemberId)
                                                return i
                                        }
                                        return 0
                                    }
                                    onActivated: {
                                        var members = bridge.selectedWork.readingMembers || []
                                        if (currentIndex >= 0 && currentIndex < members.length)
                                            readingProgressRow.readingMemberId = members[currentIndex].id
                                    }
                                }

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
                                    enabled: bridge.selectedWork.isInLibrary
                                    value: readingProgressRow.selectedReadingProgress.chapters || 0
                                    onValueModified: bridge.setReadingProgress(readingProgressRow.readingMemberId, "chapter", value)
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
                                    enabled: bridge.selectedWork.isInLibrary
                                    value: readingProgressRow.selectedReadingProgress.volumes || 0
                                    onValueModified: bridge.setReadingProgress(readingProgressRow.readingMemberId, "volume", value)
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: (bridge.selectedWork.characters || []).length > 0
                                    || bridge.selectedWork.detailsLoading
                                spacing: 8
                                Text {
                                    text: "Characters and voice actors"
                                    color: bridge.primaryColor
                                    font.pixelSize: 17
                                    font.weight: Font.Bold
                                }
                                Text {
                                    visible: (bridge.selectedWork.characters || []).length === 0
                                        && (bridge.selectedWork.detailsLoading || false)
                                    text: "Loading character credits…"
                                    color: bridge.mutedColor
                                    font.pixelSize: 11
                                }
                                GridView {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: (bridge.selectedWork.characters || []).length > 0 ? 220 : 0
                                    cellWidth: Math.max(165, width / 4)
                                    cellHeight: 104
                                    clip: true
                                    interactive: false
                                    model: bridge.selectedWork.characters || []
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: GridView.view.cellWidth - 8
                                        height: 96
                                        radius: 10
                                        color: bridge.surfaceFillColor
                                        border.width: 1
                                        border.color: bridge.frameColor

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 8
                                            Image {
                                                Layout.preferredWidth: 42
                                                Layout.preferredHeight: 58
                                                source: modelData.coverSource || ""
                                                fillMode: Image.PreserveAspectCrop
                                                asynchronous: true
                                                cache: true
                                            }
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 3
                                                Text {
                                                    text: modelData.name || "Unknown character"
                                                    color: bridge.primaryColor
                                                    font.pixelSize: 11
                                                    font.weight: Font.Bold
                                                    maximumLineCount: 2
                                                    wrapMode: Text.WordWrap
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                                Text {
                                                    text: modelData.role || ""
                                                    color: bridge.mutedColor
                                                    font.pixelSize: 9
                                                }
                                                Button {
                                                    visible: (modelData.voiceActorId || 0) > 0
                                                    text: modelData.voiceActorName || "Voice actor"
                                                    font.pixelSize: 9
                                                    onClicked: bridge.requestOpenProfile(
                                                        "voice_actor",
                                                        modelData.voiceActorId,
                                                        modelData.voiceActorName
                                                    )
                                                }
                                            }
                                        }

                                        MouseArea {
                                            anchors.fill: parent
                                            z: 1
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: bridge.requestOpenProfile(
                                                "character",
                                                modelData.id,
                                                modelData.name
                                            )
                                        }
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: (bridge.selectedWork.staff || []).length > 0
                                    || bridge.selectedWork.detailsLoading
                                spacing: 8
                                Text {
                                    text: "Production staff"
                                    color: bridge.primaryColor
                                    font.pixelSize: 17
                                    font.weight: Font.Bold
                                }
                                Text {
                                    visible: (bridge.selectedWork.staff || []).length === 0
                                        && (bridge.selectedWork.detailsLoading || false)
                                    text: "Loading staff credits…"
                                    color: bridge.mutedColor
                                    font.pixelSize: 11
                                }
                                GridView {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: (bridge.selectedWork.staff || []).length > 0 ? 180 : 0
                                    cellWidth: Math.max(165, width / 4)
                                    cellHeight: 94
                                    clip: true
                                    interactive: false
                                    model: bridge.selectedWork.staff || []
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: GridView.view.cellWidth - 8
                                        height: 86
                                        radius: 10
                                        color: bridge.surfaceFillColor
                                        border.width: 1
                                        border.color: bridge.frameColor
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 8
                                            Image {
                                                Layout.preferredWidth: 42
                                                Layout.preferredHeight: 58
                                                source: modelData.coverSource || ""
                                                fillMode: Image.PreserveAspectCrop
                                                asynchronous: true
                                                cache: true
                                            }
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 3
                                                Text {
                                                    text: modelData.name || "Unknown staff"
                                                    color: bridge.primaryColor
                                                    font.pixelSize: 11
                                                    font.weight: Font.Bold
                                                    maximumLineCount: 2
                                                    wrapMode: Text.WordWrap
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                                Text {
                                                    text: modelData.role || ""
                                                    color: bridge.mutedColor
                                                    font.pixelSize: 9
                                                    wrapMode: Text.WordWrap
                                                    maximumLineCount: 2
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                            }
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            z: 1
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: bridge.requestOpenProfile("staff", modelData.id, modelData.name)
                                        }
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: (bridge.selectedWork.relations || []).length > 0
                                spacing: 8
                                Text {
                                    text: "Related works"
                                    color: bridge.primaryColor
                                    font.pixelSize: 17
                                    font.weight: Font.Bold
                                }
                                GridView {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: Math.min(
                                        220,
                                        Math.ceil((bridge.selectedWork.relations || []).length / 4) * 104
                                    )
                                    cellWidth: Math.max(165, width / 4)
                                    cellHeight: 104
                                    clip: true
                                    interactive: false
                                    model: bridge.selectedWork.relations || []
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: GridView.view.cellWidth - 8
                                        height: 96
                                        radius: 10
                                        color: bridge.surfaceFillColor
                                        border.width: 1
                                        border.color: bridge.frameColor
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 8
                                            Image {
                                                Layout.preferredWidth: 42
                                                Layout.preferredHeight: 58
                                                source: modelData.coverSource || ""
                                                fillMode: Image.PreserveAspectCrop
                                                asynchronous: true
                                                cache: true
                                            }
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 3
                                                Text {
                                                    text: modelData.title || "Related work"
                                                    color: bridge.primaryColor
                                                    font.pixelSize: 11
                                                    font.weight: Font.Bold
                                                    maximumLineCount: 2
                                                    wrapMode: Text.WordWrap
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                                Text {
                                                    text: [modelData.relationTypes || "", modelData.format || ""].filter(Boolean).join(" · ")
                                                    color: bridge.mutedColor
                                                    font.pixelSize: 9
                                                    maximumLineCount: 2
                                                    wrapMode: Text.WordWrap
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                            }
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            z: 1
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: bridge.requestOpenRelatedWork(
                                                modelData.id,
                                                modelData.title,
                                                modelData.mediaType,
                                                modelData.format,
                                                modelData.coverSource
                                            )
                                        }
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                visible: bridge.selectedWork.mediaType === "ANIME"
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
                                visible: bridge.selectedWork.mediaType === "ANIME"
                                Layout.preferredHeight: visible ? Math.min(
                                    360, Math.max(70, bridge.episodeItems.length * 76)
                                ) : 0
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
                                                text: bridge.selectedWork.seriesCount > 1
                                                    ? ((modelData.workTitle || "Series") + " · " + modelData.title)
                                                    : modelData.title
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
                                            onToggled: bridge.setEpisodeWatched(
                                                modelData.workId || bridge.selectedWork.id,
                                                modelData.episodeNumber,
                                                checked
                                            )
                                        }
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
                                Image {
                                    Layout.preferredWidth: 180
                                    Layout.preferredHeight: 240
                                    source: bridge.selectedProfile.imageSource || ""
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    cache: true
                                    layer.enabled: true
                                    layer.effect: MultiEffect {
                                        maskEnabled: true
                                        autoPaddingEnabled: false
                                        maskSource: Rectangle {
                                            width: 180
                                            height: 240
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
