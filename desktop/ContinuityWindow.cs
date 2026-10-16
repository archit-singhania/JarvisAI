using System.Collections.ObjectModel;
using System.Net.Http;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Automation;
using Microsoft.Win32;
using JarvisAI.Services;

namespace JarvisAI;

/// <summary>Native owned workspace tools. Opening this window performs reads only.</summary>
public sealed partial class ContinuityWindow : Window
{
    private readonly Func<string,HttpMethod?,object?,Task<JsonElement>> api;
    private readonly HttpClient http;
    private readonly Action<string,string> applyLayout;
    private readonly string conversation;
    private readonly TextBlock status=new(){Text="Your drafts stay here while switching tabs.",TextWrapping=TextWrapping.Wrap,Margin=new(18)};
    private readonly AudioService recording=new();
    private readonly System.Windows.Threading.DispatcherTimer limit=new(){Interval=TimeSpan.FromMinutes(30)};
    private bool closing;
    private readonly Func<string?>? audioChooser;
    private readonly Func<string,bool>? confirmation;
    private readonly Func<string,Task>? selectConversation;
    public ContinuityWindow(Func<string,HttpMethod?,object?,Task<JsonElement>> api,HttpClient http,string conversation,Action<string,string> applyLayout,Func<string?>? audioChooser=null,Func<string,bool>? confirmation=null,Func<string,Task>? selectConversation=null)
    {
        this.api=api;this.http=http;this.conversation=conversation;this.applyLayout=applyLayout;this.audioChooser=audioChooser;this.confirmation=confirmation;this.selectConversation=selectConversation;
        Title="Wednesday · Continuity studio";Width=1120;Height=840;MinWidth=760;MinHeight=600;WindowStartupLocation=WindowStartupLocation.CenterOwner;
        SetResourceReference(BackgroundProperty,"BgPanel");SetResourceReference(ForegroundProperty,"TextPrimary");
        var dock=new DockPanel();DockPanel.SetDock(status,Dock.Bottom);dock.Children.Add(status);
        var tabs=new TabControl{Margin=new(18)};
        AddTab(tabs,"Branches",Branches());AddTab(tabs,"Routines",Routines());AddTab(tabs,"Meetings",Meetings());AddTab(tabs,"Digests",Digests());AddTab(tabs,"Layouts",Layouts());dock.Children.Add(tabs);Content=dock;
        limit.Tick+=async(_,_)=>{limit.Stop();if(recording.IsRecording){var bytes=await recording.StopRecordingAsync();RecoverRecording(bytes);status.Text="Recording reached its 30-minute limit; save the WAV for import.";}};
        Closing+=async(_,e)=>{
            if(recording.IsRecording&&!closing){e.Cancel=true;if(MessageBox.Show(this,"Stop recording and save the audio before closing?","Meeting recording",MessageBoxButton.YesNo)!=MessageBoxResult.Yes)return;
                closing=true;limit.Stop();RecoverRecording(await recording.StopRecordingAsync());Close();}
        };
        Closed+=(_,_)=>{limit.Stop();recording.Dispose();};
    }
    private static string Text(JsonElement value,string key)=>value.TryGetProperty(key,out var x)?x.ToString():"";
    public void SelectPanel(string title)
    {
        if(Content is DockPanel dock){var tabs=dock.Children.OfType<TabControl>().Single();var tab=tabs.Items.OfType<TabItem>().FirstOrDefault(t=>t.Header.ToString()==title);if(tab is not null)tabs.SelectedItem=tab;}
    }
    private static void AddTab(TabControl tabs,string title,StackPanel panel)=>tabs.Items.Add(new TabItem{Header=title,Content=new ScrollViewer{Content=panel,VerticalScrollBarVisibility=ScrollBarVisibility.Auto}});
    private static StackPanel Panel(string title,string description){var p=new StackPanel{Margin=new(20)};p.Children.Add(new TextBlock{Text=title,FontSize=26,Margin=new(0,0,0,12)});p.Children.Add(new TextBlock{Text=description,TextWrapping=TextWrapping.Wrap,Margin=new(0,0,0,18)});return p;}
    private static TextBox Field(StackPanel p,string label,string value="",bool multi=false){p.Children.Add(new TextBlock{Text=label});var box=new TextBox{Text=value,AcceptsReturn=multi,MinHeight=multi?100:30,TextWrapping=multi?TextWrapping.Wrap:TextWrapping.NoWrap,Margin=new(0,6,0,14)};AutomationProperties.SetName(box,label);p.Children.Add(box);return box;}
    private Button Button(StackPanel p,string title,Func<Task> run){var button=new Button{Content=title,HorizontalAlignment=HorizontalAlignment.Left,Margin=new(0,6,0,12)};button.Click+=async(_,_)=>{button.IsEnabled=false;try{await run();}catch(Exception error){status.Text=error.Message;}finally{button.IsEnabled=true;}};p.Children.Add(button);return button;}
    private static CheckBox Check(StackPanel p,string text){var c=new CheckBox{Content=text,Margin=new(0,8,0,12)};p.Children.Add(c);return c;}
    private static ComboBox Choice(StackPanel p,string label,params string[] choices){p.Children.Add(new TextBlock{Text=label});var c=new ComboBox{ItemsSource=choices,SelectedIndex=0,Margin=new(0,6,0,14)};AutomationProperties.SetName(c,label);p.Children.Add(c);return c;}
    private bool Confirm(string text)=>confirmation?.Invoke(text)??(MessageBox.Show(this,text,"Review this action",MessageBoxButton.YesNo,MessageBoxImage.Question)==MessageBoxResult.Yes);
    private static string[] Lines(string value)=>value.Split('\n',StringSplitOptions.RemoveEmptyEntries|StringSplitOptions.TrimEntries);

