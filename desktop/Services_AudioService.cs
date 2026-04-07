using NAudio.Wave;

namespace JarvisAI.Services;

/// <summary>
/// Records mic audio to a WAV byte array using NAudio.
/// Call StartRecording() / StopRecording() → get wav bytes back.
/// Also provides RMS level for the waveform visualiser.
/// </summary>
public class AudioService : IDisposable
{
    private WaveInEvent?   _waveIn;
    private MemoryStream?  _buffer;
    private WaveFileWriter? _writer;

    public event Action<float>? OnRmsLevel;   // 0.0 – 1.0, fires ~20x per second
    public bool IsRecording { get; private set; }

    public void StartRecording()
    {
        if (IsRecording) return;

        _buffer = new MemoryStream();
        _waveIn  = new WaveInEvent
        {
            WaveFormat = new WaveFormat(16000, 1),   // 16kHz mono — Whisper's preferred format
            BufferMilliseconds = 50,
        };
        _writer = new WaveFileWriter(_buffer, _waveIn.WaveFormat);

        _waveIn.DataAvailable += (_, e) =>
        {
            _writer.Write(e.Buffer, 0, e.BytesRecorded);

            // Compute RMS for waveform bars
            float rms = 0;
            for (int i = 0; i < e.BytesRecorded; i += 2)
            {
                short sample = BitConverter.ToInt16(e.Buffer, i);
                rms += sample * sample;
            }
            rms = MathF.Sqrt(rms / (e.BytesRecorded / 2)) / short.MaxValue;
            OnRmsLevel?.Invoke(Math.Min(rms * 8f, 1f));   // amplify for visual clarity
        };

        _waveIn.StartRecording();
        IsRecording = true;
    }

    public byte[] StopRecording()
    {
        if (!IsRecording) return Array.Empty<byte>();

        _waveIn?.StopRecording();
        _waveIn?.Dispose();
        _writer?.Flush();

        var bytes = _buffer?.ToArray() ?? Array.Empty<byte>();

        _writer?.Dispose();
        _buffer?.Dispose();
        _waveIn  = null;
        _writer  = null;
        _buffer  = null;
        IsRecording = false;

        return bytes;
    }

    public void PlayAudio(byte[] wavBytes)
    {
        if (wavBytes.Length == 0) return;
        Task.Run(() =>
        {
            using var ms     = new MemoryStream(wavBytes);
            using var reader = new WaveFileReader(ms);
            using var output = new WaveOutEvent();
            output.Init(reader);
            output.Play();
            while (output.PlaybackState == PlaybackState.Playing)
                Thread.Sleep(100);
        });
    }

    public void Dispose()
    {
        _waveIn?.Dispose();
        _writer?.Dispose();
        _buffer?.Dispose();
    }
}
