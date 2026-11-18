/* Cache public application files only. Private API responses never enter caches. */
const CACHE='wednesday-shell-v2';
const SHELL=['./','index.html','styles.css','accessibility.css','motion.css','motion.js','app.js','continuity.js','memories.js','routines.js','meetings.js','expansion.js','assets/wednesday.svg'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL))));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
  for(const name of await caches.keys())if(name.startsWith('wednesday-shell-')&&name!==CACHE)await caches.delete(name);
  await self.clients.claim();
})()));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url),scope=new URL(self.registration.scope);
  if(event.request.method!=='GET'||url.origin!==scope.origin||!url.pathname.startsWith(scope.pathname))return;
  const relative=url.pathname.slice(scope.pathname.length);
  if(!SHELL.includes(relative||'./'))return;
  event.respondWith((async()=>{
    try{return await fetch(event.request);}
    catch{
      const cache=await caches.open(CACHE);
      return await cache.match(event.request,{ignoreSearch:true})||await cache.match(new URL(relative||'./',scope).href)||Response.error();
    }
  })());
});
