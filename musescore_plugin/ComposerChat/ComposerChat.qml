/**
 * ComposerChat — MuseScore Studio plugin
 * Calls the ComposerChat CLI (generate_score.py) to produce MusicXML,
 * then opens the result in MuseScore.
 *
 * Requires: MuseScore Studio 4.4+ (Qt 6), ComposerChat installed locally.
 */
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import MuseScore 3.0
import FileIO 3.0
import Muse.UiComponents

MuseScore {
    version: "1.0.0"
    description: "Generate a deterministic score via ComposerChat CLI and open it"
    title: "ComposerChat Generate"
    pluginType: "dialog"
    categoryCode: "composing-arranging-tools"
    thumbnailName: "composerchat.png"
    requiresScore: false

    width: 460
    height: 420

    property var packIds: [
        "fugue", "piano-prelude", "classical-sonata", "piano-sonata",
        "string-quartet", "symphony", "mazurka", "waltz",
        "british-folk-tune", "celtic-jig", "swing-standard", "pop-standard",
        "chopin-piano", "chorale", "madrigal"
    ]
    property string pluginDir: ""
    property string statusText: "Ready."
    property bool busy: false

    FileIO {
        id: configFile
        onError: function (msg) { statusText = "Config FileIO: " + msg }
    }
    FileIO {
        id: requestFile
        onError: function (msg) { statusText = "Request FileIO: " + msg }
    }
    FileIO {
        id: resultFile
        onError: function (msg) { statusText = "Result FileIO: " + msg }
    }

    QProcess {
        id: proc
    }

    Timer {
        id: pollTimer
        interval: 400
        repeat: true
        property int ticks: 0
        onTriggered: {
            ticks += 1
            resultFile.source = pluginDir + "result.json"
            if (resultFile.exists()) {
                var raw = resultFile.read()
                if (raw && raw.length > 2) {
                    stop()
                    busy = false
                    handleResult(raw)
                }
            } else if (ticks > 450) { // ~3 min
                stop()
                busy = false
                statusText = "Timed out waiting for result.json"
            } else {
                statusText = "Generating… (" + ticks + ")"
            }
        }
    }

    onRun: {
        pluginDir = localPath()
        configFile.source = pluginDir + "config.json"
        if (!configFile.exists()) {
            statusText = "Missing config.json — run install_musescore_plugin.ps1"
        } else {
            statusText = "Ready. Project: " + pluginDir
        }
    }

    function localPath() {
        // file:///C:/Users/.../ComposerChat/ → C:/Users/.../ComposerChat/
        var u = Qt.resolvedUrl(".").toString()
        u = u.replace(/^file:\/\//, "")
        // Windows: /C:/... → C:/...
        if (u.length > 2 && u.charAt(0) === "/" && u.charAt(2) === ":")
            u = u.substring(1)
        if (u.charAt(u.length - 1) !== "/" && u.charAt(u.length - 1) !== "\\")
            u = u + "/"
        return u
    }

    function winPath(p) {
        return p.replace(/\//g, "\\")
    }

    function readConfig() {
        configFile.source = pluginDir + "config.json"
        if (!configFile.exists())
            return null
        try {
            return JSON.parse(configFile.read())
        } catch (e) {
            statusText = "Invalid config.json: " + e
            return null
        }
    }

    function handleResult(raw) {
        var res
        try {
            res = JSON.parse(raw)
        } catch (e) {
            statusText = "Bad result.json: " + e
            return
        }
        if (!res.ok) {
            statusText = "Error: " + (res.error || "unknown")
            return
        }
        statusText = "OK — " + (res.title || "") + "\n" + res.musicxml
        openMusicXml(res.musicxml)
    }

    function openMusicXml(path) {
        if (!path) {
            statusText += "\n(No musicxml path)"
            return
        }
        // Prefer plugin API; fall back to telling the user the path.
        try {
            var sc = readScore(path, true)
            if (sc) {
                statusText += "\nOpened in MuseScore."
                return
            }
        } catch (e) {
            // continue to fallback
        }
        try {
            Qt.openUrlExternally("file:///" + path.replace(/\\/g, "/"))
            statusText += "\nOpened via system handler."
        } catch (e2) {
            statusText += "\nPlease File → Open:\n" + path
        }
    }

    function startGenerate() {
        if (busy)
            return
        var cfg = readConfig()
        if (!cfg) {
            statusText = "Missing config.json — reinstall plugin"
            return
        }

        var pack = packIds[packBox.currentIndex] || "chorale"
        var fugueMode = ["auto", "full", "off"][fugueBox.currentIndex] || "auto"
        var req = {
            pack: pack,
            bars: parseInt(barsField.text) || 16,
            voices: voicesField.text === "" ? null : (parseInt(voicesField.text) || null),
            seed: seedField.text === "" ? null : seedField.text,
            title: titleField.text === "" ? null : titleField.text,
            tempo: tempoField.text === "" ? null : (parseInt(tempoField.text) || null),
            meter: meterField.text === "" ? null : meterField.text,
            key: keyField.text === "" ? null : keyField.text,
            fugue: fugueMode,
            midi: true,
            out_dir: cfg.out_dir || null,
            result_path: pluginDir + "result.json"
        }

        // Clear previous result
        resultFile.source = pluginDir + "result.json"
        if (resultFile.exists())
            resultFile.remove()

        requestFile.source = pluginDir + "request.json"
        var ok = requestFile.write(JSON.stringify(req))
        if (!ok) {
            statusText = "Failed to write request.json"
            return
        }

        busy = true
        statusText = "Starting generator…"

        // MuseScore QProcess.start() only accepts a single program string (no
        // argv). Use ShellExecute on the no-arg VBS launcher instead.
        var vbsUrl = "file:///" + (pluginDir + "generate_silent.vbs").replace(/\\/g, "/")
        var launched = false
        try {
            Qt.openUrlExternally(vbsUrl)
            launched = true
        } catch (e) {
            statusText = "openUrlExternally failed: " + e
        }
        // Fallback: try QProcess on the .cmd directly (works on some builds)
        if (!launched) {
            try {
                proc.start(winPath(pluginDir + "generate.cmd"))
                launched = true
            } catch (e2) {
                statusText = "Launch failed: " + e2
                busy = false
                return
            }
        }

        pollTimer.ticks = 0
        pollTimer.start()
    }

    Rectangle {
        anchors.fill: parent
        color: "#f7f7f7"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 8

            StyledTextLabel {
                text: "ComposerChat — Generate Score"
                font.bold: true
            }

            GridLayout {
                columns: 2
                columnSpacing: 10
                rowSpacing: 6
                Layout.fillWidth: true

                StyledTextLabel { text: "Style pack" }
                ComboBox {
                    id: packBox
                    Layout.fillWidth: true
                    model: packIds
                    currentIndex: 13 // chorale
                }

                StyledTextLabel { text: "Bars" }
                TextField {
                    id: barsField
                    text: "16"
                    Layout.fillWidth: true
                }

                StyledTextLabel { text: "Voices (opt)" }
                TextField {
                    id: voicesField
                    placeholderText: "auto"
                    Layout.fillWidth: true
                }

                StyledTextLabel { text: "Tempo (opt)" }
                TextField {
                    id: tempoField
                    placeholderText: "auto"
                    Layout.fillWidth: true
                }

                StyledTextLabel { text: "Meter (opt)" }
                TextField {
                    id: meterField
                    placeholderText: "4/4"
                    Layout.fillWidth: true
                }

                StyledTextLabel { text: "Key (opt)" }
                TextField {
                    id: keyField
                    placeholderText: "C / a / G"
                    Layout.fillWidth: true
                }

                StyledTextLabel { text: "Title (opt)" }
                TextField {
                    id: titleField
                    Layout.fillWidth: true
                }

                StyledTextLabel { text: "Seed (opt)" }
                TextField {
                    id: seedField
                    placeholderText: "reproducible id"
                    Layout.fillWidth: true
                }

                StyledTextLabel { text: "Fugue" }
                ComboBox {
                    id: fugueBox
                    Layout.fillWidth: true
                    model: ["auto", "full", "off"]
                    currentIndex: 0
                }
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                TextArea {
                    id: statusArea
                    readOnly: true
                    wrapMode: TextEdit.Wrap
                    text: statusText
                    background: Rectangle { color: "#ffffff"; border.color: "#cccccc" }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                FlatButton {
                    text: busy ? "Working…" : "Generate & Open"
                    enabled: !busy
                    accentButton: true
                    onClicked: startGenerate()
                }
                FlatButton {
                    text: "Close"
                    onClicked: quit()
                }
                Item { Layout.fillWidth: true }
            }
        }
    }
}
