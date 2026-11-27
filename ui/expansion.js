/* Local-only continuity tools. Values are rendered as text, never HTML. */
const localQueueKey=()=>{if(!state.owner)throw new Error('Connect this workspace once before saving offline.');return 'wednesday-edits-v1-'+state.owner;};
const readEdits=()=>JSON.parse(localStorage.getItem(localQueueKey())||'[]');
const writeEdits=rows=>localStorage.setItem(localQueueKey(),JSON.stringify(rows));
let syncingEdits=false;
async function syncEdits(){
  if(syncingEdits)return;
  syncingEdits=true;
  try{
    const active=await api('session',{method:'POST'});
    if(active.owner_id!==state.owner)throw new Error('Workspace changed. Reload before synchronizing private edits.');
    for(const row of readEdits().filter(r=>['pending','failed','syncing'].includes(r.status))){
      const update=patch=>writeEdits(readEdits().map(r=>r.operation_id===row.operation_id?{...r,...patch}:r));
      update({status:'syncing'});
      try{const result=await api('expansion/offline',json('POST',row.body));update({status:result.status,result});}
      catch(error){update({status:'failed',error:error.message});break;}
    }
  }finally{syncingEdits=false;}
}
window.addEventListener('online',()=>syncEdits().then(()=>{if(state.view==='expansion')showView('expansion');}).catch(error=>toast(error.message,true)));
function localDownload(name,text,type='application/json'){
  const link=document.createElement('a'),url=URL.createObjectURL(new Blob([text],{type}));link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function renderExpansion(panel,isCurrent){
  panel.replaceChildren(intro('Your local workspace.','Save edits through disconnections, review calendar blocks, inspect approved document folders and evaluate local source retrieval.'));
  const offline=element('section','card');offline.append(intro('Offline operations','Only notes, conversation drafts, memory corrections and reminders can synchronize. No host command or external action is replayed.'));
  const form=element('form'),draftKey=localQueueKey()+'-draft';let saved={};try{saved=JSON.parse(localStorage.getItem(draftKey)||'{}');}catch{}
  const fields=[field('Kind','kind','text',saved.kind||'note',[['note','Knowledge note'],['draft','Conversation draft'],['memory','Existing memory correction'],['reminder','Local reminder']]),field('Title','title','text',saved.title||''),field('Content','content','textarea',saved.content||''),field('Existing record ID (blank for new note/draft/reminder)','id','text',saved.id||''),field('Expected revision (memory: current version)','revision','number',saved.revision||'0'),field('Reminder timestamp with UTC offset','due_at','text',saved.due_at||'')];
  form.append(...fields);form.oninput=()=>localStorage.setItem(draftKey,JSON.stringify(Object.fromEntries(new FormData(form))));
  const submit=element('button','primary','Save to local queue');submit.type='submit';form.append(submit);
  form.onsubmit=event=>{event.preventDefault();try{const value=Object.fromEntries(new FormData(form));if(!value.title.trim()||!value.content.trim())throw new Error('Enter a title and content.');if(value.kind==='memory'&&!value.id)throw new Error('Choose an existing memory ID.');const op=crypto.randomUUID(),body={operation_id:op,id:value.id||crypto.randomUUID(),kind:value.kind,expected_revision:Number(value.revision),value:{title:value.title,content:value.content,due_at:value.due_at||null}};const rows=readEdits();if(rows.length>=200)throw new Error('Remove completed entries before adding more.');writeEdits([...rows,{operation_id:op,status:'pending',body}]);localStorage.removeItem(draftKey);showView('expansion');}catch(error){toast(error.message,true);}};
  offline.append(form,button('Synchronize now',async()=>{await syncEdits();await showView('expansion');}));
  for(const row of readEdits()){
    const actions=[button('Remove local entry',()=>{writeEdits(readEdits().filter(r=>r.operation_id!==row.operation_id));showView('expansion');})];
    if(row.status==='conflicted')actions.unshift(button('Review both versions',()=>{
      const d=memoryDialog('Resolve offline conflict');d.append(card('Your edit',row.body.value.content),card('Current saved version',row.result.current?.value?.content||'Record unavailable'));
      if(row.result.current)d.append(button('Use my edit against this revision',()=>{const op=crypto.randomUUID();writeEdits(readEdits().map(r=>r.operation_id===row.operation_id?{operation_id:op,status:'pending',body:{...row.body,operation_id:op,expected_revision:row.result.current.revision}}:r));d.close();showView('expansion');}));d.append(button('Keep both for later',()=>d.close()));
    }));
    offline.append(card(row.body.value.title,row.error||row.body.value.content,`${row.status}${row.result?.revision?' · revision '+row.result.revision:''}`,actions));
  }
  panel.append(offline);
  const calendar=element('section','card');calendar.append(intro('Calendar planning','Local UTC/IANA-timezone timed-event import/export. All-day dates use your workspace timezone. Open-ended series report their planning coverage. Google requires an explicitly configured account. Enter explicit offsets to avoid ambiguous daylight-saving times.'));
  const input=element('input');input.type='file';input.accept='.ics';input.setAttribute('aria-label','Import calendar file');input.onchange=async()=>{try{const file=input.files[0];if(!file)return;if(file.size>1000000)throw new Error('Calendar exceeds 1 MB');await api('expansion/calendar/import',json('POST',{text:await file.text()}));await showView('expansion');}catch(error){toast(error.message,true);}};
  calendar.append(input,button('Export calendar',async()=>localDownload('wednesday.ics',(await api('expansion/calendar/export')).text,'text/calendar')),button('Propose a time block',()=>editDialog('Working window',[field('Title','title'),field('Window start with offset','start','text',new Date().toISOString()),field('Window end with offset','end','text',new Date(Date.now()+8*3600000).toISOString()),field('Minutes','minutes','number','30')],async body=>{
    const proposal=await api('expansion/calendar/proposals',json('POST',{...body,minutes:Number(body.minutes)}));const d=memoryDialog('Review proposed block');d.append(card(proposal.title,`${proposal.start} → ${proposal.end}`,'Local calendar only; no invitations.'),button('Approve this exact block',async()=>{await api('expansion/calendar/proposals/'+proposal.id+'/approve',json('POST',{confirmed:true}));d.close();await showView('expansion');}),button('Approve write to selected Google calendar',async()=>{if(!confirm('Create this exact event in the selected Google calendar? No guests will be invited.'))return;await api('expansion/calendar/proposals/'+proposal.id+'/google',json('POST',{confirmed:true}));d.close();await showView('expansion');}),button('Leave unapplied',()=>d.close()));
  })));
  calendar.append(button('Select configured Google calendar',async()=>{const data=await api('expansion/calendar/google');editDialog('Select Google calendar',[field('Calendar','calendar','text',data.calendars[0]?.id||'',data.calendars.map(c=>[c.id,c.title+' ('+c.role+')']))],body=>api('expansion/calendar/google/connect',json('POST',{...body,confirmed:true})));}),button('Synchronize selected Google calendar',async()=>{await api('expansion/calendar/google/sync',{method:'POST'});await showView('expansion');}),button('Disconnect Google calendar',async()=>{const result=await api('expansion/calendar/google',{method:'DELETE'});await showView('expansion');if(result.google_revocation==='unconfirmed')toast('Disconnected locally. Google revocation could not be confirmed.',true);}));
  calendar.append(button('Sign in with Google', async () => {
    const result = await api('expansion/calendar/google/oauth/start', {method:'POST'});
    window.location.assign(result.url);
  }));
  calendar.append(button('Plan several tasks', () => editDialog('Plan several tasks', [
    field('Window start with UTC offset','start','text',new Date().toISOString()),
    field('Window end with UTC offset','end','text',new Date(Date.now()+8*3600000).toISOString()),
    field('One task per line: title | minutes | priority (0–10)','tasks','textarea'),
  ], async body => {
    const tasks = body.tasks.split(/\r?\n/).filter(line => line.trim()).map(line => {
      const [title, minutes, priority='0'] = line.split('|').map(value => value.trim());
      return {title, minutes:Number(minutes), priority:Number(priority)};
    });
    const proposal = await api('expansion/calendar/task-plans',json('POST',{start:body.start,end:body.end,tasks}));
    const dialog = memoryDialog('Review task plan');
    for (const block of proposal.blocks) dialog.append(card(block.title,block.start+' → '+block.end));
    dialog.append(button('Approve all blocks locally',async()=>{
      await api('expansion/calendar/proposals/'+proposal.id+'/approve',json('POST',{confirmed:true}));
      dialog.close();
      await showView('expansion');
    }),button('Cancel',()=>dialog.close()));
  })));
  panel.append(calendar);
  const folders=element('section','card');folders.append(intro('Watched documents','Select folders from the desktop client after explicitly configuring approved host roots. This browser only inspects status and can stop indexing. Scans run every 30 seconds.'));
  panel.append(folders);
  const evaluations=element('section','card');evaluations.append(intro('Local evaluation cases','Save a deliberately redacted query and expected owned source IDs. Runs measure source retrieval, Python syntax, or calendar timestamp normalization, latency and a labeled synthetic cancellation probe; no model calls or command execution.'));
  evaluations.append(button('Save a reviewed evaluation',()=>editDialog('Review and redact this evaluation',[field('Title','title'),field('Check type','kind','text','retrieval',[['retrieval','Source retrieval'],['retrieval_exact','Exact ranked retrieval'],['python_diagnostics','Python syntax diagnostics'],['calendar_timezone','Calendar timestamp normalization']]),field('Redacted query, Python code, or timestamp','query','textarea'),field('Expected source IDs, comma separated (ordered for exact retrieval)','sources'),field('Expected UTC timestamp (calendar only)','expected_utc'),field('Expected error line (Python only, optional)','expected_line'),field('Expect invalid input','expect_error','text','false',[['false','No'],['true','Yes']])],body=>api('expansion/evaluations',json('POST',{title:body.title,query:body.query,kind:body.kind,expect_error:body.expect_error==='true',expected_utc:body.expected_utc.trim()||null,expected_line:body.expected_line.trim()||null,expected_sources:body.sources.split(',').map(v=>v.trim()).filter(Boolean),confirmed:true})))));
  const suiteStatus = element('p');
  suiteStatus.setAttribute('role', 'status');
  const runSuite = button('Run saved evaluation suite', async () => {
    if (runSuite.getAttribute('aria-disabled') === 'true') return;
    runSuite.setAttribute('aria-disabled', 'true');
    suiteStatus.textContent = 'Running saved evaluations…';
    let summary;
    try {
      summary = await api('expansion/evaluations/run-suite', {method:'POST'});
      suiteStatus.textContent = '';
    } catch (error) {
      suiteStatus.textContent = error.message;
      return;
    } finally {
      runSuite.removeAttribute('aria-disabled');
    }
    if (!isCurrent()) return;
    const dialog = element('dialog', 'memory-inspector');
    const heading = element('h2', '', 'Evaluation suite results');
    heading.id = 'suite-results-heading';
    heading.tabIndex = -1;
    dialog.setAttribute('aria-labelledby', heading.id);
    dialog.append(heading);
    dialog.append(card(
      summary.passed + ' passed · ' + summary.failed + ' failed',
      'Median ' + summary.median_ms + ' ms · p95 ' + summary.p95_ms + ' ms · ' + summary.reused_retrievals + ' reused retrievals',
      summary.failed_case_ids.length ? 'Failed cases: ' + summary.failed_case_ids.join(', ') : '',
      [button('Download suite report', () => localDownload('evaluation-suite.json', JSON.stringify(summary, null, 2))),
       button('Close results', () => dialog.close())]
    ));
    const failedRuns = summary.runs.filter(result => !result.passed);
    if (failedRuns.length) {
      const reasons = element('ul', '');
      reasons.setAttribute('aria-label', 'Evaluation failure details');
      for (const result of failedRuns) {
        const probe = result.cancellation_probe;
        let reason = probe?.failure;
        if (!reason && probe?.passed === false) {
          reason = 'Realtime interruption or event order differed from the expected sequence.';
        }
        if (!reason && result.expected_line != null) {
          reason = `Expected Python error on line ${result.expected_line}; observed ${result.diagnostic?.line ?? 'no error'}.`;
        }
        reasons.append(element('li', '', reason || 'The result did not match the saved expectation.'));
      }
      dialog.append(reasons);
    }
    dialog.addEventListener('close', () => {
      dialog.remove();
      if (isCurrent()) runSuite.focus();
    }, {once:true});
    document.body.append(dialog);
    dialog.showModal();
    heading.focus();
  });
  evaluations.append(runSuite, suiteStatus);
  panel.append(evaluations);
  await Promise.all([
    api('expansion/calendar').then(data=>{if(isCurrent()){if(data.checked_until)calendar.append(empty("Recurring calendar checked through "+data.checked_until));calendar.append(empty(data.google.available?'Configured account: '+data.google.account_label+' · '+(data.google.connection?.calendar||'Choose a calendar'):'Google Calendar unavailable: host credentials and workspace authorization are required.'));data.events.forEach(e=>calendar.append(card(e.title,`${e.start} → ${e.end}`)));}}).catch(error=>calendar.append(empty(error.message))),
    api('expansion/folders').then(data => {
      if (!isCurrent()) return;
      folders.append(button('Refresh watched folders', () => showView('expansion')));
      for (const folder of data.folders) {
        const summary = card(folder.root, folder.error || (folder.files.length + ' files'), folder.status, [
          button('Stop indexing and remove indexed content', async () => {
            await api('expansion/folders/'+folder.id, {method:'DELETE'});
            await showView('expansion');
          }),
        ]);
        const failures = folder.files.filter(file => file.error);
        if (failures.length) {
          const details = element('details');
          details.append(element('summary', '', failures.length + ' files need attention'));
          const list = element('ul');
          for (const file of failures) list.append(element('li', '', file.path + ' — ' + file.error));
          details.append(list);
          summary.append(details);
        }
        folders.append(summary);
      }
      if (!data.folders.length) folders.append(empty('No approved folders are being indexed.'));
    }).catch(error => { if (isCurrent()) folders.append(empty(error.message)); }),
    api('expansion/evaluations').then(data=>{if(isCurrent()){data.cases.forEach(c=>evaluations.append(card(c.value.title,c.value.query,c.id,[button('Run read-only evaluation',async()=>{const result=await api('expansion/evaluations/'+c.id+'/run',{method:'POST'});localDownload('evaluation-'+result.id+'.json',JSON.stringify(result,null,2));await showView('expansion');}),button('Delete case and results',async()=>{await api('expansion/evaluations/'+c.id,{method:'DELETE'});await showView('expansion');})])));data.runs.forEach(r=>evaluations.append(card(r.value.passed?'Evaluation passed':'Evaluation failed',r.value.coverage,`${r.value.latency_ms} ms · ${r.created_at}`)));}}).catch(error=>evaluations.append(empty(error.message)))
  ]);
}
