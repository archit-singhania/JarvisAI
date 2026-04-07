using System.Windows.Media;

namespace JarvisAI.Models;

/// <summary>A single chat message shown in the UI.</summary>
public class ChatMessage
{
    public string Sender    { get; set; } = "";
    public string Content   { get; set; } = "";
    public string Timestamp { get; set; } = DateTime.Now.ToString("HH:mm");
    public bool   IsUser    { get; set; }

    public string Alignment   => IsUser ? "Right" : "Left";
    public Color  BubbleColor => IsUser
        ? Color.FromRgb(0x1C, 0x3A, 0x6E)
        : Color.FromRgb(0x0E, 0x2A, 0x38);
}
