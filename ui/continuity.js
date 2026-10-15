'use strict';
// Loaded after app.js: functions run only after a deliberate navigation action.
async function renderContinuity(panel,current){
  const [chats,reminders,receipts,saved,digests]=await Promise.all([
    api('conversations'),api('reminders'),api('receipts'),api('continuity/layouts/browser'),api('continuity/digests')]);
  if(!current())return;
  panel.replaceChildren(intro('A clear thread through your work.','Explore independent conversation branches, choose sources for a private digest, and restore a focused layout. Layouts never start recording or execute tools.'));
  const branchSection=element('section','card');branchSection.append(element('h2','','Conversation branches'));
  const select=field('Conversation','branchConversation','text',state.conversation||'',chats.conversations.map(c=>[c.id,c.title]));
  const history=element('div','continuity-list');branchSection.append(select,history);
  const load=async()=>{
    const id=select.querySelector('select').value;if(!id){history.replaceChildren(empty('Create a conversation to explore a branch.'));return;}
    const [chat,links]=await Promise.all([api('conversations/'+id),api('continuity/conversations/'+id+'/branches')]);
    history.replaceChildren();
    if(links.parent){
      const disclosure=element('details');disclosure.append(element('summary','','Compare with immutable parent context'));
      const comparison=element('div','continuity-comparison');
      const parent=element('div'),child=element('div');parent.append(element('h3','','Original context'));child.append(element('h3','','Current branch'));
      links.parent.snapshot.forEach(m=>parent.append(card(m.role,m.content)));
      chat.messages.forEach(m=>child.append(card(m.role,m.content)));
      comparison.append(parent,child);disclosure.append(comparison);history.append(disclosure);
      history.append(element('small','','Parent '+links.parent.parent+' · through message '+links.parent.message_id));
    }
    links.children.forEach(c=>history.append(button('Open branch '+c.conversation.slice(0,8),async()=>{select.querySelector('select').value=c.conversation;await load();})));
    chat.messages.forEach(m=>history.append(card(m.role,m.content,null,[button('Branch from this message',()=>editDialog('Independent branch',[field('Branch title','title','text','Alternative direction')],async body=>{
      const branch=await api('continuity/conversations/'+id+'/branches',json('POST',{message_id:m.id,title:body.title}));state.conversation=branch.id;connect();toast('Branch saved. Parent history is unchanged.');
    }))])));
    if(!chat.messages.length)history.append(empty('Messages will appear here after your first conversation.'));
  };
  select.querySelector('select').onchange=()=>load().catch(e=>toast(e.message,true));await load();panel.append(branchSection);
  const digest=element('section','card');digest.append(element('h2','','A digest you control'),element('p','','Only checked sources enter the saved digest. It uses factual excerpts, with partial coverage shown.'));
  const chosen={conversation_ids:new Set(),reminder_ids:new Set(),receipt_ids:new Set()};
  const group=(label,key,rows,title)=>{const details=element('details');details.append(element('summary','',label));rows.forEach(r=>{const line=element('label','check-field');const check=element('input');check.type='checkbox';check.onchange=()=>check.checked?chosen[key].add(r.id):chosen[key].delete(r.id);line.append(check,document.createTextNode(title(r)));details.append(line);});if(!rows.length)details.append(empty('No sources yet.'));digest.append(details);};
  group('Conversations','conversation_ids',chats.conversations,r=>r.title);group('Reminders','reminder_ids',reminders.reminders,r=>r.text);group('Approved tool receipts','receipt_ids',receipts.receipts,r=>r.tool+' · '+r.created_at);
  const since=field('Include items since','digestSince','date',new Date(Date.now()-7*86400000).toISOString().slice(0,10));digest.append(since);
  digest.append(button('Generate selected digest',async()=>{
    const date=since.querySelector('input').value;if(!date)throw new Error('Choose a start date.');
    await api('continuity/digests',json('POST',{...Object.fromEntries(Object.entries(chosen).map(([k,v])=>[k,[...v]])),since:date+'T00:00:00Z'}));await showView('continuity');
  },'primary'));
  digests.digests.forEach(d=>{const details=element('details');details.append(element('summary','',new Date(d.created_at).toLocaleString()+' · '+d.items.length+' excerpts'),element('p','',d.coverage));d.items.forEach(i=>details.append(card(i.title,i.text,i.kind+' · '+i.source_id,[button('Inspect source',async()=>{
    if(i.kind==='conversation'){state.conversation=i.source_id;await showView('chat');connect();}
    else await showView(i.kind==='reminder'?'reminders':'tools');
  })])));digest.append(details);});panel.append(digest);
  const layouts=element('section','card');layouts.append(element('h2','','Task-aware layouts'),element('p','','Browser settings are stored separately from desktop clients. Applying a layout preserves the composer draft.'));
  const values=()=>({version:1,view:'chat',rail:document.body.dataset.rail||'expanded',density:document.body.dataset.density||'comfortable',context_ids:state.conversation?[state.conversation]:[]});
  layouts.append(button('Save current layout',()=>editDialog('Save browser layout',[field('Name','title','text','Focus')],body=>api('continuity/layouts/browser',json('POST',{title:body.title,value:values()}))),'primary'));
  for(const [title,rail,density] of [['Meeting','expanded','comfortable'],['Writing','compact','comfortable'],['Research','expanded','comfortable'],['Focus','compact','focused']]){
    layouts.append(button('Save '+title+' preset',async()=>{await api('continuity/layouts/browser',json('POST',{title,value:{...values(),rail,density}}));await showView('continuity');}));
  }
  saved.layouts.forEach(l=>layouts.append(card(l.title,'Browser · revision '+l.revision,null,[button('Restore layout',async()=>{
    document.body.dataset.rail=l.value.rail;document.body.dataset.density=l.value.density;
    // Context stays selected metadata: no automatic microphone, provider, or tool action.
    sessionStorage.setItem('wednesday-layout-'+state.owner,JSON.stringify(l.value));
    await showView(l.value.view);toast('Layout restored. Your draft is preserved.');
  })])));panel.append(layouts);
  await renderRoutines(panel);
  await renderMeetings(panel);
}
