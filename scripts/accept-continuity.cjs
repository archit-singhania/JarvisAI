'use strict';
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {execFileSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8120/ui/');await page.getByText('Workspace connected',{exact:true}).waitFor();
    const seed=await page.evaluate(async()=>{
      const json=async(p,b)=>{const r=await fetch('/api/'+p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});if(!r.ok)throw new Error(await r.text());return r.json();};
      const s=await json('session',{}),c=await json('conversations',{title:'Illustrative branch QA'}),excluded=await json('conversations',{title:'Excluded QA session'});return {owner:s.owner_id,conversation:c.id,excluded:excluded.id};
    });
    // Populate only this registered acceptance owner's isolated database, never a real workspace.
    const code="from app.workspace import Workspace; import sys; s=Workspace('.runtime/advanced-browser-20261015/workspace.db'); s.message(sys.argv[1],sys.argv[2],'user','Illustrative original context'); s.message(sys.argv[1],sys.argv[3],'user','PRIVATE_EXCLUDED_QA')";
    execFileSync(path.resolve('../.tooling/python/Scripts/python.exe'),['-c',code,seed.owner,seed.conversation,seed.excluded],{env:{...process.env,PYTHONPATH:'backend'}});
    await page.getByRole('button',{name:'Continuity studio',exact:false}).click();
    await page.getByRole('heading',{name:'Conversation branches',exact:true}).waitFor();
    await page.locator('#field-branchConversation').selectOption(seed.conversation);
    await page.getByRole('button',{name:'Branch from this message',exact:true}).click();
    await page.getByLabel('Branch title',{exact:true}).fill('Alternative QA');await page.getByRole('dialog').getByRole('button',{name:'Save',exact:true}).click();
    await page.getByText('Branch saved. Parent history is unchanged.',{exact:true}).waitFor();
    await page.locator('#field-branchConversation').selectOption(seed.conversation);
    await page.getByRole('button',{name:/Open branch/}).click();
    await page.getByText('Compare with immutable parent context',{exact:true}).click();
    await page.getByRole('heading',{name:'Original context',exact:true}).waitFor();
    // Explicitly select only the original conversation for the digest.
    await page.getByText('Conversations',{exact:true}).click();
    await page.getByLabel('Illustrative branch QA',{exact:true}).check();
    await page.getByRole('button',{name:'Generate selected digest',exact:true}).click();
    await page.getByRole('button',{name:'Save Focus preset',exact:true}).click();
    await page.getByRole('button',{name:'Restore layout',exact:true}).last().waitFor();
    await page.getByRole('button',{name:'Add step',exact:true}).click();
    await page.getByRole('button',{name:'Save routine',exact:true}).click();
    await page.getByRole('button',{name:'Dry-run preview',exact:true}).click();
    await page.getByRole('heading',{name:'Preview · no operations executed',exact:true}).waitFor();
    await page.getByRole('button',{name:'Cancel',exact:true}).click();
    page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Run reviewed routine',exact:true}).click();
    await page.waitForFunction(async()=>{const x=await(await fetch('/api/routines/runs')).json();return x.runs.some(r=>r.status==='completed');});
    await page.getByRole('button',{name:'Refresh run progress',exact:true}).click();
    const data=await page.evaluate(async()=>({digest:await(await fetch('/api/continuity/digests')).json(),runs:await(await fetch('/api/routines/runs')).json(),layouts:await(await fetch('/api/continuity/layouts/browser')).json()}));
    assert(!JSON.stringify(data.digest).includes('PRIVATE_EXCLUDED_QA'));assert(data.runs.runs[0].status==='completed');assert(data.layouts.layouts.length);
    const dir='docs/continuity-2026-10-15';fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:dir+'/desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:dir+'/phone.png',fullPage:true});
    await page.reload();await page.getByText('Workspace connected',{exact:true}).waitFor();await page.getByRole('button',{name:'Continuity studio',exact:false}).click();await page.getByRole('button',{name:'Restore layout',exact:true}).last().waitFor();
    assert.deepEqual(errors,[]);fs.writeFileSync(dir+'/acceptance.json',JSON.stringify({date:new Date().toISOString(),branchCreated:true,immutableComparison:true,digestExclusion:true,routineCompleted:true,layoutsPersisted:true,pageErrors:errors},null,2));
    console.log('Wednesday continuity browser acceptance passed.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
