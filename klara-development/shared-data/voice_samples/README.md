# Voice Samples

Dateiablage:

- `killjoy.wav` liegt in diesem Verzeichnis
- das Verzeichnis wird im XTTS-Container auf `/samples` gemountet
- `config/base.json` referenziert die Datei als `/samples/killjoy.wav`

Konvertierung der mitgelieferten MP3-Datei:

```bash
ffmpeg -i ../../killjoyGermanLines6min.mp3 -ar 22050 -ac 1 killjoy.wav
```

Anforderungen an die Datei:

- WAV
- Mono
- `killjoy.wav` als Dateiname
