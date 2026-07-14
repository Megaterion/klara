# Voice Samples

Place your XTTS voice cloning sample here as `killjoy.wav`.

The file should be:
- A clean WAV recording (no background noise)
- Duration: 6-30 seconds
- Sample rate: 22050 Hz or 44100 Hz (XTTS will handle resampling)
- Mono or stereo

The Killjoy voice sample `killjoyGermanLines6min.mp3` in the repo root
should be converted to WAV and placed here:

```bash
# Convert MP3 to WAV (requires ffmpeg)
ffmpeg -i ../../killjoyGermanLines6min.mp3 -ar 22050 -ac 1 killjoy.wav
```

The container maps this directory as `/samples/` — the config references
`/app/shared-data/voice_samples/killjoy.wav` which maps to this file.
