using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JarvisAI.Models;
using JarvisAI.Services;
using Microsoft.Win32;

namespace JarvisAI;
public partial class MainViewModel : ObservableObject, IDisposable
{
    private readonly JarvisWebSocketService ws=new();
    private readonly AudioService audio=new();
    private readonly HttpClient http=new(){BaseAddress=new Uri(Environment.GetEnvironmentVariable("WEDNESDAY_URL")??"http://127.0.0.1:8000")};
    private readonly string stateFile=Path.Combine(Environment.GetEnvironmentVariable("WEDNESDAY_CLIENT_DATA")??Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Wednesday"),"session.json");
    private string token="",conversation="",turn="";
    private bool disposed;
    private ChatMessage? streaming;
    private readonly HashSet<string> blocked=[];
    [ObservableProperty] private string inputText="";
    [ObservableProperty] private string connectionStatus="Connecting workspace…";
    [ObservableProperty] private string section="Assistant";
    [ObservableProperty] private string recordTitle="";
    [ObservableProperty] private string recordContent="";
    [ObservableProperty] private string reminderTime="";
    [ObservableProperty] private bool isListening;
    [ObservableProperty] private bool speakResponses;
    [ObservableProperty] private string focus="assistant";
    [ObservableProperty] private string appearance="system";
    [ObservableProperty] private string modelProvider="ollama";
    [ObservableProperty] private string localModel="llama3.1:8b";
    [ObservableProperty] private string cloudModel="llama-3.1-8b-instant";
    [ObservableProperty] private string language="en";
    [ObservableProperty] private string persona="";
    [ObservableProperty] private string reminderZone="Asia/Kolkata";
    [ObservableProperty] private bool reduceMotion;
    [ObservableProperty] private bool reduceTransparency;
    private string editingId="";
    public ObservableCollection<ChatMessage> Messages{get;}=[];
    public ObservableCollection<WorkspaceItem> Items{get;}=[];
    public ObservableCollection<double> WaveformBars{get;}=new(Enumerable.Repeat(4d,32));

    public MainViewModel()
    {
        ReminderTime=ReminderClock.Suggest(ReminderZone,DateTimeOffset.UtcNow)??"";
        ws.OnConnectionChanged+=connected=>Application.Current.Dispatcher.Invoke(()=>ConnectionStatus=connected?"Workspace connected":"Disconnected · use Reconnect");
        ws.MessageReceived+=message=>Application.Current.Dispatcher.Invoke(()=>Handle(message));
        audio.OnRmsLevel+=rms=>Application.Current.Dispatcher.InvokeAsync(()=>{for(int i=0;i<31;i++)WaveformBars[i]=WaveformBars[i+1];WaveformBars[31]=Math.Max(4,rms*160);});
        audio.OnError+=error=>Application.Current.Dispatcher.Invoke(()=>ConnectionStatus="Audio: "+error);
        _=Guard(Initialize);
    }

    partial void OnReminderZoneChanged(string value)
    {
        var suggested=ReminderClock.Suggest(value,DateTimeOffset.UtcNow);
        if(suggested is not null)ReminderTime=suggested;
    }

    private async Task<JsonElement> Api(string path,HttpMethod? method=null,object? body=null)
    {
        using var request=new HttpRequestMessage(method??HttpMethod.Get,"/api/"+path);
        if(body is not null)request.Content=new StringContent(JsonSerializer.Serialize(body),Encoding.UTF8,"application/json");
        using var response=await http.SendAsync(request);var text=await response.Content.ReadAsStringAsync();
        if(!response.IsSuccessStatusCode)throw new InvalidOperationException(ApiError(text));
        using var json=JsonDocument.Parse(text);return json.RootElement.Clone();
    }

    private async Task Initialize()
    {
        if(File.Exists(stateFile)){using var saved=JsonDocument.Parse(await File.ReadAllTextAsync(stateFile));token=saved.RootElement.GetProperty("token").GetString()??"";conversation=saved.RootElement.GetProperty("conversation").GetString()??"";}
        http.DefaultRequestHeaders.Authorization=new AuthenticationHeaderValue("Bearer",token);
        var session=await Api("session",HttpMethod.Post);var newToken=session.GetProperty("token").GetString()!;
        if(newToken!=token)conversation="";
        token=newToken;http.DefaultRequestHeaders.Authorization=new("Bearer",token);
        if(conversation.Length>0){try{await Api("conversations/"+conversation);}catch{conversation="";}}
        var p=session.GetProperty("preferences");SpeakResponses=p.GetProperty("tts").GetBoolean();Focus=p.GetProperty("focus").GetString()??"assistant";
        Appearance=Text(p,"theme");ModelProvider=Text(p,"llm_provider");LocalModel=Text(p,"ollama_model");CloudModel=Text(p,"llm_model");Language=Text(p,"language");Persona=Text(p,"persona");ReminderZone=Text(p,"timezone");ReduceMotion=p.GetProperty("reduce_motion").GetBoolean();ReduceTransparency=p.GetProperty("reduce_transparency").GetBoolean();ThemeManager.Apply(Appearance);
        await Connect();
    }

    private async Task Connect()
    {
        var endpoint=new UriBuilder(http.BaseAddress!){Scheme=http.BaseAddress!.Scheme=="https"?"wss":"ws",Path="/ws",Query=conversation.Length>0?"conversation_id="+conversation:""};
        await ws.ConnectAsync(endpoint.Uri,token);
    }
    private async Task Guard(Func<Task> action){try{await action();}catch(Exception error){ConnectionStatus=error.Message.Length>220?error.Message[..220]:error.Message;}}
    private static string Text(JsonElement data,string name)=>data.TryGetProperty(name,out var value)?value.GetString()??"":"";
    private static string ApiError(string text){try{using var error=JsonDocument.Parse(text);var detail=error.RootElement.GetProperty("detail");return detail.ValueKind==JsonValueKind.String?detail.GetString()!:"Check the supplied fields.";}catch{return "The service request failed. Check the connection and try again.";}}

    private void Handle(JsonElement data)
    {
        var type=Text(data,"type");var eventTurn=Text(data,"turn_id");
        if(type=="stream_start"){turn=eventTurn;streaming=new(){Sender="Wednesday"};Messages.Add(streaming);}
        if(blocked.Contains(eventTurn)&&type is not ("interrupted" or "cleared" or "session"))return;
        switch(type)
        {
            case "session":
                conversation=Text(data,"conversation_id");Messages.Clear();
                foreach(var m in data.GetProperty("history").EnumerateArray())Messages.Add(new(){Sender=Text(m,"role")=="user"?"You":"Wednesday",Content=Text(m,"content"),IsUser=Text(m,"role")=="user"});
                Directory.CreateDirectory(Path.GetDirectoryName(stateFile)!);File.WriteAllText(stateFile,JsonSerializer.Serialize(new{token,conversation}));break;
            case "stream_chunk":if(streaming is not null)streaming.Content+=Text(data,"content");break;
            case "stream_end":streaming=null;ConnectionStatus="Ready when you are";break;
            case "response":case "reminder":Messages.Add(new(){Content=Text(data,"content")});if(type=="reminder")_=ws.SendAsync(new{type="reminder_ack",reminder_id=Text(data,"reminder_id")});break;
            case "audio_chunk":audio.EnqueueAudio(Convert.FromBase64String(Text(data,"audio_b64")),Text(data,"audio_format"));break;
            case "transcript":Messages.Add(new(){Sender="You",IsUser=true,Content=Text(data,"content")});break;
            case "interrupted":audio.StopPlayback();streaming=null;ConnectionStatus="Interrupted";break;
            case "error":case "stt_error":case "speech_unavailable":ConnectionStatus=Text(data,"content");break;
            case "cleared":conversation=Text(data,"conversation_id");Messages.Clear();turn="";streaming=null;blocked.Clear();File.WriteAllText(stateFile,JsonSerializer.Serialize(new{token,conversation}));break;
        }
    }

    [RelayCommand] private Task Reconnect()=>Guard(Initialize);
    [RelayCommand] private Task SendText()=>Guard(async()=>{var text=InputText.Trim();if(text.Length==0)return;await ws.SendAsync(new{type="text",content=text,tts=SpeakResponses});audio.StopPlayback();Messages.Add(new(){Sender="You",Content=text,IsUser=true});InputText="";});
    [RelayCommand] private Task Interrupt()=>Guard(async()=>{if(turn.Length>0)blocked.Add(turn);audio.StopPlayback();await ws.SendAsync(new{type="interrupt"});});
    [RelayCommand] private Task ToggleMic()=>Guard(async()=>{if(!audio.IsRecording){audio.StartRecording();IsListening=true;ConnectionStatus="Listening · press Voice again to send";}else{var bytes=await audio.StopRecordingAsync();IsListening=false;await ws.SendAsync(new{type="audio",audio_b64=Convert.ToBase64String(bytes),language=Language,tts=SpeakResponses});}});
    [RelayCommand] private Task ClearChat()=>Guard(async()=>{await ws.SendAsync(new{type="clear"});});
    [RelayCommand] private Task ScreenAnalyze()=>Guard(async()=>{var picker=new OpenFileDialog{Filter="Images|*.png;*.jpg;*.jpeg;*.webp"};if(picker.ShowDialog()!=true)return;var bytes=await File.ReadAllBytesAsync(picker.FileName);if(bytes.Length>8*1024*1024)throw new InvalidOperationException("Select an image smaller than 8 MB.");await ws.SendAsync(new{type="screen",image_b64=Convert.ToBase64String(bytes),prompt="Describe this selected image."});});
    [RelayCommand] private Task ImportDocument()=>Guard(async()=>{var picker=new OpenFileDialog{Filter="Documents|*.pdf;*.txt;*.md;*.csv;*.json;*.py;*.js;*.ts;*.cs;*.dart"};if(picker.ShowDialog()!=true)return;using var content=new MultipartFormDataContent();content.Add(new ByteArrayContent(await File.ReadAllBytesAsync(picker.FileName)),"file",Path.GetFileName(picker.FileName));using var response=await http.PostAsync("/api/documents",content);if(!response.IsSuccessStatusCode)throw new InvalidOperationException(await response.Content.ReadAsStringAsync());ConnectionStatus="Document imported";await OpenSection("Knowledge");});
    [RelayCommand] private Task OpenSection(string name)=>Guard(async()=>{Section=name;Items.Clear();editingId="";if(name is "Assistant" or "Preferences")return;var endpoint=name switch{"Knowledge"=>"documents","Memory"=>"memories","Reminders"=>"reminders","Workflows"=>"workflows",_=>"receipts"};var data=await Api(endpoint);foreach(var item in data.GetProperty(endpoint).EnumerateArray()){var title=Text(item,"title");if(title.Length==0)title=Text(item,"text");if(title.Length==0)title=Text(item,"tool");var content=Text(item,"content");if(name=="Reminders")content=Text(item,"due_at")+" · "+Text(item,"status");if(name=="Tools")content=item.GetProperty("result").GetProperty("content").GetString()??"";Items.Add(new(Text(item,"id"),title,content));}});
    [RelayCommand] private Task SaveRecord()=>Guard(async()=>{if(Section=="Memory")await Api("memories"+(editingId.Length>0?"/"+editingId:""),editingId.Length>0?HttpMethod.Patch:HttpMethod.Post,new{title=RecordTitle,content=RecordContent});else if(Section=="Reminders"){if(!DateTime.TryParseExact(ReminderTime,"yyyy-MM-dd HH:mm",System.Globalization.CultureInfo.InvariantCulture,System.Globalization.DateTimeStyles.None,out var date))throw new InvalidOperationException("Use yyyy-MM-dd HH:mm for reminder time.");await Api("reminders",HttpMethod.Post,new{text=RecordTitle,due_at=date.ToString("yyyy-MM-ddTHH:mm:ss"),timezone=ReminderZone});}else if(Section=="Workflows"){var steps=RecordContent.Split('\n',StringSplitOptions.RemoveEmptyEntries).Select(line=>{var parts=line.Split(':',2);return new{tool=parts[0].Trim(),argument=parts.Length>1?parts[1].Trim():""};}).ToArray();await Api("workflows",HttpMethod.Post,new{title=RecordTitle,steps});}else return;RecordTitle="";RecordContent="";editingId="";await OpenSection(Section);});
    [RelayCommand] private void EditRecord(WorkspaceItem item){if(Section=="Memory"){editingId=item.Id;RecordTitle=item.Title;RecordContent=item.Content;}}
    [RelayCommand] private Task RunWorkflow(WorkspaceItem item)=>Guard(async()=>{var result=await Api("workflows/"+item.Id+"/run",HttpMethod.Post);ConnectionStatus=string.Join(" · ",result.GetProperty("results").EnumerateArray().Select(r=>Text(r,"content")));});
    [RelayCommand] private Task RunTool(string tool)=>Guard(async()=>{var result=await Api("tools/execute",HttpMethod.Post,new{tool,argument=RecordContent});ConnectionStatus=Text(result,"content");await OpenSection("Tools");});
    [RelayCommand] private Task RemoveRecord(WorkspaceItem item)=>Guard(async()=>{await Api((Section=="Reminders"?"reminders/":"records/")+item.Id,HttpMethod.Delete);await OpenSection(Section);});
    [RelayCommand] private void OpenPreferences()=>Section="Preferences";
    [RelayCommand] private Task SavePreferences()=>Guard(async()=>{await Api("preferences",HttpMethod.Patch,new{theme=Appearance,focus=Focus,persona=Persona,timezone=ReminderZone,tts=SpeakResponses,llm_provider=ModelProvider,llm_model=CloudModel,ollama_model=LocalModel,language=Language,reduce_motion=ReduceMotion,reduce_transparency=ReduceTransparency});ThemeManager.Apply(Appearance);ConnectionStatus="Preferences saved";});
    [RelayCommand] private Task Export()=>Guard(async()=>{var file=new SaveFileDialog{Filter="JSON workspace|*.json",FileName="wednesday-workspace.json"};if(file.ShowDialog()!=true)return;var data=await Api("export");await File.WriteAllTextAsync(file.FileName,JsonSerializer.Serialize(data,new JsonSerializerOptions{WriteIndented=true}));});
    public void Dispose(){if(disposed)return;disposed=true;ws.Dispose();audio.Dispose();http.Dispose();}
}
