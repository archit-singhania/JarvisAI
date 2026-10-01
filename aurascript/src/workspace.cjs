'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),{spawn}=require('node:child_process'),crypto=require('node:crypto');
class WorkspaceBridge{
  constructor(){this.root=null;this.processes=new Map();}
  async select(root){this.root=await fs.realpath(root);return this.root;}
  contains(target){if(!this.root)return false;const relative=path.relative(this.root,target);return relative===''||(!path.isAbsolute(relative)&&relative!=='..'&&!relative.startsWith('..'+path.sep));}
  async resolve(target,write=false){
    if(!this.root)throw new Error('Select a workspace first.');
    const requested=path.resolve(this.root,target);
    if(!this.contains(requested))throw new Error('Path is outside the selected workspace.');
    let canonical;
    try{canonical=await fs.realpath(requested);}catch(error){if(!write||error.code!=='ENOENT')throw error;canonical=path.join(await fs.realpath(path.dirname(requested)),path.basename(requested));}
    if(!this.contains(canonical))throw new Error('Linked path leaves the selected workspace.');
    return canonical;
  }
  async read(target){const file=await this.resolve(target);const stat=await fs.stat(file);if(stat.size>4*1024*1024)throw new Error('File exceeds 4 MB editor limit.');return fs.readFile(file,'utf8');}
  async create(target){const file=await this.resolve(target,true);try{await fs.writeFile(file,'',{encoding:'utf8',flag:'wx'});}catch(error){if(error.code==='EEXIST')throw new Error('A file already exists at that path. Its contents were preserved.');throw error;}return true;}
  async write(target,content){if(typeof content!=='string'||Buffer.byteLength(content)>4*1024*1024)throw new Error('Invalid or oversized file.');const file=await this.resolve(target,true);const temp=path.join(path.dirname(file),'.aura-'+crypto.randomUUID()+'.tmp');await fs.writeFile(temp,content,'utf8');try{await fs.rename(temp,file);}catch(error){await fs.unlink(temp).catch(()=>{});throw error;}return true;}
  async list(target){const directory=await this.resolve(target);const entries=await fs.readdir(directory,{withFileTypes:true});return entries.filter(e=>!['.git','node_modules','.venv','venv','__pycache__','dist','build'].includes(e.name)).slice(0,2000).map(e=>({name:e.name,path:path.join(directory,e.name),isDir:e.isDirectory()})).sort((a,b)=>Number(b.isDir)-Number(a.isDir)||a.name.localeCompare(b.name));}
  async execute(command,args=[],onData=()=>{},shell=false){
    if(!this.root)throw new Error('Select a workspace first.');
    const id=crypto.randomUUID();const child=spawn(command,args,{cwd:this.root,shell,windowsHide:true,detached:process.platform!=='win32'});this.processes.set(id,child);let out='',settled=false;
    const completion=new Promise(resolve=>{const finish=(ok,code,error)=>{if(settled)return;settled=true;this.processes.delete(id);resolve({id,ok,code,out,error});};child.stdout?.on('data',b=>{const text=b.toString();out=(out+text).slice(-2*1024*1024);onData({id,stream:'stdout',text});});child.stderr?.on('data',b=>{const text=b.toString();out=(out+text).slice(-2*1024*1024);onData({id,stream:'stderr',text});});child.on('error',error=>finish(false,null,error.message));child.on('close',code=>finish(code===0,code));});
    return {id,completion};
  }
  async terminal(command,onData){if(typeof command!=='string'||!command.trim()||command.length>5000)throw new Error('Enter a valid terminal command.');return this.execute(command,[],onData,true);}
  cancel(id){
    const child=this.processes.get(id);if(!child)return false;
    if(process.platform==='win32'){
      const fallback=setTimeout(()=>{if(this.processes.has(id))child.kill('SIGTERM');},1500);
      const killer=spawn('taskkill',['/pid',String(child.pid),'/t','/f'],{windowsHide:true});
      killer.once('error',()=>{clearTimeout(fallback);child.kill('SIGTERM');});
      killer.once('close',code=>{if(code!==0)child.kill('SIGTERM');clearTimeout(fallback);});
      child.once('close',()=>clearTimeout(fallback));
    }else{
      try{process.kill(-child.pid,'SIGTERM');}catch{child.kill('SIGTERM');}
    }
    return true;
  }
  async git(args){
    const prefix=['-c','safe.directory='+this.root];
    const probe=await this.execute('git',[...prefix,'rev-parse','--show-toplevel']);const repository=await probe.completion;
    if(!repository.ok)return repository;
    const canonical=await fs.realpath(repository.out.trim());
    const normalize=value=>process.platform==='win32'?value.toLowerCase():value;
    if(normalize(canonical)!==normalize(this.root))return {ok:false,error:'Select the repository root before using Git actions.',out:''};
    const run=await this.execute('git',[...prefix,...args]);return run.completion;
  }
  async checkpoint(message){if(typeof message!=='string'||!message.trim()||message.length>300)throw new Error('Supply a checkpoint message.');const staged=await this.git(['add','--all']);if(!staged.ok)return staged;return this.git(['commit','-m',message]);}
}
module.exports={WorkspaceBridge};
