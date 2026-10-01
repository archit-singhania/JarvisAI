const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('aura',{
  bootstrap:()=>ipcRenderer.invoke('bootstrap'),api:(route,method,body)=>ipcRenderer.invoke('backend',route,method,body),
  openFolder:()=>ipcRenderer.invoke('open-folder'),readFile:path=>ipcRenderer.invoke('read-file',path),writeFile:(path,content)=>ipcRenderer.invoke('write-file',path,content),listDir:path=>ipcRenderer.invoke('list-dir',path),
  terminal:command=>ipcRenderer.invoke('terminal',command),cancelProcess:id=>ipcRenderer.invoke('cancel-process',id),checkpoint:message=>ipcRenderer.invoke('checkpoint',message),gitLog:()=>ipcRenderer.invoke('git-log'),gitDiff:commit=>ipcRenderer.invoke('git-diff',commit),selectImage:()=>ipcRenderer.invoke('select-image'),export:()=>ipcRenderer.invoke('export'),
  onTerminalData:callback=>{const listener=(_event,data)=>callback(data);ipcRenderer.on('terminal-data',listener);return()=>ipcRenderer.removeListener('terminal-data',listener);},
  onTerminalExit:callback=>{const listener=(_event,data)=>callback(data);ipcRenderer.on('terminal-exit',listener);return()=>ipcRenderer.removeListener('terminal-exit',listener);}
});
