using System.Net.Http;
using System.Text.Json;
using System.Windows.Controls;
using System.Windows.Automation;
using System.Windows.Automation.Peers;
using Microsoft.Win32;

namespace JarvisAI;

public sealed partial class ContinuityWindow
{
    private static readonly JsonSerializerOptions Pretty = new(){WriteIndented=true};
    private static void ShowJson(TextBox box,JsonElement data)=>box.Text=JsonSerializer.Serialize(data,Pretty);
    private static void SaveText(string name,string content)
    {
        var dialog=new SaveFileDialog{FileName=name};
        if(dialog.ShowDialog()==true)File.WriteAllText(dialog.FileName,content);
    }
    private StackPanel LocalEdits()
    {
        var p=Panel("Persist through disconnections","Load your workspace identity once, then save local operations. Synchronization never runs commands or sends external writes. Conflicts retain the submitted and current versions.");
        string? owner=null;string? path=null;
        var queueRoot=Path.Combine(Environment.GetEnvironmentVariable("WEDNESDAY_CLIENT_DATA")??Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Wednesday"),"offline");
        var identityPath=Path.Combine(queueRoot,"last-owner.txt");
        void SelectOwner(string value){if(!System.Text.RegularExpressions.Regex.IsMatch(value,"^[a-f0-9]{32}$"))throw new InvalidOperationException("Invalid identity");owner=value;path=Path.Combine(queueRoot,owner+".json");}
        if(File.Exists(identityPath)){try{SelectOwner(File.ReadAllText(identityPath));}catch{status.Text="Saved offline identity needs reconnection.";}}
        var kind=Choice(p,"Edit type","note","draft","memory","reminder");
        TextBox title=Field(p,"Title"),content=Field(p,"Content","",true),id=Field(p,"Record ID (blank for new note/draft/reminder)"),revision=Field(p,"Expected revision (memory: current version)","0"),due=Field(p,"Reminder date with UTC offset"),output=Field(p,"Local queue and results","",true);output.IsReadOnly=true;
        List<JsonElement> Read()=>path!=null&&File.Exists(path)?JsonSerializer.Deserialize<List<JsonElement>>(File.ReadAllText(path))??new():new();
        void Write(List<JsonElement> rows){if(path==null)throw new InvalidOperationException("Load identity first.");Directory.CreateDirectory(Path.GetDirectoryName(path)!);File.WriteAllText(path+".partial",JsonSerializer.Serialize(rows));File.Move(path+".partial",path,true);output.Text=JsonSerializer.Serialize(rows,Pretty);}
        Button(p,"Load identity and saved queue",async()=>{var session=await api("session",HttpMethod.Post,null);SelectOwner(Text(session,"owner_id"));Directory.CreateDirectory(queueRoot);File.WriteAllText(identityPath+".partial",owner);File.Move(identityPath+".partial",identityPath,true);output.Text=JsonSerializer.Serialize(Read(),Pretty);});
        output.Text=JsonSerializer.Serialize(Read(),Pretty);
        Button(p,"Save local operation",()=>{
            if(owner==null)throw new InvalidOperationException("Load identity once before going offline.");
            if(string.IsNullOrWhiteSpace(title.Text)||string.IsNullOrWhiteSpace(content.Text))throw new InvalidOperationException("Enter title and content.");
            if(kind.SelectedItem?.ToString()=="memory"&&string.IsNullOrWhiteSpace(id.Text))throw new InvalidOperationException("Select an existing memory ID.");
            var body=new{operation_id=Guid.NewGuid().ToString(),id=string.IsNullOrWhiteSpace(id.Text)?Guid.NewGuid().ToString():id.Text,kind=kind.SelectedItem?.ToString(),expected_revision=int.Parse(revision.Text),value=new{title=title.Text,content=content.Text,due_at=string.IsNullOrWhiteSpace(due.Text)?null:due.Text}};
            var rows=Read();if(rows.Count>=200)throw new InvalidOperationException("Export and clear completed queue entries first.");rows.Add(JsonSerializer.SerializeToElement(new{status="pending",body}));Write(rows);return Task.CompletedTask;
        });
        Button(p,"Synchronize safe local edits",async()=>{
            if(owner==null)throw new InvalidOperationException("Load identity first.");var current=await api("session",HttpMethod.Post,null);if(Text(current,"owner_id")!=owner)throw new InvalidOperationException("Workspace changed. Reload identity.");
            var rows=Read();for(int i=0;i<rows.Count;i++){
                if(Text(rows[i],"status") is "completed" or "conflicted")continue;
                var body=rows[i].GetProperty("body");
                try{var result=await api("expansion/offline",HttpMethod.Post,body);rows[i]=JsonSerializer.SerializeToElement(new{status=Text(result,"status"),body,result});Write(rows);}
                catch(Exception error){rows[i]=JsonSerializer.SerializeToElement(new{status="failed",body,error=error.Message});Write(rows);throw;}
            }
        });
        Button(p,"Export private queue for conflict review",()=>{SaveText("wednesday-local-edits.json",JsonSerializer.Serialize(Read(),Pretty));return Task.CompletedTask;});
        Button(p,"Remove completed entries",()=>{Write(Read().Where(r=>Text(r,"status")!="completed").ToList());return Task.CompletedTask;});
        return p;
    }
    private StackPanel CalendarPlanning()
    {
        var p=Panel("Review your time","Local calendar files and conflict-checked proposals. Import UTC/IANA timed events and all-day dates. Open-ended series report their planning coverage. Google requires a configured account and explicit calendar selection.");
        TextBox title=Field(p,"Block title"),start=Field(p,"Working-window start with UTC offset",DateTimeOffset.Now.ToString("O")),end=Field(p,"Working-window end with UTC offset",DateTimeOffset.Now.AddHours(8).ToString("O")),minutes=Field(p,"Duration in minutes","30"),output=Field(p,"Calendar and proposed changes","",true);output.IsReadOnly=true;string? proposal=null;
        Button(p,"Load calendar",async()=>ShowJson(output,await api("expansion/calendar",null,null)));
        Button(p,"Sign in with Google",async()=>{
            var result=await api("expansion/calendar/google/oauth/start",HttpMethod.Post,null);
            if(!Uri.TryCreate(Text(result,"url"),UriKind.Absolute,out var url) ||
               url.Scheme!=Uri.UriSchemeHttps || url.Host!="accounts.google.com")
                throw new InvalidOperationException("Invalid Google sign-in address.");
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(url.AbsoluteUri){UseShellExecute=true});
            status.Text="Finish signing in in your browser, then list your Google calendars here.";
        });
        var calendarId=Field(p,"Selected Google calendar ID");
        Button(p,"List configured Google calendars",async()=>ShowJson(output,await api("expansion/calendar/google",null,null)));
        Button(p,"Connect selected Google calendar",async()=>{if(Confirm("Use this configured account and calendar: "+calendarId.Text+"?"))ShowJson(output,await api("expansion/calendar/google/connect",HttpMethod.Post,new{calendar=calendarId.Text,confirmed=true}));});
        Button(p,"Synchronize Google calendar",async()=>ShowJson(output,await api("expansion/calendar/google/sync",HttpMethod.Post,null)));
        Button(p,"Disconnect Google calendar",async()=>ShowJson(output,await api("expansion/calendar/google",HttpMethod.Delete,null)));
        Button(p,"Approve Google event write",async()=>{if(proposal==null)throw new InvalidOperationException("Create and inspect a proposal first.");if(Confirm("Create the proposed event in the selected Google calendar? No guests will be invited."))ShowJson(output,await api("expansion/calendar/proposals/"+proposal+"/google",HttpMethod.Post,new{confirmed=true}));});
        Button(p,"Import calendar file",async()=>{var dialog=new OpenFileDialog{Filter="Calendar|*.ics"};if(dialog.ShowDialog()!=true)return;if(new FileInfo(dialog.FileName).Length>1000000)throw new InvalidOperationException("Calendar exceeds 1 MB");ShowJson(output,await api("expansion/calendar/import",HttpMethod.Post,new{text=File.ReadAllText(dialog.FileName)}));});
        Button(p,"Export calendar",async()=>SaveText("wednesday.ics",Text(await api("expansion/calendar/export",null,null),"text")));
        Button(p,"Propose free block",async()=>{var result=await api("expansion/calendar/proposals",HttpMethod.Post,new{title=title.Text,start=start.Text,end=end.Text,minutes=int.Parse(minutes.Text)});proposal=Text(result,"id");ShowJson(output,result);});
        Button(p,"Approve displayed proposal",async()=>{if(proposal==null)throw new InvalidOperationException("Create a proposal first");if(Confirm("Add the displayed block to the local calendar? No invitations will be sent."))ShowJson(output,await api("expansion/calendar/proposals/"+proposal+"/approve",HttpMethod.Post,new{confirmed=true}));});return p;
    }
    private StackPanel WatchedFolders()
    {
        var p=Panel("Approved document roots","The host must explicitly list approved roots in WEDNESDAY_WATCH_ROOTS. TXT, Markdown and PDF only; scans are bounded and never follow symlinks. Browser clients cannot select arbitrary folders.");
        TextBox root=Field(p,"Selected root"),exclusions=Field(p,"Excluded glob patterns, one per line","",true),id=Field(p,"Folder ID to stop"),output=Field(p,"Index status and per-file failures","",true);output.IsReadOnly=true;
        Button(p,"Choose directory",()=>{var dialog=new OpenFolderDialog();if(dialog.ShowDialog()==true)root.Text=dialog.FolderName;return Task.CompletedTask;});
        Button(p,"Approve indexing",async()=>{if(Confirm("Index supported files beneath "+root.Text+" for this workspace?"))ShowJson(output,await api("expansion/folders",HttpMethod.Post,new{root=root.Text,exclusions=Lines(exclusions.Text),confirmed=true}));});
        Button(p,"Refresh scan status",async()=>ShowJson(output,await api("expansion/folders",null,null)));
        Button(p,"Stop and remove indexed content",async()=>{if(Confirm("Remove this watched folder from retrieval? Original files remain."))ShowJson(output,await api("expansion/folders/"+Uri.EscapeDataString(id.Text),HttpMethod.Delete,null));});return p;
    }
    private StackPanel LocalEvaluations()
    {
        var p=Panel("Reproducible source checks","Explicitly redact queries before saving. Runs measure retrieval or Python syntax diagnostics and a synthetic cancellation probe. No commands, external writes or model calls.");
        var kind=Choice(p,"Evaluation check","retrieval","python_diagnostics");var expectError=Check(p,"Expect a Python syntax error");
        TextBox title=Field(p,"Case title"),query=Field(p,"Redacted query","",true),sources=Field(p,"Expected owned source IDs, one per line","",true),id=Field(p,"Case ID to run/delete"),output=Field(p,"Cases and measurements","",true);output.IsReadOnly=true;
        Button(p,"Load cases and results",async()=>ShowJson(output,await api("expansion/evaluations",null,null)));
        Button(p,"Save reviewed case",async()=>{if(Confirm("I reviewed and redacted this query for local evaluation storage."))ShowJson(output,await api("expansion/evaluations",HttpMethod.Post,new{title=title.Text,query=query.Text,kind=kind.SelectedItem?.ToString(),expect_error=expectError.IsChecked==true,expected_sources=Lines(sources.Text),confirmed=true}));});
        var suiteStatus = new TextBlock { TextWrapping = System.Windows.TextWrapping.Wrap };
        AutomationProperties.SetLiveSetting(suiteStatus, AutomationLiveSetting.Polite);
        void Announce(string message)
        {
            suiteStatus.Text = message;
            UIElementAutomationPeer.CreatePeerForElement(suiteStatus)?.RaiseAutomationEvent(AutomationEvents.LiveRegionChanged);
        }
        Button(p,"Run saved evaluation suite",async()=>{
            Announce("Running saved evaluations.");
            try
            {
                var report = await api("expansion/evaluations/run-suite",HttpMethod.Post,null);
                ShowJson(output,report);
                Announce($"Evaluation suite finished. {Text(report,"passed")} passed, {Text(report,"failed")} failed.");
            }
            catch (Exception error)
            {
                Announce($"Evaluation suite failed. {error.Message}");
                throw;
            }
        });
        p.Children.Add(suiteStatus);
        Button(p,"Run read-only case",async()=>ShowJson(output,await api("expansion/evaluations/"+Uri.EscapeDataString(id.Text)+"/run",HttpMethod.Post,null)));
        Button(p,"Export displayed results",()=>{SaveText("wednesday-evaluation.json",output.Text);return Task.CompletedTask;});
        Button(p,"Delete case and results",async()=>{if(Confirm("Delete this case and its recorded runs?"))ShowJson(output,await api("expansion/evaluations/"+Uri.EscapeDataString(id.Text),HttpMethod.Delete,null));});return p;
    }
}
