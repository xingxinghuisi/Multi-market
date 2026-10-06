import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import {readFileSync, existsSync} from "node:fs";

const source = readFileSync(new URL("../web/sw.js", import.meta.url), "utf8");
function worker(overrides={}) {
  const handlers = {}, writes = [], deleted = [], lifecycle = [];
  const scope = {
    URL, Response,
    self: {location:{origin:"https://radar.example"}, clients:{claim:async()=>lifecycle.push("claimed")},
      skipWaiting:async()=>lifecycle.push("waiting skipped"), addEventListener:(event,handler)=>handlers[event]=handler},
    caches: {
      open:async()=>({addAll:async urls=>writes.push(...urls), put:async request=>writes.push(request.url)}),
      keys:async()=>["market-radar-shell-v0","market-radar-shell-v1","unrelated-app"],
      delete:async key=>deleted.push(key), match:async()=>new Response("offline shell"),
    },
    fetch:async()=>new Response("online shell"), ...overrides,
  };
  vm.runInNewContext(source,scope);
  return {handlers,writes,deleted,lifecycle};
}

test("shell assets are cached before an update activates",async()=>{
  const {handlers,writes,lifecycle}=worker();let work;
  handlers.install({waitUntil:promise=>work=promise});await work;
  assert.ok(writes.includes("/"));
  assert.deepEqual(lifecycle,["waiting skipped"]);
  for(const url of writes){
    assert.ok(!url.startsWith("/api/")&&!url.includes("legacy"));
    assert.ok(existsSync(new URL(url==="/"?"../web/mobile.html":`../web${url}`,import.meta.url)),url);
  }
});
test("sensitive paths, writes, queries and other origins bypass the cache",()=>{
  const {handlers}=worker();
  for(const [url,method] of [["/api/client-profile","GET"],["/api/notifications","GET"],["/api/market/latest","GET"],["/api/watchlist","POST"],["/legacy","GET"],["/?token=secret","GET"],["https://other.example/","GET"]]) {
    let intercepted=false;
    handlers.fetch({request:{url:new URL(url,"https://radar.example").href,method},respondWith:()=>intercepted=true});
    assert.equal(intercepted,false,url);
  }
});
test("offline navigation returns only the cached public shell",async()=>{
  const {handlers}=worker({fetch:async()=>{throw new Error("offline");}});let response;
  handlers.fetch({request:{url:"https://radar.example/",method:"GET"},respondWith:promise=>response=promise});
  assert.equal(await (await response).text(),"offline shell");
});
test("activation removes old Radar caches while preserving unrelated caches",async()=>{
  const {handlers,deleted}=worker();let work;
  handlers.activate({waitUntil:promise=>work=promise});await work;
  assert.deepEqual(deleted,["market-radar-shell-v0","market-radar-shell-v1"]);
});
