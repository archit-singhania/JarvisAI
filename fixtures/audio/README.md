# Audio acceptance fixtures

The WAV and MP3 files contain the same generated 660 Hz, 0.4-second mono tone at 24 kHz. They are deliberately synthetic format fixtures, with no model, voice, recording, or intelligibility claim.

The native client uses its production decoder to read both files, producing `native-audio-acceptance.json`. The executed result decodes 19,200 PCM bytes from WAV and 21,888 bytes from MP3; the MP3 includes encoder padding. No audio output device is required for this decoding check.

```powershell
$env:WEDNESDAY_SMOKE_LOG = "$PWD\test-results\audio-errors.log"
desktop\bin\Release\net10.0-windows\JarvisAI.exe --audio-check="$PWD\fixtures\audio"
```

Physical playback and microphone/transcription are separate manual checks. Runtime ordering tests construct valid WAV fixtures and inspect decoded samples and sequence numbers.
