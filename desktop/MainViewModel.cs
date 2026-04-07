using System.Collections.ObjectModel;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JarvisAI.Models;
using JarvisAI.Services;

namespace JarvisAI;

public partial class MainViewModel : ObservableObject
{
    private readonly JarvisWebSocketService _ws;
    private readonly AudioService           _audio;
    private readonly DispatcherTimer        _waveTimer;

    // ── Observable state ──────────────────────────────────────── //
    [ObservableProperty] private string inputText         = "";
    [ObservableProperty] private string connectionStatus  = "Connecting...";
    [ObservableProperty] private bool   isListening       = false;
    [ObservableProperty] private Color  micButtonColor    = Color.FromRgb(0x1C, 0x23, 0x33);
    [ObservableProperty] private string currentMode       = "text";   // "text" | "voice"

    public ObservableCollection<ChatMessage> Messages  { get; } = new();
    public ObservableCollection<string>      ToolLog   { get; } = new();
    public ObservableCollection<double>      WaveformBars { get; } = new();

    // ------------------------------------------------------------------ //
    //  Init                                                                //
    // ------------------------------------------------------------------ //

    public MainViewModel()
    {
        _ws    = new JarvisWebSocketService();
        _audio = new AudioService();

        // Seed waveform with 32 bars
        for (int i = 0; i < 32; i++) WaveformBars.Add(4);

        // Wire WS events
        _ws.OnConnectionChanged += connected =>
            App.Current.Dispatcher.Invoke(() =>
                ConnectionStatus = connected ? "● Connected to backend" : "✕ Disconnected");

        _ws.OnTextResponse += (text, tool) =>
            App.Current.Dispatcher.Invoke(() =>
            {
                AddMessage("JARVIS", text, isUser: false);
                if (tool is not null) LogTool(tool, text);
            });

        _ws.OnAudioResponse += (text, audioBytes) =>
            App.Current.Dispatcher.Invoke(() =>
            {
                AddMessage("JARVIS", text, isUser: false);
                if (audioBytes is not null) _audio.PlayAudio(audioBytes);
            });

        // Waveform animation timer
        _waveTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(50) };
        _waveTimer.Tick += AnimateWaveform;

        // Mic RMS → waveform bars
        _audio.OnRmsLevel += rms =>
            App.Current.Dispatcher.InvokeAsync(() => PushRmsToWaveform(rms));

        _ = ConnectAsync();
    }

    private async Task ConnectAsync()
    {
        await _ws.ConnectAsync();
        AddMessage("JARVIS", "Hello! I'm Jarvis. How can I help you today?", isUser: false);
    }

    // ------------------------------------------------------------------ //
    //  Commands                                                            //
    // ------------------------------------------------------------------ //

    [RelayCommand]
    private async Task SendText()
    {
        var text = InputText.Trim();
        if (string.IsNullOrEmpty(text)) return;

        AddMessage("YOU", text, isUser: true);
        InputText = "";
        await _ws.SendTextAsync(text);
    }

    [RelayCommand]
    private async Task ToggleMic()
    {
        if (!_audio.IsRecording)
        {
            // Start recording
            _audio.StartRecording();
            IsListening    = true;
            MicButtonColor = Color.FromArgb(0xFF, 0x00, 0xD4, 0xFF);
            _waveTimer.Start();
        }
        else
        {
            // Stop and send
            _waveTimer.Stop();
            IsListening    = false;
            MicButtonColor = Color.FromRgb(0x1C, 0x23, 0x33);

            var wavBytes = _audio.StopRecording();
            if (wavBytes.Length > 0)
            {
                AddMessage("YOU", "🎤 [Voice message sent]", isUser: true);
                await _ws.SendAudioAsync(wavBytes);
            }

            ResetWaveform();
        }
    }

    [RelayCommand]
    private void SetMode(string mode) => CurrentMode = mode;

    [RelayCommand]
    private async Task ScreenAnalyze() =>
        await _ws.SendScreenAnalyzeAsync("Describe what's on my screen in detail.");

    [RelayCommand]
    private void AddMemory()
    {
        // TODO Phase 3: open a small dialog, let user type a fact to remember
        AddMessage("JARVIS", "Memory feature coming in Phase 3! You'll be able to teach me personal facts.", isUser: false);
    }

    [RelayCommand]
    private async Task ClearChat()
    {
        Messages.Clear();
        ToolLog.Clear();
        await _ws.SendClearAsync();
        AddMessage("JARVIS", "Chat cleared. Fresh start!", isUser: false);
    }

    // ------------------------------------------------------------------ //
    //  Helpers                                                             //
    // ------------------------------------------------------------------ //

    private void AddMessage(string sender, string content, bool isUser)
    {
        Messages.Add(new ChatMessage
        {
            Sender  = sender,
            Content = content,
            IsUser  = isUser,
            Timestamp = DateTime.Now.ToString("HH:mm"),
        });
    }

    private void LogTool(string toolName, string result)
    {
        var preview = result.Length > 60 ? result[..60] + "…" : result;
        ToolLog.Insert(0, $"[{toolName}] {preview}");
        if (ToolLog.Count > 10) ToolLog.RemoveAt(ToolLog.Count - 1);
    }

    private void PushRmsToWaveform(float rms)
    {
        // Shift bars left, push new bar on right
        for (int i = 0; i < WaveformBars.Count - 1; i++)
            WaveformBars[i] = WaveformBars[i + 1];
        WaveformBars[^1] = Math.Max(4, rms * 50);
    }

    private void ResetWaveform()
    {
        for (int i = 0; i < WaveformBars.Count; i++)
            WaveformBars[i] = 4;
    }

    private readonly Random _rng = new();
    private void AnimateWaveform(object? s, EventArgs e)
    {
        // Idle animation when mic is on but silent
        for (int i = 0; i < WaveformBars.Count - 1; i++)
            WaveformBars[i] = WaveformBars[i + 1];
        WaveformBars[^1] = 4 + _rng.NextDouble() * 6;
    }
}
