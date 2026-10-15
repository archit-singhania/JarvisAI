'use strict';
async function renderRoutines(panel){
  const [{routines},{runs}]=await Promise.all([api('routines'),api('routines/runs')]);
  const section=element('section','card');section.append(element('h2','','Visual routines'),element('p','','Ordered, bounded steps with explicit input references. Assistant requests and reminder writes pause for confirmation. Host commands and messages are not routine tools.'));
  const draft=element('div','routine-editor'),name=field('Routine title','routineTitle','text','My review routine'),steps=element('ol','continuity-list');
  draft.append(name,steps);const models=[];
  const redraw=()=>{steps.replaceChildren();models.forEach((model,index)=>{
    const row=element('li','card');row.append(element('h3','','Step '+(index+1)));
    const inputs=[field('Action','tool','text',model.tool,[['time','Current time'],['search','Read-only search'],['weather','Read-only weather'],['assistant','Assistant request · confirmation'],['reminder','Create reminder · confirmation']]),field('Input','argument','textarea',model.argument),field('Condition','condition','text',model.condition,[['always','Always'],['previous_success','Previous step succeeded'],['previous_failure','Previous step failed']]),field('On failure','failure','text',model.failure,[['stop','Stop'],['continue','Continue']]),field('Append output from earlier step · optional','input_step','number',model.input_step===null?'':model.input_step+1),field('Reminder due · timezone-aware ISO date','due_at','text',model.due_at||''),field('Reminder timezone','timezone','text',model.timezone)];
    inputs.forEach(input=>{input.querySelector('input,select,textarea').oninput=e=>{const key=e.target.name;model[key]=key==='input_step'?(e.target.value===''?null:Number(e.target.value)-1):e.target.value;};row.append(input);});
    row.append(button('Move up',()=>{if(index){[models[index-1],models[index]]=[models[index],models[index-1]];redraw();}}),button('Move down',()=>{if(index+1<models.length){[models[index+1],models[index]]=[models[index],models[index+1]];redraw();}}),button('Remove step',()=>{models.splice(index,1);redraw();}));steps.append(row);
  });};
  const add=()=>{if(models.length>=20)throw new Error('A routine supports at most 20 steps.');models.push({tool:'time',argument:'',condition:'always',failure:'stop',input_step:null,due_at:null,timezone:'UTC'});redraw();};
  draft.append(button('Add step',add),button('Save routine',async()=>{
    const title=name.querySelector('input').value;await api('routines',json('POST',{title,steps:models.map(s=>({...s,due_at:s.due_at||null}))}));await showView('continuity');
  },'primary'));section.append(draft);
  routines.forEach(r=>section.append(card(r.title,r.steps.map((s,i)=>`${i+1}. ${s.tool} · ${s.condition} · on failure ${s.failure}`).join('\n'),'Revision '+r.revision,[button('Dry-run preview',async()=>{
    const preview=await api('routines/'+r.id+'/preview',{method:'POST'});const content=element('div');preview.steps.forEach(s=>content.append(card('Step '+(s.index+1)+' · '+s.tool,s.argument||'No input',s.confirmation_required?'Pauses for explicit confirmation':'Read-only operation')));
    editDialog('Preview · no operations executed',[content],async()=>{});
  }),button('Run reviewed routine',async()=>{
    if(!confirm('Run “'+r.title+'” revision '+r.revision+'? Consequential steps will ask again.'))return;
    await api('routines/'+r.id+'/runs',json('POST',{revision:r.revision}));await showView('continuity');
  })])));
  const runList=element('div');const paint=rows=>{runList.replaceChildren();rows.forEach(r=>{
    const actions=[];if(r.status==='awaiting_confirmation')actions.push(button('Confirm step '+(r.cursor+1),async()=>{
      const step=r.snapshot.steps[r.cursor];if(!confirm('Approve '+step.tool+' step with input: '+step.argument+'?'))return;
      await api('routines/runs/'+r.id+'/confirm',json('POST',{cursor:r.cursor}));await refresh();
    }));if(['queued','running','awaiting_confirmation'].includes(r.status))actions.push(button('Stop remaining steps',async()=>{await api('routines/runs/'+r.id+'/stop',{method:'POST'});await refresh();}));
    runList.append(card(r.snapshot.title+' · '+r.status,r.results.map(x=>`${x.step+1}. ${x.success?'✓':'Failed'} ${x.content}`).join('\n')||'No steps completed.',`Step ${Math.min(r.cursor+1,r.snapshot.steps.length)} / ${r.snapshot.steps.length}`,actions));
  });};const refresh=async()=>paint((await api('routines/runs')).runs);
  section.append(element('h3','','Run receipts'),button('Refresh run progress',refresh),runList);paint(runs);panel.append(section);
}
