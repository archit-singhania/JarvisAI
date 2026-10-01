const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');
const {WorkspaceBridge}=require('../src/workspace.cjs');
test('workspace ownership, linked escape, atomic saves and bounded files',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'aura-test-'));const outside=await fs.mkdtemp(path.join(os.tmpdir(),'aura-outside-'));const bridge=new WorkspaceBridge();await bridge.select(root);
  await bridge.write('test.py','print("saved")');assert.equal(await bridge.read('test.py'),'print("saved")');assert.equal((await bridge.list(root))[0].name,'test.py');
  await assert.rejects(bridge.create('test.py'),/already exists/);assert.equal(await bridge.read('test.py'),'print("saved")');await bridge.create('new.py');assert.equal(await bridge.read('new.py'),'');
  await assert.rejects(bridge.read(path.join(outside,'private.py')),/outside/);await assert.rejects(bridge.write('../escape.py','bad'),/outside/);
  await fs.symlink(outside,path.join(root,'linked'),process.platform==='win32'?'junction':'dir');await assert.rejects(bridge.write('linked/escape.py','bad'),/Linked/);
});
test('terminal streams output and exits without blocking; cancellable process',async()=>{
  const bridge=new WorkspaceBridge();await bridge.select(await fs.mkdtemp(path.join(os.tmpdir(),'aura-process-')));const data=[];
  const run=await bridge.execute(process.execPath,['-e','process.stdout.write("actual output")'],event=>data.push(event));const result=await run.completion;
  assert.equal(result.ok,true);assert.equal(result.out,'actual output');assert.equal(data[0].stream,'stdout');
  const long=await bridge.execute(process.execPath,['-e','setInterval(()=>{},1000)']);assert.equal(bridge.cancel(long.id),true);await long.completion;assert.equal(bridge.processes.size,0);
});
