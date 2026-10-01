'use strict';
const {app,BrowserWindow,ipcMain,dialog,protocol,net,Menu}=require('electron');
const path=require('node:path'),fs=require('node:fs/promises'),{pathToFileURL}=require('node:url');
const {WorkspaceBridge}=require('./workspace.cjs');
protocol.registerSchemesAsPrivileged([{scheme:'aura',privileges:{standard:true,secure:true,supportFetchAPI:true,corsEnabled:true,stream:true}}]);
if(process.env.AURA_TEST_DATA)app.setPath('userData',path.resolve(process.env.AURA_TEST_DATA));
const workspace=new WorkspaceBridge();let window,token='';
const backend=process.env.WEDNESDAY_URL||'http://127.0.0.1:8000';
function trusted(event){const url=new URL(event.senderFrame.url);return event.sender===window.webContents&&event.senderFrame===window.webContents.mainFrame&&url.protocol==='aura:'&&url.hostname==='app';}
function handle(name,fn){ipcMain.handle(name,async(event,...args)=>{if(!trusted(event))throw new Error('Untrusted renderer.');return fn(...args);});}
async function backendRequest(route,method='GET',body){
  if(!/^(session|preferences|capabilities|conversations(?:\/[a-f0-9]+)?|memories(?:\/[a-f0-9]+)?|documents|records\/[a-f0-9]+|reminders(?:\/[a-f0-9]+)?|workflows(?:\/[a-f0-9]+\/run)?|receipts|export|code\/(diagnostics|analyze)|search\?q=.*)$/.test(route))throw new Error('Unsupported service route.');
  if(!['GET','POST','PATCH','DELETE'].includes(method))throw new Error('Unsupported HTTP method.');
  const response=await fetch(backend+'/api/'+route,{method,headers:{'Content-Type':'application/json',...(token?{'Authorization':'Bearer '+token}:{})},...(body?{body:JSON.stringify(body)}:{})});
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Service request failed.');return data;
}
app.whenReady().then(async()=>{
  protocol.handle('aura',request=>{const url=new URL(request.url);const root=path.join(__dirname);const file=path.resolve(root,'.'+decodeURIComponent(url.pathname));if(url.hostname!=='app'||!file.startsWith(root+path.sep))return new Response('Forbidden',{status:403});return net.fetch(pathToFileURL(file).toString());});
  window=new BrowserWindow({width:1480,height:930,minWidth:900,minHeight:650,show:process.env.AURA_HEADLESS!=='1',title:'AuraScript',icon:path.join(__dirname,'../assets/icon.png'),backgroundColor:'#10111b',webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,offscreen:process.env.AURA_HEADLESS==='1',backgroundThrottling:process.env.AURA_HEADLESS!=='1'}});
  window.webContents.setWindowOpenHandler(()=>({action:'deny'}));window.webContents.on('will-navigate',(event,url)=>{if(!url.startsWith('aura://app/'))event.preventDefault();});
  window.webContents.on('will-prevent-unload',event=>{const choice=dialog.showMessageBoxSync(window,{type:'question',buttons:['Keep editing','Discard changes'],defaultId:0,cancelId:0,title:'Unsaved changes',message:'Some files have unsaved edits.'});if(choice===1)event.preventDefault();});
  const stateFile=path.join(app.getPath('userData'),'workspace-session.json');try{token=JSON.parse(await fs.readFile(stateFile,'utf8')).token||'';}catch{}
  handle('bootstrap',async()=>{const session=await backendRequest('session','POST');token=session.token;await fs.writeFile(stateFile,JSON.stringify({token}));return {...session,backend};});
  handle('backend',backendRequest);
  handle('open-folder',async()=>{const result=await dialog.showOpenDialog(window,{properties:['openDirectory']});if(result.canceled)return null;return workspace.select(result.filePaths[0]);});
  handle('read-file',p=>workspace.read(p));handle('create-file',p=>workspace.create(p));handle('write-file',(p,c)=>workspace.write(p,c));handle('list-dir',p=>workspace.list(p));
  handle('terminal',async command=>{const run=await workspace.terminal(command,event=>window.webContents.send('terminal-data',event));run.completion.then(result=>window.webContents.send('terminal-exit',result));return {id:run.id};});
  handle('cancel-process',id=>workspace.cancel(id));handle('checkpoint',message=>workspace.checkpoint(message));handle('git-log',()=>workspace.git(['log','-15','--format=%H%x09%s%x09%ci']));handle('git-diff',commit=>{if(!/^[a-f0-9]{7,40}$/.test(commit))throw new Error('Invalid commit.');return workspace.git(['show',commit,'--no-color','--no-ext-diff']);});
  handle('select-image',async()=>{const selected=await dialog.showOpenDialog(window,{properties:['openFile'],filters:[{name:'Images',extensions:['png','jpg','jpeg','webp']}]});if(selected.canceled)return null;const bytes=await fs.readFile(selected.filePaths[0]);if(bytes.length>8*1024*1024)throw new Error('Image exceeds 8 MB.');return {name:path.basename(selected.filePaths[0]),base64:bytes.toString('base64')};});
  handle('export',async()=>{const selected=await dialog.showSaveDialog(window,{defaultPath:'wednesday-workspace.json',filters:[{name:'JSON',extensions:['json']}]});if(selected.canceled)return false;await fs.writeFile(selected.filePath,JSON.stringify(await backendRequest('export'),null,2));return true;});
  Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'AuraScript',submenu:[{role:'about'},{role:'quit'}]},{label:'Edit',submenu:[{role:'undo'},{role:'redo'},{type:'separator'},{role:'cut'},{role:'copy'},{role:'paste'},{role:'selectAll'}]},{label:'View',submenu:[{role:'resetZoom'},{role:'zoomIn'},{role:'zoomOut'},{role:'togglefullscreen'}]}]));
  await window.loadURL('aura://app/index.html');if(process.argv.includes('--dev'))window.webContents.openDevTools({mode:'detach'});
});
app.on('window-all-closed',()=>app.quit());app.on('before-quit',()=>{for(const id of workspace.processes.keys())workspace.cancel(id);});
