import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs/promises';
const handlers={};
const shell=new Response('<!doctype html>',{headers:{'Content-Type':'text/html'}});
const scope={self:{location:{origin:'https://personal.example'},addEventListener:(type,fn)=>{handlers[type]=fn}},URL,Response,caches:{match:async key=>key==='/iphone/'?shell.clone():undefined},fetch:async()=>{throw Error('offline')}};
vm.runInNewContext(await fs.readFile(new URL('../pwa/sw.js',import.meta.url),'utf8'),scope);
async function offline(url,mode='no-cors'){
 let result;handlers.fetch({request:{url,method:'GET',mode},respondWith:p=>{result=p},waitUntil:()=>{}});return result?await result:null;
}
assert.equal(await offline('https://accounts.google.com/gsi/client'),null,'external provider scripts must pass through, never become HTML');
assert.equal(await offline('https://personal.example/iphone/api/status'),null,'authenticated API must never use offline shell');
const css=await offline('https://personal.example/iphone/missing.css');assert.equal(css.status,503);assert.equal(css.headers.get('Content-Type'),'text/plain');
const script=await offline('https://personal.example/iphone/missing.js');assert.equal(script.status,503);assert.doesNotMatch(await script.text(),/doctype/);
const navigation=await offline('https://personal.example/iphone/deep-link','navigate');assert.match(await navigation.text(),/doctype/);
console.log('Offline navigation fallback preserves API, provider script and stylesheet boundaries.');
