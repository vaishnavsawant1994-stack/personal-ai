const CACHE='personal-ai-iphone-v28';
const SHELL=['/iphone/','/iphone/manifest.webmanifest','/iphone/layout.css','/iphone/design-system.css','/iphone/primitives.css','/iphone/memory-experiences.css','/iphone/memory-experiences.js'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  // Never substitute our HTML for provider scripts, API data, CSS or images.
  if(event.request.method!=='GET'||url.origin!==self.location.origin||
     !url.pathname.startsWith('/iphone/')||url.pathname.startsWith('/iphone/api/'))return;
  event.respondWith(fetch(event.request).then(response=>{
    if(response.ok&&SHELL.includes(url.pathname)){
      const copy=response.clone();event.waitUntil(caches.open(CACHE).then(cache=>cache.put(event.request,copy)));
    }
    return response;
  }).catch(async()=>{
    const cached=await caches.match(event.request);
    if(cached)return cached;
    if(event.request.mode==='navigate'){
      const shell=await caches.match('/iphone/');if(shell)return shell;
    }
    return new Response('Unavailable offline',{status:503,headers:{'Content-Type':'text/plain'}});
  }));
});
