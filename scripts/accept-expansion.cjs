'use strict';
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.env.WEDNESDAY_URL||'http://127.0.0.1:8799/ui/');
  await page.locator('#connection-label').filter({hasText:'Workspace connected'}).waitFor();
  await page.evaluate(()=>navigator.serviceWorker.ready);
  await page.waitForFunction(()=>navigator.serviceWorker.controller!==null);
  await page.route('**/api/expansion/folders', route => route.fulfill({json:{folders:[{
    id:'fixture', root:'Approved fixture', status:'ready', files:[
      {path:'pending.pdf',error:'PDF workers are busy; extraction will retry on the next scan'},
    ],
  }]}}));
  await page.getByRole('button',{name:'Local workspace'}).click();
  await page.getByText('1 files need attention',{exact:true}).click();
  await page.getByText('pending.pdf — PDF workers are busy; extraction will retry on the next scan',{exact:true}).waitFor();
  await page.getByRole('heading',{name:'Offline operations',exact:true}).waitFor();
  await context.setOffline(true);
  await page.locator('#field-title').fill('Offline acceptance');
  await page.locator('#field-content').fill('violet offline evidence');
  await page.getByRole('button',{name:'Save to local queue'}).click();
  await page.getByText('pending',{exact:true}).waitFor();
  await page.reload();
  await page.getByText('pending',{exact:true}).waitFor();
  await context.setOffline(false);
  await page.getByRole('button',{name:'Synchronize now'}).click();
  await page.getByText('completed · revision 1',{exact:true}).waitFor();
  await page.reload();await page.locator('#connection-label').filter({hasText:'Workspace connected'}).waitFor();
  await page.getByRole('button',{name:'Local workspace'}).click();
  await page.getByText('completed · revision 1',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Propose a time block'}).click();
  await page.getByRole('dialog').locator('#field-title').fill('Focused work');
  await page.getByRole('dialog').getByRole('button',{name:'Save',exact:true}).click();
  await page.getByRole('button',{name:'Approve this exact block'}).click();
  await page.getByRole('heading',{name:'Focused work',exact:true}).waitFor();
  await page.getByRole('button',{name:'Plan several tasks'}).click();
  await page.getByRole('dialog').locator('#field-tasks').fill('Read brief | 30 | 8\nDraft notes | 20 | 3');
  await page.getByRole('dialog').getByRole('button',{name:'Save',exact:true}).click();
  await page.getByRole('button',{name:'Approve all blocks locally'}).click();
  await page.getByRole('heading',{name:'Read brief',exact:true}).waitFor();
  await page.getByRole('heading',{name:'Draft notes',exact:true}).waitFor();
  const source=await page.evaluate(async()=>{const r=await fetch('/api/search?q=violet');return (await r.json()).sources[0].id;});
  await page.getByRole('button',{name:'Save a reviewed evaluation'}).click();
  await page.getByRole('dialog').locator('#field-title').fill('Source acceptance');
  await page.getByRole('dialog').locator('#field-query').fill('violet');
  await page.getByRole('dialog').locator('#field-sources').fill(source);
  await page.getByRole('dialog').getByRole('button',{name:'Save',exact:true}).click();
  await page.getByRole('button',{name:'Run read-only evaluation'}).click();
  await page.getByRole('heading',{name:'Evaluation passed'}).waitFor();
  await page.getByRole('button',{name:'Save a reviewed evaluation'}).click();
  const calendarCase=page.getByRole('dialog');
  await calendarCase.locator('#field-title').fill('Calendar offset acceptance');
  await calendarCase.locator('#field-kind').selectOption('calendar_timezone');
  await calendarCase.locator('#field-query').fill('2027-11-07T01:30:00-05:00');
  await calendarCase.locator('#field-expected_utc').fill('2027-11-07T06:30:00Z');
  await calendarCase.getByRole('button',{name:'Save',exact:true}).click();
  await page.getByRole('heading',{name:'Calendar offset acceptance',exact:true}).waitFor();
  await page.getByRole('button',{name:'Save a reviewed evaluation'}).click();
  const syntaxCase=page.getByRole('dialog');
  await syntaxCase.locator('#field-title').fill('Python error line acceptance');
  await syntaxCase.locator('#field-kind').selectOption('python_diagnostics');
  await syntaxCase.locator('#field-query').fill('x = 1\ndef broken(:');
  await syntaxCase.locator('#field-expect_error').selectOption('true');
  await syntaxCase.locator('#field-expected_line').fill('3');
  await syntaxCase.getByRole('button',{name:'Save',exact:true}).click();
  await page.getByRole('heading',{name:'Python error line acceptance',exact:true}).waitFor();
  const runSuite = page.getByRole('button',{name:'Run saved evaluation suite'});
  await runSuite.focus();
  await page.keyboard.press('Enter');
  await page.getByRole('heading',{name:'2 passed · 1 failed'}).waitFor();
  const dialog = page.getByRole('dialog',{name:'Evaluation suite results'});
  assert(await dialog.evaluate(node => document.activeElement.id === 'suite-results-heading'));
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button',{name:'Download suite report'}).click(),
  ]);
  const summary = JSON.parse(require('node:fs').readFileSync(await download.path(), 'utf8'));
  assert.equal(summary.runs.length,3);
  const syntaxResult=summary.runs.find(run=>run.formula_version==='python-diagnostics-v2');
  assert.equal(syntaxResult?.diagnostic.line,2);
  assert.equal(syntaxResult.expected_line,3);
  assert.equal(syntaxResult.passed,false);
  const calendarResult=summary.runs.find(run=>run.formula_version==='calendar-timezone-v1');
  assert.equal(calendarResult?.actual_utc,'2027-11-07T06:30:00+00:00');
  assert.equal(calendarResult.expected_utc,calendarResult.actual_utc);
  assert(summary.p95_ms >= summary.median_ms);
  await page.keyboard.press('Escape');
  await dialog.waitFor({state:'hidden'});
  assert(await runSuite.evaluate(node => document.activeElement === node));
  await page.setViewportSize({width:390,height:844});
  const mobileStatus=page.locator('#mobile-connection-status');
  await mobileStatus.waitFor({state:'visible'});
  assert.match(await mobileStatus.ariaSnapshot(), /status/);
  assert.match(await mobileStatus.textContent(), /Workspace connected/);
  const section=page.getByRole('combobox',{name:'Workspace section'});
  assert.equal(await section.inputValue(),'expansion');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Phone horizontal overflow');
  assert.deepEqual(errors,[]);
  console.log('PASS offline shell reload/reconnect/persistence, calendar approval, evaluation, phone overflow, JavaScript errors');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
