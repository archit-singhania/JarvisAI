using System.Net.WebSockets;
using System.Text;
using System.Text.Json;

namespace JarvisAI.Services;

public sealed class JarvisWebSocketService : IDisposable
{
    private ClientWebSocket? socket;
    private CancellationTokenSource lifetime = new();
    private readonly SemaphoreSlim sends = new(1,1);
    private bool disposed;
    public event Action<JsonElement>? MessageReceived;
    public event Action<bool>? OnConnectionChanged;
    public bool IsConnected => socket?.State == WebSocketState.Open;

    public async Task ConnectAsync(Uri endpoint, string token)
    {
        lifetime.Cancel();socket?.Dispose();lifetime.Dispose();lifetime=new();
        var connection=new ClientWebSocket();connection.Options.SetRequestHeader("Authorization","Bearer "+token);
        socket=connection;
        try
        {
            await connection.ConnectAsync(endpoint,lifetime.Token);
            OnConnectionChanged?.Invoke(true);
            _=ReceiveAsync(connection,lifetime.Token);
        }
        catch {OnConnectionChanged?.Invoke(false);throw;}
    }

    public async Task SendAsync(object payload)
    {
        if(!IsConnected)throw new InvalidOperationException("Connect the workspace before sending.");
        await sends.WaitAsync();
        try {await socket!.SendAsync(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload)),WebSocketMessageType.Text,true,lifetime.Token);}
        finally {sends.Release();}
    }

    private async Task ReceiveAsync(ClientWebSocket connection,CancellationToken cancellation)
    {
        var buffer=new byte[16384];
        try
        {
            while(connection.State==WebSocketState.Open)
            {
                using var data=new MemoryStream();WebSocketReceiveResult result;
                do
                {
                    result=await connection.ReceiveAsync(buffer,cancellation);
                    if(result.MessageType==WebSocketMessageType.Close)return;
                    data.Write(buffer,0,result.Count);
                    if(data.Length>16*1024*1024)throw new InvalidDataException("Event exceeds size limit.");
                }while(!result.EndOfMessage);
                using var json=JsonDocument.Parse(data.ToArray());MessageReceived?.Invoke(json.RootElement.Clone());
            }
        }
        catch(OperationCanceledException){}
        catch(WebSocketException){}
        finally{if(ReferenceEquals(socket,connection))OnConnectionChanged?.Invoke(false);}
    }

    public void Dispose(){if(disposed)return;disposed=true;lifetime.Cancel();socket?.Dispose();lifetime.Dispose();}
}
