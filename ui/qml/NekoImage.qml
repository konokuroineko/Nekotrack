import QtQuick

Image {
    id: root
    property var imageBridge: null
    property string url: ""
    property string cachedUrl: ""

    source: cachedUrl.length > 0 ? cachedUrl : url
    onUrlChanged: cachedUrl = ""

    onStatusChanged: {
        if (status !== Image.Error || !imageBridge)
            return
        var remote = String(url || "")
        if ((remote.indexOf("https://") === 0 || remote.indexOf("http://") === 0)
                && imageBridge.requestImageCache) {
            imageBridge.requestImageCache(remote)
        }
    }

    Connections {
        target: root.imageBridge
        ignoreUnknownSignals: true
        function onImageCached(remoteUrl, localUrl) {
            if (remoteUrl === root.url && localUrl && localUrl.length > 0)
                root.cachedUrl = localUrl
        }
    }
}
