globalThis.MonacoEnvironment={getWorker(_moduleId,label){
  const worker=['json','html','typescript'].includes(label)?label:label==='javascript'?'typescript':['css','scss','less'].includes(label)?'css':'editor';
  return new Worker(new URL('vendor/'+worker+'.worker.js',document.baseURI));
}};
import 'monaco-editor/basic-languages/monaco.contribution.js';
import 'monaco-editor/language/json/monaco.contribution.js';
import 'monaco-editor/language/typescript/monaco.contribution.js';
import 'monaco-editor/language/html/monaco.contribution.js';
import 'monaco-editor/language/css/monaco.contribution.js';
export * from 'monaco-editor/editor/editor.api.js';
