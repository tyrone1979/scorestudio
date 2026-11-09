# MuseScore Studio plugin · ComposerChat Generate

Generate a deterministic MusicXML score from [MuseScore Studio](https://musescore.org/) 4.4+ (tested on 4.7) by calling ComposerChat’s CLI.

**Release:** [musescore-plugin-v1.0.0](https://github.com/tyrone1979/scorestudio/releases/tag/musescore-plugin-v1.0.0)  
Download asset: `ComposerChat-MuseScore-Plugin-v1.0.0.zip` (see the release **Assets** section).

## Architecture

```
MuseScore QML dialog  →  request.json  →  generate_silent.vbs / generate.cmd
                                              ↓
                                    generate_score.py (deterministic kernel)
                                              ↓
                                    MusicXML (+ MIDI)  →  open in MuseScore
```

## Install

### From this repository (recommended)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_musescore_plugin.ps1
```

Copies `musescore_plugin/ComposerChat/` into  
`%USERPROFILE%\Documents\MuseScore4\Plugins\ComposerChat\`  
and writes a machine-local `config.json` (Python path + project root).

### From the GitHub release zip

1. Unzip `ComposerChat-MuseScore-Plugin-v1.0.0.zip`
2. Prefer running `install_musescore_plugin.ps1` from a full ComposerChat checkout (the plugin needs the project venv + `generate_score.py`)
3. Or copy the `ComposerChat/` folder into the MuseScore Plugins directory and create `config.json` from `config.example.json`

Then:

1. Restart MuseScore Studio  
2. **Home → Plugins** → enable **ComposerChat Generate**  
3. **Plugins → Composing tools → ComposerChat Generate**

## CLI (same engine)

```bash
python generate_score.py --pack chorale --bars 16 --out out.musicxml
python generate_score.py --list-packs
python generate_score.py --pack waltz --bars 8 --seed demo --json
```

## Requirements

- MuseScore Studio **4.4+** (Qt 6 plugin API)
- Local ComposerChat checkout with dependencies (`pip install -r requirements.txt`)
- Windows launcher scripts (`.cmd` / `.vbs`) ship for the MuseScore `QProcess` / ShellExecute path

## License

GPL-3.0, same as ComposerChat / Score Studio.
