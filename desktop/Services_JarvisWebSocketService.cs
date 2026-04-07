using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace JarvisAI.Services;

/// <summary>
/// Connects to the FastAPI /ws WebSocket endpoint.
/// Sends text/audio messages, fires events on responses.
/// </summary>
public class JarvisWebSocketService : IDisposable
{
    private const string WsUrl = "ws://localhost:8000/ws";

    private ClientWebSocket? _ws;
    private CancellationTokenSource _cts = new();

    public event Action<string, string?>? OnTextResponse;   // (text, toolUsed)
    public event Action<string, byte[]?>? OnAudioResponse;  // (transcript, audioBytes)
    public event Action<bool>?            OnConnectionChanged;

    public bool IsConnected => _ws?.State == WebSocketState.Open;

    // ------------------------------------------------------------------ //
    //  Connect                                                             //
    // ------------------------------------------------------------------ //

    public async Task ConnectAsync()
    {
        try
        {
            _ws?.Dispose();
            _ws = new ClientWebSocket();
            _cts = new CancellationTokenSource();

            await _ws.ConnectAsync(new Uri(WsUrl), _cts.Token);
            OnConnectionChanged?.Invoke(true);
            _ = ReceiveLoopAsync();   // fire-and-forget receive loop
        }
        catch (Exception ex)
        {
            OnConnectionChanged?.Invoke(false);
            Console.WriteLine($"[WS] Connect failed: {ex.Message}");
        }
    }

    // ------------------------------------------------------------------ //
    //  Send                                                                //
    // ------------------------------------------------------------------ //

    public async Task SendTextAsync(string text)
    {
        if (!IsConnected) return;
        var payload = JsonSerializer.Serialize(new { type = "text", content = text });
        await SendRawAsync(payload);
    }

    public async Task SendAudioAsync(byte[] wavBytes)
    {
        if (!IsConnected) return;
        var b64 = Convert.ToBase64String(wavBytes);
        var payload = JsonSerializer.Serialize(new { type = "audio", audio_b64 = b64 });
        await SendRawAsync(payload);
    }

    public async Task SendScreenAnalyzeAsync(string? prompt = null)
    {
        if (!IsConnected) return;
        var payload = JsonSerializer.Serialize(new { type = "screen", prompt });
        await SendRawAsync(payload);
    }

    public async Task SendClearAsync()
    {
        if (!IsConnected) return;
        await SendRawAsync(JsonSerializer.Serialize(new { type = "clear" }));
    }

    private async Task SendRawAsync(string json)
    {
        var bytes = Encoding.UTF8.GetBytes(json);
        await _ws!.SendAsync(bytes, WebSocketMessageType.Text, true, _cts.Token);
    }

    // ------------------------------------------------------------------ //
    //  Receive loop                                                        //
    // ------------------------------------------------------------------ //

    private async Task ReceiveLoopAsync()
    {
        var buf = new byte[1024 * 64];
        var sb  = new StringBuilder();

        try
        {
            while (_ws!.State == WebSocketState.Open)
            {
                WebSocketReceiveResult result;
                sb.Clear();

                do
                {
                    result = await _ws.ReceiveAsync(buf, _cts.Token);
                    if (result.MessageType == WebSocketMessageType.Close) goto done;
                    sb.Append(Encoding.UTF8.GetString(buf, 0, result.Count));
                }
                while (!result.EndOfMessage);

                HandleMessage(sb.ToString());
            }
        }
        catch { /* disconnected */ }

        done:
        OnConnectionChanged?.Invoke(false);
    }

    private void HandleMessage(string raw)
    {
        try
        {
            var node = JsonNode.Parse(raw);
            var type = node?["type"]?.GetValue<string>();

            switch (type)
            {
                case "text":
                case "screen":
                    OnTextResponse?.Invoke(
                        node?["content"]?.GetValue<string>() ?? "",
                        node?["tool_used"]?.GetValue<string>());
                    break;

                case "audio":
                    var text     = node?["content"]?.GetValue<string>() ?? "";
                    var b64Audio = node?["audio_b64"]?.GetValue<string>();
                    var audioBytes = b64Audio is not null ? Convert.FromBase64String(b64Audio) : null;
                    OnAudioResponse?.Invoke(text, audioBytes);
                    break;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[WS] Parse error: {ex.Message}");
        }
    }

    public void Dispose()
    {
        _cts.Cancel();
        _ws?.Dispose();
    }
}
