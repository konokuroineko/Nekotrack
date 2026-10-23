import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

ItemDelegate {
    id: control

    required property string titleText
    required property string mediaFormat
    required property string descriptionText
    required property string progressText
    property string accentGlyph: "N"

    Accessible.name: qsTr("%1, %2. %3").arg(titleText).arg(mediaFormat).arg(progressText)
    Accessible.description: descriptionText
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    padding: 14
    implicitHeight: 126

    contentItem: RowLayout {
        spacing: 14

        Rectangle {
            Layout.preferredWidth: 68
            Layout.preferredHeight: 92
            Layout.alignment: Qt.AlignVCenter
            radius: 10
            color: "#29243E"
            border.color: "#514477"
            border.width: 1

            Text {
                anchors.centerIn: parent
                text: control.accentGlyph
                color: "#D9CCFF"
                font.pixelSize: 25
                font.bold: true
                accessibleName: qsTr("Artwork placeholder")
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 5

            Text {
                Layout.fillWidth: true
                text: control.titleText
                color: "#F4F1FF"
                font.pixelSize: 16
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                maximumLineCount: 1
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Rectangle {
                    Layout.preferredWidth: formatLabel.implicitWidth + 16
                    Layout.preferredHeight: 23
                    radius: 6
                    color: "#302941"

                    Text {
                        id: formatLabel
                        anchors.centerIn: parent
                        text: control.mediaFormat
                        color: "#D8C8FF"
                        font.pixelSize: 11
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: control.progressText
                    color: "#C5BED8"
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
            }

            Text {
                Layout.fillWidth: true
                text: control.descriptionText
                color: "#B8B2C8"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }

        Text {
            text: "›"
            color: control.visualFocus ? "#F4F1FF" : "#A79AC8"
            font.pixelSize: 26
            Layout.alignment: Qt.AlignVCenter
        }
    }

    background: Rectangle {
        radius: 14
        color: control.down ? "#29243A" : (control.hovered ? "#202131" : "#191B27")
        border.color: control.visualFocus ? "#E0D5FF" : (control.hovered ? "#6B5B91" : "#303142")
        border.width: control.visualFocus ? 2 : 1
    }
}