    private StackPanel Branches()
    {
        var p=Panel("Independent directions","Branch from a saved message. The original context is frozen; parent history and global memory remain unchanged.");
        var chats=new ComboBox{DisplayMemberPath="Title",Margin=new(0,0,0,14)};AutomationProperties.SetName(chats,"Conversation");p.Children.Add(chats);
        var messages=new ListBox{DisplayMemberPath="Title",MaxHeight=240};AutomationProperties.SetName(messages,"Branch from message");p.Children.Add(messages);
        TextBox title=Field(p,"New branch title","Alternative direction"),compare=Field(p,"Immutable parent comparison","",true);compare.IsReadOnly=true;
        Button(p,"Load conversations",async()=>{var data=await api("conversations",null,null);chats.ItemsSource=data.GetProperty("conversations").EnumerateArray().Select(c=>new Option(Text(c,"id"),Text(c,"title"))).ToList();});
        Button(p,"Inspect selected conversation",async()=>{
            if(chats.SelectedItem is not Option selected)throw new InvalidOperationException("Select a conversation.");var data=await api("conversations/"+selected.Id,null,null);
            messages.ItemsSource=data.GetProperty("messages").EnumerateArray().Select(m=>new Option(Text(m,"id"),Text(m,"role")+": "+Text(m,"content"))).ToList();
            var links=await api("continuity/conversations/"+selected.Id+"/branches",null,null);var parent=links.GetProperty("parent");
            compare.Text=parent.ValueKind==JsonValueKind.Null?"This is an original conversation.":string.Join("\n\n",parent.GetProperty("snapshot").EnumerateArray().Select(m=>Text(m,"role")+": "+Text(m,"content")));
        });
        Button(p,"Create independent branch",async()=>{if(chats.SelectedItem is not Option selected||messages.SelectedItem is not Option message)throw new InvalidOperationException("Select a conversation and message.");var branch=await api("continuity/conversations/"+selected.Id+"/branches",HttpMethod.Post,new{message_id=int.Parse(message.Id),title=title.Text});status.Text="Branch saved: "+Text(branch,"title")+". Reload conversations to inspect it.";});
        Button(p,"Continue selected conversation in assistant",async()=>{if(recording.IsRecording)throw new InvalidOperationException("Stop and save the meeting recording first.");if(chats.SelectedItem is Option selected&&selectConversation is not null){await selectConversation(selected.Id);Close();}});return p;
    }
    private StackPanel Routines()
    {
        var p=Panel("Ordered routine builder","Read-only tools, approved assistant requests and confirmed reminders. No arbitrary scripts or host commands.");var name=Field(p,"Routine title","Review routine");
        var models=new ObservableCollection<RoutineStep>();var grid=new DataGrid{ItemsSource=models,AutoGenerateColumns=false,CanUserAddRows=false,MinHeight=200,Margin=new(0,0,0,14)};
        grid.Columns.Add(new DataGridComboBoxColumn{Header="Action",ItemsSource=new[]{"time","search","weather","assistant","reminder"},SelectedItemBinding=new System.Windows.Data.Binding("tool")});
        foreach(var key in new[]{"argument","condition","failure","input_step","due_at","timezone"})grid.Columns.Add(new DataGridTextColumn{Header=key.Replace('_',' '),Binding=new System.Windows.Data.Binding(key)});
        p.Children.Add(grid);Button(p,"Add step",()=>{if(models.Count>=20)throw new InvalidOperationException("Limit: 20 steps.");models.Add(new());return Task.CompletedTask;});
        Button(p,"Remove selected step",()=>{if(grid.SelectedItem is RoutineStep s)models.Remove(s);return Task.CompletedTask;});
        Button(p,"Move step up",()=>{if(grid.SelectedItem is RoutineStep s){var i=models.IndexOf(s);if(i>0)models.Move(i,i-1);}return Task.CompletedTask;});
        Button(p,"Save routine",async()=>{grid.CommitEdit();grid.CommitEdit();await api("routines",HttpMethod.Post,new{title=name.Text,steps=models.ToArray()});status.Text="Routine saved. Input references use zero-based earlier step numbers; conditions: always/previous_success/previous_failure; failures: stop/continue.";});
        var definitions=new ComboBox{DisplayMemberPath="Title"};p.Children.Add(definitions);var runs=new ComboBox{DisplayMemberPath="Title"};p.Children.Add(runs);var report=Field(p,"Preview and execution receipts","",true);report.IsReadOnly=true;
        Button(p,"Refresh routines and runs",async()=>{var d=await api("routines",null,null);definitions.ItemsSource=d.GetProperty("routines").EnumerateArray().Select(r=>new Option(Text(r,"id"),Text(r,"title"))).ToList();var result=await api("routines/runs",null,null);runs.ItemsSource=result.GetProperty("runs").EnumerateArray().Select(r=>new Option(Text(r,"id"),Text(r.GetProperty("snapshot"),"title")+" · "+Text(r,"status"))).ToList();});
        Button(p,"Dry-run preview",async()=>{if(definitions.SelectedItem is not Option s)return;var d=await api("routines/"+s.Id+"/preview",HttpMethod.Post,null);report.Text=string.Join("\n",d.GetProperty("steps").EnumerateArray().Select(x=>Text(x,"tool")+": "+Text(x,"argument")+" · confirmation "+Text(x,"confirmation_required")));});
        Button(p,"Run reviewed routine",async()=>{if(definitions.SelectedItem is not Option s||!Confirm("Run "+s.Title+"? Consequential steps pause for individual approval."))return;var d=await api("routines/"+s.Id+"/preview",HttpMethod.Post,null);await api("routines/"+s.Id+"/runs",HttpMethod.Post,new{revision=d.GetProperty("revision").GetInt32()});status.Text="Run queued. Refresh to inspect progress.";});
        Button(p,"Inspect selected run",async()=>{if(runs.SelectedItem is not Option s)return;var d=await api("routines/runs/"+s.Id,null,null);report.Text=Text(d,"status")+"\n"+string.Join("\n",d.GetProperty("results").EnumerateArray().Select(x=>Text(x,"step")+": "+Text(x,"content")));});
        Button(p,"Confirm waiting step",async()=>{if(runs.SelectedItem is not Option s)return;var d=await api("routines/runs/"+s.Id,null,null);var cursor=d.GetProperty("cursor").GetInt32();if(Text(d,"status")!="awaiting_confirmation")throw new InvalidOperationException("This run is not awaiting confirmation.");var step=d.GetProperty("snapshot").GetProperty("steps")[cursor];if(Confirm("Approve "+Text(step,"tool")+": "+Text(step,"argument")+"?"))await api("routines/runs/"+s.Id+"/confirm",HttpMethod.Post,new{cursor});});
        Button(p,"Stop remaining steps",async()=>{if(runs.SelectedItem is Option s)await api("routines/runs/"+s.Id+"/stop",HttpMethod.Post,null);});return p;
    }
    private StackPanel Meetings()
    {
        var p=Panel("Consented meeting notes","A provisioned local engine transcribes timestamped segments. Failed jobs retain audio for Retry/Delete. Raw audio is deleted after success unless retention is selected.");var title=Field(p,"Meeting title","Meeting");CheckBox consent=Check(p,"I have participant consent to record/import this meeting."),retain=Check(p,"Retain raw audio after successful transcription.");
        async Task Upload(byte[]? bytes,string? filename){if(consent.IsChecked!=true)throw new InvalidOperationException("Confirm consent first.");using var body=new MultipartFormDataContent();body.Add(new StringContent(title.Text),"title");body.Add(new StringContent("true"),"consent");body.Add(new StringContent(retain.IsChecked==true?"true":"false"),"retain");if(bytes is not null)body.Add(new ByteArrayContent(bytes),"file","meeting.wav");else{if(new FileInfo(filename!).Length>100*1024*1024)throw new InvalidOperationException("Audio limit: 100 MB.");body.Add(new StreamContent(File.OpenRead(filename!)),"file",Path.GetFileName(filename!));}using var response=await http.PostAsync("/api/meetings",body);if(!response.IsSuccessStatusCode)throw new InvalidOperationException("Meeting import failed. Audio was not confirmed saved; retry or keep a local copy.");status.Text="Meeting saved to the local transcription queue.";}
        Button(p,"Import consented audio",async()=>{if(consent.IsChecked!=true)throw new InvalidOperationException("Confirm consent first.");if(audioChooser is not null){var chosen=audioChooser();if(chosen is not null)await Upload(null,chosen);}else{var file=new OpenFileDialog{Filter="Audio|*.wav;*.mp3;*.m4a;*.ogg;*.webm;*.flac"};if(file.ShowDialog()==true)await Upload(null,file.FileName);}});
        Button(p,"Start meeting recording",()=>{if(consent.IsChecked!=true)throw new InvalidOperationException("Confirm consent first.");if(recording.IsRecording)throw new InvalidOperationException("A recording is already active.");recording.StartRecording();limit.Start();status.Text="● RECORDING MEETING · Stop recording to save";return Task.CompletedTask;});
        Button(p,"■ Stop and save recording",async()=>{if(!recording.IsRecording)return;limit.Stop();var bytes=await recording.StopRecordingAsync();try{await Upload(bytes,null);}catch{RecoverRecording(bytes);throw;}});
        var selected=new ComboBox{DisplayMemberPath="Title"};p.Children.Add(selected);var transcript=Field(p,"Timestamped transcript","",true);transcript.IsReadOnly=true;TextBox notes=Field(p,"Notes","",true),decisions=Field(p,"Decisions · one per line","",true),reminders=Field(p,"Proposed reminders · one per line","",true);int revision=0;string loaded="";
        Button(p,"Refresh meeting jobs",async()=>{var data=await api("meetings",null,null);status.Text=Text(data.GetProperty("capability"),"detail");selected.ItemsSource=data.GetProperty("meetings").EnumerateArray().Select(r=>new Option(Text(r,"id"),Text(r,"title")+" · "+Text(r,"status"))).ToList();});
        Button(p,"Load selected meeting",async()=>{if(selected.SelectedItem is not Option s)return;var data=await api("meetings/"+s.Id,null,null);loaded=s.Id;revision=data.GetProperty("revision").GetInt32();transcript.Text=string.Join("\n",data.GetProperty("transcript").EnumerateArray().Select(x=>Text(x,"start")+"–"+Text(x,"end")+"s: "+Text(x,"text")));var n=data.GetProperty("notes");notes.Text=Text(n,"notes");decisions.Text=n.TryGetProperty("decisions",out var d)?string.Join("\n",d.EnumerateArray().Select(x=>x.GetString())):"";reminders.Text=n.TryGetProperty("proposed_reminders",out var r)?string.Join("\n",r.EnumerateArray().Select(x=>x.GetString())):"";status.Text=Text(data,"status")+" · audio present: "+Text(data,"audio_present")+" "+Text(data,"error");});
        Button(p,"Save notes and proposals",async()=>{if(loaded.Length==0)throw new InvalidOperationException("Load a meeting first.");var data=await api("meetings/"+loaded,HttpMethod.Patch,new{revision,notes=notes.Text,decisions=Lines(decisions.Text),proposed_reminders=Lines(reminders.Text)});revision=data.GetProperty("revision").GetInt32();status.Text="Saved. Proposals do not create reminders; review them in Reminders.";});
        Button(p,"Retry failed transcription",async()=>{if(selected.SelectedItem is Option s)await api("meetings/"+s.Id+"/retry",HttpMethod.Post,null);});
        Button(p,"Delete meeting and retained audio",async()=>{if(selected.SelectedItem is Option s&&Confirm("Delete this meeting, notes and retained audio?"))await api("meetings/"+s.Id,HttpMethod.Delete,null);});return p;
    }
    private void RecoverRecording(byte[] bytes){var save=new SaveFileDialog{Filter="WAV audio|*.wav",FileName="meeting-recovery.wav"};if(save.ShowDialog(this)==true)File.WriteAllBytes(save.FileName,bytes);}
    private StackPanel Digests()
    {
        var p=Panel("Selected-source digest","Check the sources you want included. Excluded conversations never enter this deterministic excerpt digest.");var sources=new StackPanel();p.Children.Add(sources);var chosen=new List<(CheckBox Check,string Kind,string Id)>();
        Button(p,"Load available sources",async()=>{sources.Children.Clear();chosen.Clear();foreach(var endpoint in new[]{"conversations","reminders","receipts"}){var data=await api(endpoint,null,null);foreach(var row in data.GetProperty(endpoint).EnumerateArray()){var title=Text(row,"title");if(title.Length==0)title=Text(row,"text");if(title.Length==0)title=Text(row,"tool");var c=Check(sources,endpoint+": "+title);chosen.Add((c,endpoint,Text(row,"id")));}}});
        TextBox since=Field(p,"Include since · timezone-aware date",DateTimeOffset.UtcNow.AddDays(-7).ToString("O")),report=Field(p,"Saved digest","",true);report.IsReadOnly=true;
        Button(p,"Generate checked-source digest",async()=>{var data=await api("continuity/digests",HttpMethod.Post,new{since=since.Text,conversation_ids=chosen.Where(c=>c.Check.IsChecked==true&&c.Kind=="conversations").Select(c=>c.Id).ToArray(),reminder_ids=chosen.Where(c=>c.Check.IsChecked==true&&c.Kind=="reminders").Select(c=>c.Id).ToArray(),receipt_ids=chosen.Where(c=>c.Check.IsChecked==true&&c.Kind=="receipts").Select(c=>c.Id).ToArray()});report.Text=Text(data,"coverage")+"\n\n"+string.Join("\n\n",data.GetProperty("items").EnumerateArray().Select(x=>Text(x,"title")+": "+Text(x,"text")+"\nSource: "+Text(x,"source_id")));});
        Button(p,"Reload latest saved digest",async()=>{var d=await api("continuity/digests",null,null);var rows=d.GetProperty("digests").EnumerateArray().ToArray();report.Text=rows.Length==0?"No digest saved.":Text(rows[0],"coverage")+"\n\n"+string.Join("\n\n",rows[0].GetProperty("items").EnumerateArray().Select(x=>Text(x,"title")+": "+Text(x,"text")+"\nSource: "+Text(x,"source_id")));});var enabled=Check(p,"Enable a local schedule from checked sources");var period=Choice(p,"Frequency","daily","weekly");var zone=Field(p,"Schedule timezone","UTC");var hour=Field(p,"Schedule hour · 0–23","9");var minute=Field(p,"Schedule minute · 0–59","0");var weekday=Field(p,"Weekly day · Monday 0 through Sunday 6","0");
        Button(p,"Save selected-source schedule",async()=>{
            if(!int.TryParse(hour.Text,out var h)||!int.TryParse(minute.Text,out var m)||!int.TryParse(weekday.Text,out var w))throw new InvalidOperationException("Use whole numbers for schedule time and weekday.");
            await api("continuity/digest-schedule",HttpMethod.Put,new{enabled=enabled.IsChecked==true,period=period.SelectedItem.ToString(),timezone=zone.Text,hour=h,minute=m,weekday=w,conversation_ids=chosen.Where(c=>c.Check.IsChecked==true&&c.Kind=="conversations").Select(c=>c.Id).ToArray(),reminder_ids=chosen.Where(c=>c.Check.IsChecked==true&&c.Kind=="reminders").Select(c=>c.Id).ToArray(),receipt_ids=chosen.Where(c=>c.Check.IsChecked==true&&c.Kind=="receipts").Select(c=>c.Id).ToArray()});status.Text="Schedule saved for only the checked sources. The local service must be running.";
        });
        Button(p,"Reload saved schedule",async()=>{
            var d=await api("continuity/digest-schedule",null,null);var row=d.GetProperty("schedule");if(row.ValueKind==JsonValueKind.Null){status.Text="No schedule saved.";return;}var c=row.GetProperty("configuration");enabled.IsChecked=c.GetProperty("enabled").GetBoolean();period.SelectedItem=Text(c,"period");zone.Text=Text(c,"timezone");hour.Text=Text(c,"hour");minute.Text=Text(c,"minute");weekday.Text=Text(c,"weekday");
            foreach(var item in chosen)item.Check.IsChecked=c.GetProperty(item.Kind=="conversations"?"conversation_ids":item.Kind=="reminders"?"reminder_ids":"receipt_ids").EnumerateArray().Any(x=>x.GetString()==item.Id);
            status.Text="Next due: "+Text(row,"next_due")+" "+Text(row,"error");
        });return p;
    }
    private StackPanel Layouts()
    {
        var p=Panel("Task-aware layouts","Layouts change panel density only. Drafts remain intact; no recording, tool or permission is enabled.");var name=Field(p,"Layout name","Focus");var rail=Choice(p,"Navigation rail","expanded","compact");var density=Choice(p,"Content density","comfortable","focused");
        Button(p,"Save desktop layout",async()=>{await api("continuity/layouts/wpf",HttpMethod.Post,new{title=name.Text,value=new{version=1,view="chat",rail=rail.SelectedItem.ToString(),density=density.SelectedItem.ToString(),context_ids=conversation.Length>0?new[]{conversation}:Array.Empty<string>()}});status.Text="Desktop layout saved.";});
        var layouts=new ComboBox{DisplayMemberPath="Title"};p.Children.Add(layouts);var values=new Dictionary<string,JsonElement>();Button(p,"Load desktop layouts",async()=>{var d=await api("continuity/layouts/wpf",null,null);values.Clear();foreach(var row in d.GetProperty("layouts").EnumerateArray())values[Text(row,"id")]=row.GetProperty("value").Clone();layouts.ItemsSource=d.GetProperty("layouts").EnumerateArray().Select(x=>new Option(Text(x,"id"),Text(x,"title"))).ToList();});
        Button(p,"Restore selected layout",async()=>{if(recording.IsRecording)throw new InvalidOperationException("Stop and save the recording before restoring a layout.");if(layouts.SelectedItem is Option s){var v=values[s.Id];var contexts=v.GetProperty("context_ids").EnumerateArray().Select(x=>x.GetString()).Where(x=>!string.IsNullOrEmpty(x)).ToArray();if(contexts.Length>0&&selectConversation is not null){await api("conversations/"+contexts[0],null,null);await selectConversation(contexts[0]!);}applyLayout(Text(v,"rail"),Text(v,"density"));status.Text="Layout restored. Drafts and permissions are preserved.";}});return p;
    }
    private sealed record Option(string Id,string Title);
    public sealed class RoutineStep
    {
        public string tool{get;set;}="time";
        public string argument{get;set;}="";
        public string condition{get;set;}="always";
        public string failure{get;set;}="stop";
        public int? input_step{get;set;}
        public string? due_at{get;set;}
        public string timezone{get;set;}="UTC";
    }
}
