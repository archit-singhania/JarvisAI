/* Owned memory controls; no automatic memory creation. Uses the shared API and dialogs. */
const memoryOrigins={explicit_user:'Explicit user entry',selected_conversation:'Selected conversation',approved_suggestion:'Approved suggestion',source_unavailable:'Source unavailable'};
function exportMemory(value){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='memory-provenance.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function memoryDialog(title){const d=element('dialog','memory-inspector');d.setAttribute('aria-label',title);d.append(intro(title,'You control what is saved and used.'));d.addEventListener('close',()=>d.remove());document.body.append(d);d.showModal();return d;}
async function inspectMemory(id){
  const data=await api('memories/'+id),m=data.memory,p=m.metadata,d=memoryDialog('Memory source and history');
  d.append(card(m.title,m.content,`${memoryOrigins[p.origin]} · ${p.scope} · v${p.version}`));
  d.append(element('p','',`Last confirmed: ${p.last_confirmed_at||'Unknown'} · Expiry: ${p.expires_at||'None'}`));
  d.append(data.source_message?card('Selected source',data.source_message.content,`${data.source_message.role} · SHA-256 ${p.source.sha256}`):empty(p.source?'Original source is unavailable; its reference and hash remain.':'No conversation source is attached.'));
  d.append(element('p','','A source supplied as context does not prove it determined an answer. Corrections preserve original provenance.'));
  data.revisions.forEach(r=>d.append(card('Revision '+r.version,r.content,`${r.title} · ${r.recorded_at}`)));
  d.append(button('Export memory history',()=>exportMemory(data)),button('Close history',()=>d.close(),'primary'));
}
async function editMemory(m=null,source=null){
  const {conversations}=await api('conversations');
  const scopes=[['workspace','Workspace'],...conversations.map(c=>[c.id,'Conversation: '+c.title])];
  if(m?.metadata.scope==='conversation'&&!conversations.some(c=>c.id===m.metadata.conversation_id))scopes.push([m.metadata.conversation_id,'Original conversation unavailable']);
  const expiry=m?.metadata.expires_at?new Date(m.metadata.expires_at):null;
  const local=expiry?new Date(expiry.getTime()-expiry.getTimezoneOffset()*60000).toISOString().slice(0,16):'';
  editDialog(m?'Correct memory':source?'Review selected source before saving':'A new memory',[
    field('Title','title','text',m?.title||source?.content.slice(0,60)||''),field('What should Wednesday remember?','content','textarea',m?.content||source?.content||''),
    field('Use in','scope_choice','text',m?.metadata.scope==='conversation'?m.metadata.conversation_id:'workspace',scopes),field('Expiry in local timezone · optional','expiry','datetime-local',local),
  ],body=>{
    const payload={title:body.title,content:body.content,scope:body.scope_choice==='workspace'?'workspace':'conversation',conversation_id:body.scope_choice==='workspace'?null:body.scope_choice,expires_at:body.expiry?new Date(body.expiry).toISOString():null};
    if(m)payload.expected_version=m.metadata.version;
    if(source)Object.assign(payload,{origin:source.role==='assistant'?'approved_suggestion':'selected_conversation',source_conversation_id:source.conversation,source_message_id:source.id,confirmed:true});
    return api('memories'+(m?'/'+m.id:''),json(m?'PATCH':'POST',payload));
  });
}
async function selectMemorySource(){
  const {conversations}=await api('conversations');if(!conversations.length){toast('Start a conversation before selecting a source.');return;}
  const d=memoryDialog('Select memory source'),choice=field('Source conversation','source','text',conversations[0].id,conversations.map(c=>[c.id,c.title])),messages=element('div');
  async function load(){messages.replaceChildren(empty('Loading messages…'));try{const id=choice.querySelector('select').value;const data=await api('conversations/'+id);if(choice.querySelector('select').value!==id)return;messages.replaceChildren();data.messages.forEach(m=>messages.append(card(m.role,m.content,'Review and save explicitly to create a memory.',[button('Use this message',async()=>{d.close();await editMemory(null,{...m,conversation:id});})])));if(!data.messages.length)messages.append(empty('No saved messages.'));}catch(error){messages.replaceChildren(empty(error.message));}}
  choice.querySelector('select').onchange=load;d.append(choice,messages,button('Cancel selection',()=>d.close()));await load();
}
async function renderMemories(panel,isCurrent){
  const {memories}=await api('memories');if(!isCurrent())return;
  panel.replaceChildren(intro('Remember with context.','Inspect origins, correct saved facts and limit where memories are used. Expired memories are excluded from new retrieval.'));
  const bar=element('div','panel-toolbar');bar.append(button('＋ Add memory',()=>editMemory(),'primary'),button('From conversation',selectMemorySource),button('Export memories',async()=>exportMemory(await api('memories/export'))));panel.append(bar);
  const grid=element('div','card-grid');memories.forEach(m=>{const p=m.metadata,expired=p.expires_at&&new Date(p.expires_at)<=new Date();grid.append(card(m.title,m.content,`${memoryOrigins[p.origin]} · v${p.version} · ${p.scope}${expired?' · Expired':''}`,[button('Edit',()=>editMemory(m)),button('Source and history',()=>inspectMemory(m.id)),button('Remove',async()=>{await api('records/'+m.id,{method:'DELETE'});await showView('memory');})]));});panel.append(memories.length?grid:empty('No memories saved yet.'));
}
