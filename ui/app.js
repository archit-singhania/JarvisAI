'use strict';
const $ = id => document.getElementById(id);
const state = {owner:null, conversation:null, socket:null, preferences:{}, view:'chat', message:null, turn:null, blocked:new Set(), reconnect:null, recording:null, acquiring:false, audio:null, queue:[], objectUrl:null};
const titles = {chat:'Assistant',knowledge:'Knowledge',memory:'Memory',reminders:'Reminders',tools:'Tools & workflows',settings:'Preferences'};
let toastTimer,viewRequest=0,lastProgress=0;
const motion=window.WednesdayMotion;
function toast(message,error=false){$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;motion.enter($('toast'));clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6500);}
async function api(path,options={}){
  const response=await fetch('/api/'+path,{credentials:'same-origin',...options,headers:{'X-Requested-With':'Wednesday',...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...options.headers}});
  let data;try{data=await response.json();}catch{throw new Error('The service returned an unreadable response.');}
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'The request could not be completed.');
  return data;
}
const json=(method,body)=>({method,body:JSON.stringify(body)});
function element(tag,className,text){const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;}
function button(text,action,className='quiet'){const node=element('button',className,text);node.type='button';node.addEventListener('click',()=>Promise.resolve(action()).catch(error=>toast(error.message,true)));return node;}
function applyPreferences(){
  const p=state.preferences;document.documentElement.dataset.palette=p.palette||'amethyst';document.documentElement.dataset.theme=p.theme==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):p.theme||'dark';
  document.documentElement.dataset.reduceMotion=String(!!p.reduce_motion);document.documentElement.dataset.reduceTransparency=String(!!p.reduce_transparency);document.documentElement.dataset.highContrast=String(!!p.high_contrast);$('focus').value=p.focus||'assistant';
}
async function savePreferences(patch){state.preferences=await api('preferences',json('PATCH',patch));applyPreferences();}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{if(state.preferences.theme==='system')applyPreferences();});
function setActivity(label,phase='idle'){$('activity-label').textContent=label;$('orb-label').textContent=label;document.body.dataset.state=phase;$('stop').hidden=phase==='idle';$('composer').setAttribute('aria-busy',String(phase==='thinking'));$('mic').setAttribute('aria-pressed',String(phase==='listening'));motion.pulse(document.querySelector('.activity-orb'));motion.pulse(document.querySelector('.orb'));}
function stopAudio(){state.queue=[];if(state.audio){state.audio.pause();state.audio=null;}if(state.objectUrl){URL.revokeObjectURL(state.objectUrl);state.objectUrl=null;}}
function playAudio(){
  if(state.audio||!state.queue.length)return;
  const chunk=state.queue.shift();if(state.blocked.has(chunk.turn_id)){playAudio();return;}
  const bytes=Uint8Array.from(atob(chunk.audio_b64),x=>x.charCodeAt(0));
  state.objectUrl=URL.createObjectURL(new Blob([bytes],{type:chunk.audio_format==='wav'?'audio/wav':'audio/mpeg'}));
  const audio=new Audio(state.objectUrl);state.audio=audio;
  const done=()=>{if(state.audio!==audio)return;URL.revokeObjectURL(state.objectUrl);state.objectUrl=null;state.audio=null;playAudio();};
  audio.onended=done;audio.onerror=()=>{toast('This audio format could not be played.',true);done();};
  audio.play().catch(()=>{toast('Enable audio playback by interacting with the page.',true);done();});
}
function addMessage(role,content,sources=[],animate=true){
  $('welcome').hidden=true;$('messages').classList.add('has-messages');
  const row=element('article','message '+role);row.append(element('div','message-meta',role==='assistant'?'◉ Wednesday':'You'));
  const body=element('div','message-content',content);row.append(body);
  if(sources.length){const list=element('div','sources');sources.forEach((source,i)=>list.append(element('span','source',`[${i+1}] ${source.title}`)));row.append(list);}
  $('messages').append(row);if(animate)motion.enter(row);$('messages').scrollTop=$('messages').scrollHeight;return body;
}
function dispatch(data){
  if(data.type==='session'){
    state.conversation=data.conversation_id;localStorage.setItem('wednesday-conversation-'+state.owner,state.conversation);$('messages').replaceChildren();
    $('messages').classList.toggle('has-messages',!!data.history?.length);$('welcome').hidden=!!data.history?.length;
    (data.history||[]).forEach(m=>addMessage(m.role,m.content,m.sources,false));state.message=null;refreshHistory();return;
  }
  if(data.type==='stream_start'){state.turn=data.turn_id;stopAudio();state.message=addMessage('assistant','',data.sources);setActivity('Thinking through your request…','thinking');}
  if(data.turn_id&&state.blocked.has(data.turn_id)&&!['interrupted','cleared'].includes(data.type))return;
  switch(data.type){
    case 'stream_chunk':if(performance.now()-lastProgress>350){lastProgress=performance.now();motion.pulse(document.querySelector('.activity-orb'));}if(state.message)state.message.textContent+=data.content||'';$('messages').scrollTop=$('messages').scrollHeight;break;
    case 'stream_end':setActivity('Ready when you are');state.message=null;refreshHistory();break;
    case 'audio_chunk':state.queue.push(data);playAudio();break;
    case 'response':addMessage('assistant',data.content);setActivity('Ready when you are');break;
    case 'transcript':addMessage('user',data.content);break;
    case 'stt_start':setActivity('Transcribing your voice…','thinking');break;
    case 'error':case 'stt_error':case 'speech_unavailable':if(state.message&&!state.message.textContent){state.message.textContent=data.content;state.message.classList.add('operation-error');}toast(data.content,true);setActivity('Check your engine in Preferences');break;
    case 'interrupted':stopAudio();state.message=null;setActivity('Response interrupted');break;
    case 'cleared':state.conversation=data.conversation_id;localStorage.setItem('wednesday-conversation-'+state.owner,state.conversation);$('messages').replaceChildren();$('messages').classList.remove('has-messages');$('welcome').hidden=false;refreshHistory();break;
    case 'reminder':toast(data.content);send({type:'reminder_ack',reminder_id:data.reminder_id});if(state.view==='reminders')showView('reminders');break;
    case 'wake_detected':if(!state.recording)toggleRecording().catch(error=>toast(error.message,true));break;
  }
}
function connect(){
  clearTimeout(state.reconnect);if(state.socket){state.socket.onclose=null;state.socket.close();}
  const url=new URL('/ws',location.href);url.protocol=location.protocol==='https:'?'wss:':'ws:';if(state.conversation)url.searchParams.set('conversation_id',state.conversation);
  const ws=new WebSocket(url);state.socket=ws;
  ws.onopen=()=>{$('connection-dot').classList.add('online');$('connection-label').textContent='Workspace connected';};
  ws.onmessage=event=>{try{dispatch(JSON.parse(event.data));}catch{toast('An invalid service event was received.',true);}};
  ws.onclose=()=>{$('connection-dot').classList.remove('online');$('connection-label').textContent='Reconnecting…';setActivity('Connection interrupted. Your saved work is safe.');stopAudio();state.reconnect=setTimeout(connect,3000);};
}
function send(payload){if(state.socket?.readyState!==WebSocket.OPEN){toast('Wait for the workspace to reconnect.',true);return false;}state.socket.send(JSON.stringify(payload));return true;}
async function refreshHistory(){
  try{const {conversations}=await api('conversations?q='+encodeURIComponent($('history-search').value));$('history-list').replaceChildren();conversations.forEach(c=>{$('history-list').append(button(c.title,()=>{state.conversation=c.id;showView('chat');connect();},'history-item'+(c.id===state.conversation?' selected':'')));});}catch(error){toast(error.message,true);}
}
async function newConversation(){await interrupt();const conversation=await api('conversations',json('POST',{mode:state.preferences.focus||'assistant'}));state.conversation=conversation.id;showView('chat');connect();}
async function interrupt(){if(state.acquiring)state.acquiring=false;if(state.recording){state.recording.cancelled=true;if(state.recording.recorder.state==='recording')state.recording.recorder.stop();}if(state.turn)state.blocked.add(state.turn);stopAudio();send({type:'interrupt'});setActivity('Ready when you are');}
function intro(title,description){const node=element('div','panel-intro');node.append(element('h2','',title),element('p','',description));return node;}
function empty(text){return element('div','empty',text);}
function card(title,content,detail,actions=[]){const node=element('article','card');node.append(element('h3','',title),element('p','',content));if(detail)node.append(element('small','',detail));const toolbar=element('div','card-actions');actions.forEach(b=>toolbar.append(b));node.append(toolbar);return node;}
function field(label,name,type='text',value='',options=null){const container=element('label','field',label);const control=element(options?'select':type==='textarea'?'textarea':'input');control.name=name;control.id='field-'+name;if(!options&&type!=='textarea')control.type=type;
  if(options)options.forEach(([v,t])=>{const option=element('option','',t);option.value=v;control.append(option);});control.value=value;container.append(control);return container;
}
function editDialog(title,fields,submit){
  $('dialog-title').textContent=title;$('dialog-fields').replaceChildren(...fields);$('editor-form').onsubmit=async event=>{event.preventDefault();const save=event.submitter;save.disabled=true;try{await submit(Object.fromEntries(new FormData(event.currentTarget)));await motion.close($('editor-dialog'));await showView(state.view);}catch(error){toast(error.message,true);}finally{save.disabled=false;}};$('editor-dialog').showModal();motion.enter($('editor-dialog'));
}
async function showView(view){
  const request=++viewRequest;state.view=view;$('view-title').textContent=titles[view];document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===view));$('chat-view').hidden=view!=='chat';$('panel-view').hidden=view==='chat';document.querySelectorAll('.nav').forEach(n=>n.setAttribute('aria-current',n.dataset.view===view?'page':'false'));if(view==='chat'){motion.enter($('chat-view'));return;}
  const panel=$('panel-view');panel.replaceChildren(empty('Loading your workspace…'));panel.setAttribute('aria-busy','true');motion.enter(panel);
  try{
    if(view==='knowledge'){
      const {documents}=await api('documents');if(request!==viewRequest)return;panel.replaceChildren(intro('Keep your context close.','Bring in documents, notes, and source files. Wednesday retrieves matching excerpts locally and shows the sources used in each answer.'));
      panel.append(button('＋ Import document',()=>$('document-input').click(),'primary'));
      const grid=element('div','card-grid');grid.style.marginTop='22px';documents.forEach(d=>grid.append(card(d.title,'Available for source retrieval.',`${d.metadata.bytes.toLocaleString()} bytes · Local lexical retrieval`,[button('Remove',async()=>{await api('records/'+d.id,{method:'DELETE'});showView(view);})])));panel.append(documents.length?grid:empty('Your knowledge library is empty. Import a PDF, Markdown, text, or source file to begin.'));
    }else if(view==='memory'){
      const {memories}=await api('memories');if(request!==viewRequest)return;panel.replaceChildren(intro('Remember what matters.','Save useful preferences and facts. You control what is remembered, edited, and removed.'));
      const editor=m=>editDialog(m?'Edit memory':'A new memory',[field('Title','title','text',m?.title||''),field('What should Wednesday remember?','content','textarea',m?.content||'')],body=>api('memories'+(m?'/'+m.id:''),json(m?'PATCH':'POST',body)));
      panel.append(button('＋ Add memory',()=>editor(),'primary'));const grid=element('div','card-grid');grid.style.marginTop='22px';memories.forEach(m=>grid.append(card(m.title,m.content,null,[button('Edit',()=>editor(m)),button('Remove',async()=>{await api('records/'+m.id,{method:'DELETE'});showView(view);})])));panel.append(memories.length?grid:empty('No memories saved yet.'));
    }else if(view==='reminders'){
      const {reminders}=await api('reminders');if(request!==viewRequest)return;panel.replaceChildren(intro('Make room for the important things.','Reminders persist across restarts. Due reminders are delivered when your workspace is connected.'));
      panel.append(button('＋ Schedule reminder',()=>editDialog('Schedule a reminder',[field('Reminder','text'),field('Date and time in the timezone below','local_time','datetime-local'),field('Timezone','timezone','text',state.preferences.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone)],body=>{if(!body.local_time)throw new Error('Choose a valid date and time.');return api('reminders',json('POST',{text:body.text,due_at:body.local_time,timezone:body.timezone}));}),'primary'));
      const grid=element('div','card-grid');grid.style.marginTop='22px';reminders.forEach(r=>grid.append(card(r.text,new Date(r.due_at).toLocaleString(),r.status+' · '+r.timezone,r.status==='scheduled'?[button('Cancel',async()=>{await api('reminders/'+r.id,{method:'DELETE'});showView(view);})]:[])));panel.append(reminders.length?grid:empty('No reminders scheduled.'));
    }else if(view==='tools'){
      const [receipts,workflows]=await Promise.all([api('receipts'),api('workflows')]);if(request!==viewRequest)return;panel.replaceChildren(intro('Useful actions. Clear boundaries.','Run a tool deliberately, inspect its receipt, or save a repeatable sequence. Host actions always require individual confirmation.'));
      const controls=element('div','panel-toolbar');
      controls.append(button('Run a tool',()=>editDialog('Run a tool',[field('Tool','tool','text','time',[['time','Current time'],['weather','Weather'],['search','Web search'],['open_app','Open a local app']]),field('Query or app name','argument')],async body=>{const confirmed=body.tool!=='open_app'||confirm('Launch '+body.argument+' on this device?');if(!confirmed)return;const result=await api('tools/execute',json('POST',{...body,confirmed}));toast(result.content,!result.success);})));
      controls.append(button('＋ Save workflow',()=>editDialog('Reusable workflow',[field('Name','title'),field('One step per line: time, weather, or search: query','steps','textarea','time\nweather')],body=>{const steps=body.steps.split('\n').filter(Boolean).map(line=>{const [tool,...rest]=line.split(':');if(!['time','weather','search'].includes(tool.trim()))throw new Error('Workflows support time, weather, and search.');return {tool:tool.trim(),argument:rest.join(':').trim()};});return api('workflows',json('POST',{title:body.title,steps}));}),'primary'));panel.append(controls);
      const grid=element('div','card-grid');workflows.workflows.forEach(w=>grid.append(card(w.title,'Saved sequence · '+JSON.parse(w.content).length+' steps',null,[button('Run workflow',async()=>{const result=await api('workflows/'+w.id+'/run',{method:'POST'});toast(result.results.map(r=>r.content).join(' · '));showView(view);}),button('Remove',async()=>{await api('records/'+w.id,{method:'DELETE'});showView(view);})])));panel.append(grid);
      panel.append(intro('Execution receipts','Results recorded by the service, including unavailable tools.'));const receiptsGrid=element('div','card-grid');receipts.receipts.forEach(r=>receiptsGrid.append(card(r.tool,r.result.content,new Date(r.created_at).toLocaleString())));panel.append(receipts.receipts.length?receiptsGrid:empty('Run your first tool to create an execution receipt.'));
    }else if(view==='settings'){
      const caps=await api('capabilities');if(request!==viewRequest)return;const p=state.preferences;panel.replaceChildren(intro('Make it feel like yours.','Choose an engine, a focus, and an appearance. Cloud providers require backend API keys; local inference requires a running Ollama model.'));
      const form=element('form','settings-form card');const grid=element('div','settings-grid');
      grid.append(field('Appearance','theme','text',p.theme,[['system','System'],['light','Pearl'],['dark','Graphite']]),field('Signature palette','palette','text',p.palette||'amethyst',[['amethyst','Amethyst · violet / platinum'],['lagoon','Lagoon · mineral / sea glass'],['ember','Ember · copper / warm pearl']]),field('Default focus','focus','text',p.focus,[['assistant','Assistant'],['coding','Coding'],['research','Research'],['focus','Focus']]),field('Model provider','llm_provider','text',p.llm_provider,[['ollama','Ollama · local'],['groq','Groq'],['openai','OpenAI'],['gemini','Gemini']]),field('Local model name','ollama_model','text',p.ollama_model),field('Cloud model name','llm_model','text',p.llm_model),field('Reminder timezone · IANA name','timezone','text',p.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone),field('Speech language code','language','text',p.language),field('Response style · optional','persona','textarea',p.persona||''));form.append(grid);
      [['reduce_motion','Reduce motion'],['reduce_transparency','Reduce transparency'],['high_contrast','High contrast'],['tts','Speak responses using configured server speech']].forEach(([name,label])=>{const line=element('label','check-field');const input=element('input');input.type='checkbox';input.name=name;input.checked=!!p[name];line.append(input,document.createTextNode(label));form.append(line);});
      const save=element('button','primary','Save preferences');save.type='submit';form.append(save);form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{const data=Object.fromEntries(new FormData(form));['reduce_motion','reduce_transparency','high_contrast','tts'].forEach(k=>data[k]=form.elements[k].checked);await savePreferences(data);toast('Preferences saved.');}catch(error){toast(error.message,true);}finally{save.disabled=false;}};panel.append(form);
      const status=element('div','card status-list');status.style.marginTop='18px';status.append(element('h3','','Engine availability'));Object.entries(caps.llm).forEach(([name,engine])=>{const row=element('div','status-row');row.append(element('strong','',name),element('span',engine.available?'available':'',engine.available?'Configured':'Unavailable'));status.append(row);if(engine.detail)status.append(element('p','',engine.detail));});status.append(element('p','',`Server speech: ${caps.speech.provider} · Retrieval: ${caps.retrieval}`));status.append(button('Start local wake-word listener',async()=>{const result=await api('wake-word/start',{method:'POST'});toast(result.detail);}));status.append(button('Stop wake-word listener',()=>api('wake-word/stop',{method:'POST'})));panel.append(status);
    }
  }catch(error){if(request===viewRequest){panel.replaceChildren(empty(error.message));toast(error.message,true);}}finally{if(request===viewRequest){panel.setAttribute('aria-busy','false');motion.enter(panel);}}
}
async function toggleRecording(){
  if(state.acquiring){state.acquiring=false;setActivity('Microphone request cancelled');return;}
  if(state.recording){if(state.recording.recorder.state==='recording')state.recording.recorder.stop();return;}
  if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined')throw new Error('Voice recording requires a supported browser on HTTPS or localhost.');
  await interrupt();if(state.acquiring)return;state.acquiring=true;setActivity('Waiting for microphone permission…','listening');let stream;try{stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,channelCount:1}});}catch(error){state.acquiring=false;setActivity('Microphone permission was not granted');throw error;}
  if(!state.acquiring){stream.getTracks().forEach(track=>track.stop());return;}state.acquiring=false;
  const supported=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(type=>MediaRecorder.isTypeSupported(type));
  const recorder=new MediaRecorder(stream,supported?{mimeType:supported}:undefined),chunks=[];
  const context=new (window.AudioContext||window.webkitAudioContext)(),analyser=context.createAnalyser();context.createMediaStreamSource(stream).connect(analyser);analyser.fftSize=512;
  const recording={recorder,stream,context,cancelled:false};state.recording=recording;$('mic').textContent='■';$('mic').setAttribute('aria-label','Stop and send voice recording');setActivity('Listening… speak naturally','listening');
  recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
  const samples=new Float32Array(analyser.fftSize);let spoken=false,silence=0;const started=performance.now();
  const meter=setInterval(()=>{analyser.getFloatTimeDomainData(samples);const rms=Math.sqrt(samples.reduce((s,x)=>s+x*x,0)/samples.length);document.querySelector('.orb').style.transform=motion.reduced()?'':`scale(${1+Math.min(rms*2,.12)})`;if(rms>.025){spoken=true;silence=0;}else if(spoken)silence+=100;if(silence>=1600||performance.now()-started>45000)if(recorder.state==='recording')recorder.stop();},100);
  recorder.onstop=async()=>{clearInterval(meter);stream.getTracks().forEach(track=>track.stop());await context.close();state.recording=null;$('mic').textContent='♩';$('mic').setAttribute('aria-label','Record voice message');document.querySelector('.orb').style.transform='';
    if(recording.cancelled){setActivity('Ready when you are');return;}const blob=new Blob(chunks,{type:recorder.mimeType});if(blob.size<500){setActivity('Recording was too short');return;}const reader=new FileReader();reader.onload=()=>send({type:'audio',audio_b64:reader.result.split(',')[1],language:state.preferences.language||'en',tts:!!state.preferences.tts});reader.readAsDataURL(blob);setActivity('Processing your voice…','thinking');};recorder.start();
}
async function uploadDocument(file){if(!file)return;const body=new FormData();body.append('file',file);$('attachment-note').hidden=false;$('attachment-note').textContent='Importing '+file.name+'…';try{const result=await api('documents',{method:'POST',body});toast(result.title+' added to your knowledge.');if(state.view==='knowledge')showView('knowledge');}finally{$('attachment-note').hidden=true;$('document-input').value='';}}
async function uploadImage(file){if(!file)return;if(file.size>8*1024*1024)throw new Error('Select an image smaller than 8 MB.');await interrupt();const reader=new FileReader();reader.onload=()=>{if(send({type:'screen',image_b64:reader.result.split(',')[1],prompt:$('prompt').value||'Describe this selected image and help me understand it.'})){addMessage('user','Selected image: '+file.name);setActivity('Inspecting the selected image…','thinking');}};reader.readAsDataURL(file);$('screen-input').value='';}
$('composer').addEventListener('submit',event=>{event.preventDefault();const text=$('prompt').value.trim();if(!text)return;if(send({type:'text',content:text,tts:!!state.preferences.tts})){stopAudio();addMessage('user',text);$('prompt').value='';setActivity('Starting your turn…','thinking');}});
$('prompt').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('composer').requestSubmit();}});
$('prompt').addEventListener('input',()=>{$('prompt').style.height='auto';$('prompt').style.height=Math.min($('prompt').scrollHeight,180)+'px';});
document.querySelectorAll('[data-view]').forEach(node=>node.addEventListener('click',()=>showView(node.dataset.view)));
document.querySelectorAll('[data-prompt]').forEach(node=>node.addEventListener('click',()=>{$('prompt').value=node.dataset.prompt;$('prompt').focus();}));
$('new-chat').onclick=()=>newConversation().catch(error=>toast(error.message,true));$('stop').onclick=interrupt;$('mic').onclick=()=>toggleRecording().catch(error=>toast(error.message,true));
$('header-new').onclick=$('new-chat').onclick;
$('focus').onchange=()=>savePreferences({focus:$('focus').value}).catch(error=>toast(error.message,true));
$('theme-toggle').onclick=()=>savePreferences({theme:({system:'light',light:'dark',dark:'system'})[state.preferences.theme||'system']}).catch(error=>toast(error.message,true));
$('history-search').oninput=refreshHistory;$('search-open').onclick=()=>{$('history-search').focus();};
$('attach-document').onclick=()=>$('document-input').click();$('attach-screen').onclick=()=>$('screen-input').click();
$('document-input').onchange=()=>uploadDocument($('document-input').files[0]).catch(error=>toast(error.message,true));$('screen-input').onchange=()=>uploadImage($('screen-input').files[0]).catch(error=>toast(error.message,true));
$('export').onclick=()=>{const a=document.createElement('a');a.href='/api/export';a.download='wednesday-workspace.json';a.click();};
$('dialog-close').onclick=$('dialog-cancel').onclick=()=>motion.close($('editor-dialog'));
$('editor-dialog').addEventListener('cancel',event=>{event.preventDefault();motion.close($('editor-dialog'));});
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='n'){event.preventDefault();newConversation().catch(error=>toast(error.message,true));}if(event.key==='Escape')interrupt();if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();$('history-search').focus();}});
async function boot(){try{const session=await api('session',{method:'POST'});state.owner=session.owner_id;state.preferences=session.preferences;applyPreferences();state.conversation=localStorage.getItem('wednesday-conversation-'+state.owner);if(state.conversation){try{await api('conversations/'+state.conversation);}catch{state.conversation=null;}}connect();await refreshHistory();if(new URLSearchParams(location.search).get('view')==='settings')showView('settings');}catch(error){toast(error.message,true);$('connection-label').textContent='Service unavailable';}}
boot();

// Pointer highlights update only the floating interaction material, at most once per frame.
(() => {
  let frame=0, point;
  const enabled=()=>!matchMedia('(prefers-reduced-motion: reduce)').matches && document.documentElement.dataset.reduceMotion!=='true';
  document.addEventListener('pointermove',event=>{
    if(!enabled())return;
    const surface=event.target.closest('.glass,.topbar,.rail,.chat-composer,dialog,.header-actions');
    if(!surface)return;
    point={surface,x:event.clientX,y:event.clientY};
    if(frame)return;
    frame=requestAnimationFrame(()=>{frame=0;const {surface,x,y}=point;const rect=surface.getBoundingClientRect();if(!rect.width||!rect.height)return;surface.style.setProperty('--glass-x',`${Math.round((x-rect.left)/rect.width*100)}%`);surface.style.setProperty('--glass-y',`${Math.round((y-rect.top)/rect.height*100)}%`);});
  },{passive:true});
})();
