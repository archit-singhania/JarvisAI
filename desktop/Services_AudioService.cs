using NAudio.Wave;
using System.Threading.Channels;

namespace JarvisAI.Services;

public sealed class AudioService : IDisposable
{
    private WaveInEvent? input;
    private MemoryStream? buffer;
    private WaveFileWriter? writer;
    private TaskCompletionSource<byte[]>? finished;
    private CancellationTokenSource playback = new();
    private Channel<(byte[] Bytes,string Format)> queue=Channel.CreateUnbounded<(byte[],string)>();
    public event Action<float>? OnRmsLevel;
    public event Action<string>? OnError;
    public bool IsRecording => input is not null;
    public AudioService(){_=PlayLoop(queue,playback.Token);}

    public void StartRecording()
    {
        if(IsRecording)return;
        buffer=new();writer=new(buffer,new WaveFormat(16000,1));finished=new(TaskCreationOptions.RunContinuationsAsynchronously);
        input=new(){WaveFormat=new WaveFormat(16000,1),BufferMilliseconds=50};
        input.DataAvailable+=(_,e)=>
        {
            writer?.Write(e.Buffer,0,e.BytesRecorded);double energy=0;
            for(int i=0;i+1<e.BytesRecorded;i+=2){double sample=BitConverter.ToInt16(e.Buffer,i)/32768d;energy+=sample*sample;}
            OnRmsLevel?.Invoke((float)Math.Sqrt(energy/Math.Max(1,e.BytesRecorded/2)));
        };
        input.RecordingStopped+=(_,e)=>
        {
            writer?.Dispose();var bytes=buffer?.ToArray()??[];
            input?.Dispose();input=null;writer=null;buffer?.Dispose();buffer=null;
            if(e.Exception is not null)finished?.TrySetException(e.Exception);else finished?.TrySetResult(bytes);
        };
        input.StartRecording();
    }

    public async Task<byte[]> StopRecordingAsync()
    {
        if(input is null||finished is null)return [];
        var completion=finished.Task;input.StopRecording();return await completion.WaitAsync(TimeSpan.FromSeconds(5));
    }

    public void EnqueueAudio(byte[] bytes,string format)=>queue.Writer.TryWrite((bytes,format));
    public void StopPlayback()
    {
        playback.Cancel();playback.Dispose();playback=new();queue.Writer.TryComplete();queue=Channel.CreateUnbounded<(byte[],string)>();_=PlayLoop(queue,playback.Token);
    }

    private async Task PlayLoop(Channel<(byte[] Bytes,string Format)> channel,CancellationToken cancellation)
    {
        try
        {
            await foreach(var item in channel.Reader.ReadAllAsync(cancellation))
            {
                try
                {
                    using var stream=new MemoryStream(item.Bytes);
                    using WaveStream reader=item.Format=="wav"?new WaveFileReader(stream):new Mp3FileReader(stream);
                    using var output=new WaveOutEvent();output.Init(reader);output.Play();
                    try{while(output.PlaybackState==PlaybackState.Playing)await Task.Delay(20,cancellation);}
                    finally{output.Stop();}
                }
                catch(Exception error) when(error is not OperationCanceledException){OnError?.Invoke(error.Message);}
            }
        }
        catch(OperationCanceledException){}
    }

    public void Dispose(){playback.Cancel();input?.Dispose();writer?.Dispose();buffer?.Dispose();}
}
