'use strict';
let meetingRecorder=null;
let meetingAcquiring=false;
const meetingDrafts=new Map();
window.addEventListener('beforeunload',event=>{if(meetingRecorder||meetingAcquiring){event.preventDefault();event.returnValue='Stop and save the meeting recording before leaving.';}});
async function renderMeetings(panel){
  if(!meetingDrafts.has(state.owner))meetingDrafts.set(state.owner,{title:'Meeting notes',consent:false,retain:false});
  const draft=meetingDrafts.get(state.owner);
  const {meetings,capability}=await api('meetings');const section=element('section','card');
  section.append(element('h2','','Meeting companion'),element('p','',capability.available?'Local transcription engine is available.':capability.detail));
  const consent=element('input');consent.type='checkbox';consent.checked=draft.consent;consent.onchange=()=>draft.consent=consent.checked;const line=element('label','check-field');line.append(consent,document.createTextNode('I have participant consent to record or import this meeting.'));
  const retain=element('input');retain.type='checkbox';retain.checked=draft.retain;retain.onchange=()=>draft.retain=retain.checked;const retainLine=element('label','check-field');retainLine.append(retain,document.createTextNode('Keep raw audio after successful transcription (off by default).'));
  const title=field('Meeting title','meetingTitle','text',draft.title);title.querySelector('input').oninput=e=>draft.title=e.target.value;const file=element('input');file.type='file';file.accept='.wav,.mp3,.m4a,.ogg,.webm,.flac';file.setAttribute('aria-label','Import meeting audio');
  const upload=async(audio)=>{if(!consent.checked)throw new Error('Confirm participant consent first.');const data=new FormData();data.append('file',audio);data.append('title',title.querySelector('input').value);data.append('consent','true');data.append('retain',String(retain.checked));await api('meetings',{method:'POST',body:data});toast('Meeting saved to the transcription queue.');await showView('continuity');};
  file.onchange=()=>{if(file.files[0])upload(file.files[0]).catch(e=>toast(e.message,true));};
  const status=element('p','','Microphone idle');status.setAttribute('role','status');
  const stop=button('■ Stop meeting recording',()=>{if(meetingRecorder?.recorder.state==='recording')meetingRecorder.recorder.stop();});stop.hidden=true;
  const start=button('Record consented meeting',async()=>{
    if(!consent.checked)throw new Error('Confirm participant consent first.');
    if(meetingRecorder||meetingAcquiring)throw new Error('A recording or microphone request is already active. Use its Stop control.');
    if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw new Error('Recording is unavailable; import an audio file instead.');
    meetingAcquiring=true;start.disabled=true;let cancelled=false;
    const pending=button('Cancel meeting microphone request',()=>{cancelled=true;pending.remove();status.textContent='Microphone request cancelled; any late stream will be released.';},'primary');document.querySelector('.header-actions').append(pending);
    let stream;
    try{stream=await navigator.mediaDevices.getUserMedia({audio:true});}
    catch(error){meetingAcquiring=false;start.disabled=false;pending.remove();throw error;}
    meetingAcquiring=false;pending.remove();
    if(cancelled){stream.getTracks().forEach(t=>t.stop());start.disabled=false;return;}
    const recorder=new MediaRecorder(stream),chunks=[];let size=0;
    const session={recorder,stream};meetingRecorder=session;start.disabled=true;stop.hidden=false;status.textContent='● Recording meeting — microphone active';status.classList.add('recording-active');
    // Keep an always-visible Stop control even if the user navigates to another panel.
    const globalStop=button('■ Stop meeting recording',()=>recorder.stop(),'primary');globalStop.id='meeting-stop-global';document.querySelector('.header-actions').append(globalStop);
    const limit=setTimeout(()=>{if(recorder.state==='recording')recorder.stop();},30*60*1000);
    recorder.ondataavailable=e=>{chunks.push(e.data);size+=e.data.size;if(size>90*1024*1024&&recorder.state==='recording')recorder.stop();};
    recorder.onerror=()=>{toast('Recording failed. The local recording will be offered for recovery.',true);if(recorder.state!=='inactive')recorder.stop();};
    recorder.onstop=async()=>{
      clearTimeout(limit);stream.getTracks().forEach(t=>t.stop());meetingRecorder=null;globalStop.remove();start.disabled=false;stop.hidden=true;status.textContent='Recording stopped';status.classList.remove('recording-active');
      const mime=recorder.mimeType||'audio/webm';const suffix=mime.includes('mp4')?'m4a':mime.includes('ogg')?'ogg':'webm';const audio=new File(chunks,'meeting.'+suffix,{type:mime});
      try{await upload(audio);}catch(e){toast(e.message,true);const url=URL.createObjectURL(audio),a=element('a','','Save recording locally for retry');a.href=url;a.download=audio.name;document.querySelector('.header-actions').append(a);a.onclick=()=>setTimeout(()=>{URL.revokeObjectURL(url);a.remove();},1000);}
    };recorder.start(1000);
  },'primary');section.append(title,line,retainLine,file,start,stop,status,button('Refresh meeting jobs',()=>showView('continuity')));
  meetings.forEach(m=>{
    const details=element('details');details.append(element('summary','',m.title+' · '+m.status),element('p','',m.error||`${m.transcript.length} transcript segments · raw audio ${m.audio_present?'retained':'removed'}`));
    m.transcript.forEach(s=>details.append(card(`${s.start.toFixed(1)}–${s.end.toFixed(1)}s`,s.text)));
    details.append(button('Edit meeting notes',()=>editDialog('Notes and proposals',[field('Notes','notes','textarea',m.notes.notes||''),field('Decisions · one per line','decisions','textarea',(m.notes.decisions||[]).join('\n')),field('Proposed reminders · one per line','proposed_reminders','textarea',(m.notes.proposed_reminders||[]).join('\n'))],body=>api('meetings/'+m.id,json('PATCH',{revision:m.revision,notes:body.notes,decisions:body.decisions.split('\n').filter(Boolean),proposed_reminders:body.proposed_reminders.split('\n').filter(Boolean)})))));
    (m.notes.proposed_reminders||[]).forEach(text=>details.append(button('Review reminder: '+text.slice(0,60),()=>editDialog('Confirm a proposed reminder',[field('Reminder text','text','text',text),field('Local date and time','due_at','datetime-local'),field('IANA timezone','timezone','text',state.preferences.timezone||'UTC')],body=>api('reminders',json('POST',body))))));
    if(['failed','interrupted'].includes(m.status))details.append(button('Retry transcription',async()=>{await api('meetings/'+m.id+'/retry',{method:'POST'});await showView('continuity');}));
    details.append(button('Delete meeting and raw audio',async()=>{if(!confirm('Delete this meeting, its notes and any retained audio?'))return;await api('meetings/'+m.id,{method:'DELETE'});await showView('continuity');}));section.append(details);
  });panel.append(section);
}
