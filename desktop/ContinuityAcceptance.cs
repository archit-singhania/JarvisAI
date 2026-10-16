using System.Net.Http;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;

namespace JarvisAI;
public sealed partial class ContinuityWindow
{
    private StackPanel AcceptancePanel(string title)=>((ScrollViewer)((DockPanel)Content).Children.OfType<TabControl>().Single().Items.OfType<TabItem>().Single(t=>t.Header.ToString()==title).Content).Content as StackPanel??throw new InvalidOperationException("Panel missing");
    private static TextBox AcceptanceField(StackPanel panel,string label)
    {
        for(int i=0;i<panel.Children.Count-1;i++)if(panel.Children[i] is TextBlock text&&text.Text==label&&panel.Children[i+1] is TextBox box)return box;
        throw new InvalidOperationException("Native field missing: "+label);
    }
    private async Task AcceptanceClick(StackPanel panel,string title)
    {
        var button=panel.Children.OfType<Button>().Single(b=>b.Content.ToString()==title);button.RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Button.ClickEvent));
        for(int i=0;i<1000&&!button.IsEnabled;i++)await Task.Delay(20);
        if(!button.IsEnabled)throw new TimeoutException("Native action did not finish: "+title);
    }
    private static void Require(bool condition,string message){if(!condition)throw new InvalidOperationException(message);}
    public async Task<object> VerifyContinuityAsync()
    {
        if(Environment.GetEnvironmentVariable("WEDNESDAY_ACCEPTANCE_MODE")!="1"||http.BaseAddress?.IsLoopback!=true)throw new InvalidOperationException("Native functional acceptance requires an isolated loopback fixture.");
        using(var health=await http.GetAsync("/health")){var value=JsonDocument.Parse(await health.Content.ReadAsStringAsync());Require(value.RootElement.GetProperty("demo_mode").GetBoolean(),"Use the isolated demonstration-mode fixture service.");}
        var parent=await api("conversations",HttpMethod.Post,new{title="QA native parent "+Guid.NewGuid().ToString("N"),mode="assistant"});var parentId=Text(parent,"id");
        using(var socket=new ClientWebSocket())
        {
            socket.Options.SetRequestHeader("Authorization",http.DefaultRequestHeaders.Authorization!.ToString());var url=new UriBuilder(http.BaseAddress!){Scheme="ws",Path="/ws",Query="conversation_id="+parentId};await socket.ConnectAsync(url.Uri,CancellationToken.None);
            var buffer=new byte[65536];await socket.ReceiveAsync(buffer,CancellationToken.None);await socket.SendAsync(Encoding.UTF8.GetBytes("{\"type\":\"text\",\"content\":\"Illustrative native QA original context\",\"tts\":false}"),WebSocketMessageType.Text,true,CancellationToken.None);
            for(int i=0;i<100;i++){var history=await api("conversations/"+parentId,null,null);if(history.GetProperty("messages").GetArrayLength()>0)break;await Task.Delay(50);}
            await socket.SendAsync(Encoding.UTF8.GetBytes("{\"type\":\"interrupt\"}"),WebSocketMessageType.Text,true,CancellationToken.None);
        }
        var branches=AcceptancePanel("Branches");await AcceptanceClick(branches,"Load conversations");var chats=branches.Children.OfType<ComboBox>().Single();chats.SelectedItem=chats.Items.Cast<Option>().Single(c=>c.Id==parentId);await AcceptanceClick(branches,"Inspect selected conversation");var messages=branches.Children.OfType<ListBox>().Single();messages.SelectedItem=messages.Items.Cast<Option>().First(m=>m.Title.StartsWith("user:"));var branchName="QA native alternative "+Guid.NewGuid().ToString("N");AcceptanceField(branches,"New branch title").Text=branchName;await AcceptanceClick(branches,"Create independent branch");await AcceptanceClick(branches,"Load conversations");chats.SelectedItem=chats.Items.Cast<Option>().Single(c=>c.Title==branchName);await AcceptanceClick(branches,"Inspect selected conversation");Require(AcceptanceField(branches,"Immutable parent comparison").Text.Contains("Illustrative native QA original context"),"Immutable native comparison failed");
        var routines=AcceptancePanel("Routines");AcceptanceField(routines,"Routine title").Text="QA native time routine";await AcceptanceClick(routines,"Add step");await AcceptanceClick(routines,"Save routine");await AcceptanceClick(routines,"Refresh routines and runs");var definitions=routines.Children.OfType<ComboBox>().First();definitions.SelectedItem=definitions.Items.Cast<Option>().Single(c=>c.Title=="QA native time routine");await AcceptanceClick(routines,"Dry-run preview");Require(AcceptanceField(routines,"Preview and execution receipts").Text.Contains("time"),"Native dry-run preview missing");await AcceptanceClick(routines,"Run reviewed routine");
        JsonElement routineResult=default;for(int i=0;i<100;i++){routineResult=await api("routines/runs",null,null);if(routineResult.GetProperty("runs").EnumerateArray().Any(r=>Text(r,"status")=="completed"))break;await Task.Delay(100);}Require(routineResult.GetProperty("runs").EnumerateArray().Any(r=>Text(r,"status")=="completed"),"Native routine did not complete");
        var meetings=AcceptancePanel("Meetings");AcceptanceField(meetings,"Meeting title").Text="Consented native synthetic meeting";await AcceptanceClick(meetings,"Import consented audio");Require(status.Text.Contains("Confirm consent"),"Native meeting consent gate missing");var checks=meetings.Children.OfType<CheckBox>().ToArray();checks[0].IsChecked=true;Require(checks[1].IsChecked!=true,"Native audio retention must default off");await AcceptanceClick(meetings,"Import consented audio");
        JsonElement completed=default;for(int i=0;i<200;i++){var data=await api("meetings",null,null);completed=data.GetProperty("meetings").EnumerateArray().FirstOrDefault(m=>Text(m,"title")=="Consented native synthetic meeting");if(completed.ValueKind!=JsonValueKind.Undefined&&Text(completed,"status") is "completed" or "failed")break;await Task.Delay(100);}Require(completed.ValueKind!=JsonValueKind.Undefined&&Text(completed,"status")=="completed","Native real transcription failed");Require(!completed.GetProperty("audio_present").GetBoolean(),"Native service audio not removed after transcript persistence");await AcceptanceClick(meetings,"Refresh meeting jobs");var meetingList=meetings.Children.OfType<ComboBox>().Single();meetingList.SelectedItem=meetingList.Items.Cast<Option>().Single(c=>c.Id==Text(completed,"id"));await AcceptanceClick(meetings,"Load selected meeting");Require(AcceptanceField(meetings,"Timestamped transcript").Text.Contains("meeting",StringComparison.OrdinalIgnoreCase),"Native timestamped transcription missing");AcceptanceField(meetings,"Notes").Text="Reviewed native QA notes";await AcceptanceClick(meetings,"Save notes and proposals");var noteReadback=await api("meetings/"+Text(completed,"id"),null,null);Require(Text(noteReadback.GetProperty("notes"),"notes")=="Reviewed native QA notes","Native notes did not persist");
        var digests=AcceptancePanel("Digests");await AcceptanceClick(digests,"Load available sources");var sources=digests.Children.OfType<StackPanel>().Single();var selected=sources.Children.OfType<CheckBox>().Single(c=>c.Content.ToString()=="conversations: "+Text(parent,"title"));selected.IsChecked=true;await AcceptanceClick(digests,"Generate checked-source digest");Require(AcceptanceField(digests,"Saved digest").Text.Contains(parentId),"Native digest source link missing");await AcceptanceClick(digests,"Reload latest saved digest");Require(AcceptanceField(digests,"Saved digest").Text.Contains("Illustrative native QA original context"),"Native digest did not reload");
        var layouts=AcceptancePanel("Layouts");AcceptanceField(layouts,"Layout name").Text="QA native focus";layouts.Children.OfType<ComboBox>().First().SelectedItem="compact";await AcceptanceClick(layouts,"Save desktop layout");await AcceptanceClick(layouts,"Load desktop layouts");var layoutList=layouts.Children.OfType<ComboBox>().Last();layoutList.SelectedItem=layoutList.Items.Cast<Option>().Single(l=>l.Title=="QA native focus");await AcceptanceClick(layouts,"Restore selected layout");Require(status.Text.Contains("Drafts and permissions"),"Native layout restore failed");Require(!recording.IsRecording,"Layout restore must not enable recording");
        return new{passed=true,syntheticFixture=true,modelResponse="Controlled labeled fixture for branch context only; no live AI inference claim",checks=new[]{"native branch creation and immutable comparison","native dry-run and real time routine","native consent gate and real local transcription","native audio cleanup and notes readback","native selected-source digest and reload","native layout persistence and restore without recording"}};
    }
}
