import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createAppUpdater} from "../web/static/app-update.js";

const version="2026.10.11.3",target="2026.10.11.4";
function harness({href="https://radar.example/#home",storage,blocked=false,online=true}={}){
  let held=blocked,connected=online;
  const memory=new Map(),reloads=[],warnings=[];
  const local=storage||{getItem:key=>memory.get(key),setItem:(key,value)=>memory.set(key,value)};
  const updater=createAppUpdater({version,location:{href},storage:()=>local,
    online:()=>connected,blocked:()=>held,reload:url=>reloads.push(url),
    waiting:()=>{},stalled:()=>warnings.push("stopped"),now:()=>1000000});
  return {updater,reloads,warnings,storage:local,unblock:()=>held=false,connect:()=>connected=true};
}
test("unchanged or invalid versions never reload, including first worker installation",()=>{
  const h=harness();
  for(const value of [version,null,"",{},"https://other.example","x".repeat(200)])h.updater.offer(value);
  assert.deepEqual(h.reloads,[]);
});
test("stale HTTP cache cannot produce a second reload after navigation",()=>{
  const first=harness();first.updater.offer(target);first.updater.offer(target);
  assert.equal(first.reloads.length,1);
  assert.equal(new URL(first.reloads[0]).searchParams.get("v"),target);
  const second=harness({href:first.reloads[0],storage:first.storage});
  for(let i=0;i<20;i++)second.updater.offer(target);
  assert.deepEqual(second.reloads,[]);assert.equal(second.warnings.length,1);
});
test("blocked session storage uses a durable URL guard",()=>{
  const storage={getItem:()=>{throw new Error("blocked");},setItem:()=>{throw new Error("blocked");}};
  const first=harness({storage});first.updater.offer(target);
  const second=harness({storage,href:first.reloads[0]});second.updater.offer(target);
  assert.equal(first.reloads.length,1);assert.equal(second.reloads.length,0);
});
test("mixed backend versions are bounded to two refresh attempts per ten minutes",()=>{
  let h=harness();
  for(const next of [target,"2026.10.11.5","2026.10.11.6"]){
    h.updater.offer(next);
    if(next!=="2026.10.11.6")h=harness({href:h.reloads[0],storage:h.storage});
  }
  assert.deepEqual(h.reloads,[]);
});
test("writes and offline state defer rather than lose a pending update",()=>{
  const h=harness({blocked:true,online:false});h.updater.offer(target);
  assert.equal(h.updater.pending,true);assert.equal(h.reloads.length,0);
  h.connect();h.updater.apply();assert.equal(h.reloads.length,0);
  h.unblock();assert.equal(h.updater.apply(),true);assert.equal(h.reloads.length,1);
});
test("HTML, imports and worker cache use the release version consistently",()=>{
  const release=readFileSync(new URL("../web/version.txt",import.meta.url),"utf8").trim();
  const main=readFileSync(new URL("../web/static/mobile.js",import.meta.url),"utf8");
  const html=readFileSync(new URL("../web/mobile.html",import.meta.url),"utf8");
  const sw=readFileSync(new URL("../web/sw.js",import.meta.url),"utf8");
  assert.ok(main.includes(`APP_VERSION = "${release}"`));
  for(const file of ["mobile.js","mobile.css"])assert.ok(html.includes(`/static/${file}?v=${release}`));
  for(const match of main.matchAll(/from "\.\/([^"?]+)\?v=([^"?]+)"/g))assert.equal(match[2],release);
  assert.ok(sw.includes(`VERSION = "${release}"`));
});
