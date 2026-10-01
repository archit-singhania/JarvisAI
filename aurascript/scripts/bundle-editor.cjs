const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
fs.mkdirSync(path.join(root,'src/vendor'),{recursive:true});
fs.cpSync(path.join(root,'node_modules/monaco-editor/min/vs'),path.join(root,'src/vendor/vs'),{recursive:true});
fs.copyFileSync(path.join(root,'node_modules/monaco-editor/LICENSE'),path.join(root,'src/vendor/monaco-LICENSE'));
