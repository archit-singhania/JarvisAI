using CommunityToolkit.Mvvm.ComponentModel;

namespace JarvisAI.Models;
public partial class ChatMessage : ObservableObject
{
    [ObservableProperty] private string content="";
    public string Sender{get;set;}="Wednesday";
    public bool IsUser{get;set;}
    public string Timestamp{get;set;}=DateTime.Now.ToString("HH:mm");
}

public sealed record WorkspaceItem(string Id,string Title,string Content);
