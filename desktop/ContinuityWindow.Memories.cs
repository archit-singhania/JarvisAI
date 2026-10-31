using System.Net.Http;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Automation;
using Microsoft.Win32;

namespace JarvisAI;

public sealed partial class ContinuityWindow
{
    private StackPanel MemoryProvenance()
    {
        var p=Panel("Memory with provenance","Inspect origins and revisions. Expired memories are excluded from new retrieval; prior conversation messages remain in history.");
        var memories=new ComboBox{DisplayMemberPath="Title",Margin=new(0,6,0,14)};
        AutomationProperties.SetName(memories,"Saved memory");p.Children.Add(memories);
        string? editing=null;int version=0;JsonElement? source=null;
        var title=Field(p,"Memory title"),content=Field(p,"Memory content","",true);
        var scope=Choice(p,"Memory scope","workspace","conversation");
        var chats=new ComboBox{DisplayMemberPath="Title",Margin=new(0,6,0,14)};AutomationProperties.SetName(chats,"Scope and source conversation");p.Children.Add(chats);
        var expiry=Field(p,"Expiry · ISO timestamp with timezone, or blank",""),history=Field(p,"Source and revision history","",true);history.IsReadOnly=true;
        async Task Load(){var data=await api("memories",null,null);memories.ItemsSource=data.GetProperty("memories").EnumerateArray().Select(m=>new Option(Text(m,"id"),Text(m,"title"))).ToList();var conversations=await api("conversations",null,null);chats.ItemsSource=conversations.GetProperty("conversations").EnumerateArray().Select(c=>new Option(Text(c,"id"),Text(c,"title"))).ToList();}
        Button(p,"Load memories and conversations",Load);
        Button(p,"Inspect selected memory",async()=>{
            if(memories.SelectedItem is not Option selected)throw new InvalidOperationException("Select a saved memory.");
            var data=await api("memories/"+selected.Id,null,null);var m=data.GetProperty("memory");var meta=m.GetProperty("metadata");
            editing=selected.Id;version=meta.GetProperty("version").GetInt32();source=null;title.Text=Text(m,"title");content.Text=Text(m,"content");scope.SelectedItem=Text(meta,"scope");expiry.Text=Text(meta,"expires_at");
            chats.SelectedItem=chats.Items.Cast<Option>().FirstOrDefault(c=>c.Id==Text(meta,"conversation_id"));
            var original=data.GetProperty("source_message");
            history.Text=$"Origin: {Text(meta,"origin")} · revision {version}\nLast confirmed: {Text(meta,"last_confirmed_at")}\nSource status: {Text(data,"source_status")}\n"+(original.ValueKind==JsonValueKind.Object?Text(original,"content"):"No source message available.")+"\n\n"+string.Join("\n\n",data.GetProperty("revisions").EnumerateArray().Select(r=>$"Revision {Text(r,"version")} · {Text(r,"recorded_at")}\n{Text(r,"title")}\n{Text(r,"content")}"));
        });
        Button(p,"New explicit memory",()=>{editing=null;source=null;version=0;title.Clear();content.Clear();expiry.Clear();history.Text="Explicit user entry. Nothing is saved until Save memory is pressed.";scope.SelectedItem="workspace";return Task.CompletedTask;});
        var messages=new ListBox{DisplayMemberPath="Title",MaxHeight=160};AutomationProperties.SetName(messages,"Source message");p.Children.Add(messages);var sourceRows=new Dictionary<string,JsonElement>();
        Button(p,"Load source messages",async()=>{if(chats.SelectedItem is not Option selected)throw new InvalidOperationException("Select a conversation.");var data=await api("conversations/"+selected.Id,null,null);sourceRows.Clear();foreach(var m in data.GetProperty("messages").EnumerateArray())sourceRows[Text(m,"id")]=m.Clone();messages.ItemsSource=sourceRows.Values.Select(m=>new Option(Text(m,"id"),Text(m,"role")+": "+Text(m,"content"))).ToList();});
        Button(p,"Review selected message as new memory",()=>{if(messages.SelectedItem is not Option selected)throw new InvalidOperationException("Select a source message.");source=sourceRows[selected.Id];editing=null;version=0;content.Text=Text(source.Value,"content");title.Text=content.Text[..Math.Min(60,content.Text.Length)];history.Text="Selected source: "+content.Text+"\nReview the content, scope and expiry before saving.";return Task.CompletedTask;});
        Button(p,"Save memory",async()=>{
            var data=new Dictionary<string,object?>{{"title",title.Text},{"content",content.Text},{"scope",scope.SelectedItem?.ToString()},{"conversation_id",scope.SelectedItem?.ToString()=="conversation"?(chats.SelectedItem as Option)?.Id:null},{"expires_at",string.IsNullOrWhiteSpace(expiry.Text)?null:expiry.Text}};
            if(editing is not null)data["expected_version"]=version;
            else if(source is JsonElement chosen){if(!Confirm("Save this selected message as a memory? Assistant suggestions are not verified facts."))return;data["origin"]=Text(chosen,"role")=="assistant"?"approved_suggestion":"selected_conversation";data["source_conversation_id"]=Text(chosen,"conversation");data["source_message_id"]=chosen.GetProperty("id").GetInt32();data["confirmed"]=true;}
            var result=await api("memories"+(editing is null?"":"/"+editing),editing is null?HttpMethod.Post:HttpMethod.Patch,data);editing=Text(result,"id");version=result.GetProperty("version").GetInt32();source=null;status.Text="Memory saved · revision "+version;await Load();
        });
        Button(p,"Export memory provenance",async()=>{var save=new SaveFileDialog{Filter="JSON|*.json",FileName="memory-provenance.json"};if(save.ShowDialog(this)!=true)return;var data=await api("memories/export",null,null);await File.WriteAllTextAsync(save.FileName,JsonSerializer.Serialize(data,new JsonSerializerOptions{WriteIndented=true}));status.Text="Memory provenance exported.";});
        Button(p,"Delete selected memory and revisions",async()=>{if(memories.SelectedItem is not Option selected)throw new InvalidOperationException("Select a saved memory.");if(!Confirm("Delete this memory and its revision history? Existing conversation messages remain."))return;await api("records/"+selected.Id,HttpMethod.Delete,null);editing=null;source=null;title.Clear();content.Clear();history.Clear();await Load();status.Text="Memory deleted and excluded from future retrieval.";});
        return p;
    }
}
