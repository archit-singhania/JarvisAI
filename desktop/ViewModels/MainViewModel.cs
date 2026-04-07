using System.Collections.ObjectModel;
using System.Windows;
using System.Windows.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JarvisAI.Models;
using JarvisAI.Services;

namespace JarvisAI.ViewModels;

public partial class MainViewModel : ObservableObject
{
    // ── Services ──────────────────────────────────────────────────
    private readonly JarvisWebSocketService _ws;
    private readonly AudioService _audio;

    // ── Observable state ──────────────────────────────────────────
    [ObservableProperty] private string _inputText = string.Empty;
    [ObservableProperty] private string _statusText = "Connecting...";
    [ObservableProperty] private Color _statusColor = Colors.Orange;
    [ObservableProperty] private bool _isListening;
    [ObservableProperty] private Color _micButtonColor = Color.FromRgb(28, 35, 51);
    [ObservableProperty] private string _currentModel = "llama-3.1-70b · Groq";
    [ObservableProperty] private GridLength _waveformHeight = new(0);

    public ObservableCollection<ChatMessage> Messages { get; } = [];

    // Fired from VM so MainWindow can call ScrollToBottom()
    public Action? ScrollToBottom;

    public MainViewModel()
    {
        _ws = new JarvisWebSocketService("ws://localhost:8000/ws");
        _audio = new AudioService();

        _ws.MessageReceived += OnJarvisResponse;
        _ws.Connected += () => App.Current.Dispatcher.Invoke(() =>
        {
            StatusText = "Online";
            StatusColor = Color.FromRgb(16, 185, 129);
        });
        _ws.Disconnected += () => App.Current.Dispatcher.Invoke(() =>
        {
            StatusText = "Disconnected";
            StatusColor = Colors.OrangeRed;
        });

        _ = _ws.ConnectAsync();

        AddMessage("Jarvis", "Good day. Systems are online. How can I assist you?", false);
    }

    // ── Commands ──────────────────────────────────────────────────

    [RelayCommand]
    private async Task SendText()
    {
        var text = InputText.Trim();
        if (string.IsNullOrEmpty(text)) return;

        InputText = string.Empty;
        AddMessage("You", text, true);
        await _ws.SendAsync(new { type = "text", content = text });
    }

    [RelayCommand]
    private async Task ToggleListening()
    {
        if (!IsListening)
        {
            IsListening = true;
            MicButtonColor = Color.FromRgb(0, 212, 255);
            WaveformHeight = new GridLength(64);
            StatusText = "Listening...";
            StatusColor = Color.FromRgb(0, 212, 255);
            await _audio.StartRecordingAsync(OnAudioCaptured);
        }
        else
        {
            IsListening = false;
            MicButtonColor = Color.FromRgb(28, 35, 51);
            WaveformHeight = new GridLength(0);
            StatusText = "Online";
            StatusColor = Color.FromRgb(16, 185, 129);
            await _audio.StopRecordingAsync();
        }
    }

    [RelayCommand]
    private async Task ToggleVoiceMode() => await ToggleListening();

    [RelayCommand]
    private async Task Rap()
    {
        AddMessage("You", "Rap for me, Jarvis!", true);
        await _ws.SendAsync(new
        {
            type = "text",
            content = "Rap for me — make it about AI and the future. Keep it punchy, 8 bars max."
        });
    }

    [RelayCommand]
    private Task Time()
    {
        var now = DateTime.Now.ToString("h:mm tt, dddd, MMMM d");
        AddMessage("Jarvis", $"It is currently {now}.", false);
        return Task.CompletedTask;
    }

    [RelayCommand]
    private async Task Weather()
    {
        AddMessage("You", "What's the weather?", true);
        await _ws.SendAsync(new { type = "text", content = "What is the current weather? Use your weather tool." });
    }

    [RelayCommand]
    private async Task ScreenAware()
    {
        AddMessage("You", "Jarvis, look at my screen.", true);
        var imageBytes = ScreenCaptureService.Capture();
        var base64 = Convert.ToBase64String(imageBytes);
        await _ws.SendAsync(new
        {
            type = "image",
            content = base64,
            prompt = "Describe what you see on this screen and offer help."
        });
    }

    [RelayCommand]
    private Task ClearChat()
    {
        Messages.Clear();
        AddMessage("Jarvis", "Memory cleared. Fresh start.", false);
        return Task.CompletedTask;
    }

    // ── Handlers ──────────────────────────────────────────────────

    private void OnJarvisResponse(string responseJson)
    {
        App.Current.Dispatcher.Invoke(() =>
        {
            try
            {
                var obj = Newtonsoft.Json.JsonConvert.DeserializeObject<dynamic>(responseJson)!;
                string content = ((string?)obj?.content ?? (string?)obj?.response) ?? "...";
                AddMessage("Jarvis", content, false);
            }
            catch
            {
                AddMessage("Jarvis", responseJson, false);
            }
        });
    }

    private async void OnAudioCaptured(byte[] audioData)
    {
        var base64Audio = Convert.ToBase64String(audioData);
        await _ws.SendAsync(new { type = "audio", content = base64Audio });
        await ToggleListening();
    }

    private void AddMessage(string sender, string content, bool isUser)
    {
        Messages.Add(new ChatMessage
        {
            Sender = sender,
            Content = content,
            IsUser = isUser,
            Timestamp = DateTime.Now.ToString("HH:mm"),
            Alignment = isUser ? HorizontalAlignment.Right : HorizontalAlignment.Left,
            BubbleColor = isUser
                ? Color.FromArgb(40, 59, 130, 246)
                : Color.FromArgb(40, 28, 35, 51)
        });

        ScrollToBottom?.Invoke();
    }
}
