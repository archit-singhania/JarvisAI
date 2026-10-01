'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),esbuild=require('esbuild');
const root=path.resolve(__dirname,'..'),output=path.join(root,'src/vendor');
(async()=>{
  // All output is generated from the locked source dependencies. Removing
  // stale bundles prevents a mixed-version editor after dependency upgrades.
  if(!output.startsWith(root+path.sep))throw new Error('Invalid editor output');
  await fs.rm(output,{recursive:true,force:true});await fs.mkdir(output,{recursive:true});
  const shared={bundle:true,minify:true,format:'iife',target:'chrome140',logLevel:'warning',loader:{'.ttf':'file'}};
  await esbuild.build({...shared,entryPoints:[path.join(root,'scripts/editor-entry.mjs')],globalName:'monaco',outfile:path.join(output,'editor.js')});
  for(const [name,source]of Object.entries({editor:'editor/editor.worker.js',json:'language/json/json.worker.js',css:'language/css/css.worker.js',html:'language/html/html.worker.js',typescript:'language/typescript/ts.worker.js'})){
    await esbuild.build({...shared,entryPoints:[path.join(root,'node_modules/monaco-editor/esm/vs',source)],outfile:path.join(output,name+'.worker.js')});
  }
  await fs.copyFile(path.join(root,'node_modules/monaco-editor/LICENSE'),path.join(output,'monaco-LICENSE'));
  await fs.copyFile(path.join(root,'node_modules/dompurify/LICENSE'),path.join(output,'dompurify-LICENSE'));
  console.log('Offline Monaco and language workers bundled from locked dependencies.');
})().catch(error=>{console.error(error);process.exit(1);});
