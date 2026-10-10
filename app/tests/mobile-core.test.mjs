import test from "node:test";
import assert from "node:assert/strict";
import {number, percent, safeURL, escapeHTML, kind, marketMatches, candleSeries, alertPayload, timestamp, supportsSubscriptions} from "../web/static/mobile-core.js";

test("subscriptions select USD-M contracts independently of quote collection",()=>{
  const asset={asset_type:"crypto",venue:"BINANCE",currency:"USDT",segment:"FUTURES",enabled:false};
  assert.equal(supportsSubscriptions(asset),true);
  assert.equal(supportsSubscriptions({...asset,segment:"SPOT"}),false);
  assert.equal(supportsSubscriptions({...asset,currency:"USD"}),false);
  assert.equal(supportsSubscriptions({...asset,asset_type:"stock"}),false);
  assert.equal(supportsSubscriptions({...asset,segment:"USD_M"}),true);
});

test("missing numeric fields are never presented as zero",()=>{
  for(const value of [null,undefined,"",NaN,Infinity]) {assert.equal(number(value),"—");assert.equal(percent(value),"—");}
  assert.equal(number(0),"0");assert.equal(percent(0),"0%");
});
test("provider text and links cannot inject HTML or script",()=>{
  assert.equal(safeURL("javascript:alert(1)"),null);
  assert.equal(safeURL("data:text/html,test"),null);
  assert.equal(safeURL("https://example.com/news"),"https://example.com/news");
  assert.equal(escapeHTML('<img src=x onerror="alert(1)">'),"&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
});
test("Spot, perpetual futures, and stocks remain distinct",()=>{
  assert.equal(kind({asset_type:"crypto",segment:"SPOT"}),"Spot");
  assert.equal(kind({asset_type:"crypto",segment:"FUTURES"}),"合约");
  assert.equal(kind({asset_type:"crypto",segment:"USDT_PERPETUAL"}),"合约");
  assert.equal(kind({asset_type:"stock",segment:"KOSPI"}),"股票");
  assert.equal(marketMatches({asset_type:"crypto",currency:"USD"},"US"),false);
});
test("step alerts require a real anchor; threshold alerts omit it",()=>{
  const form={asset_id:"2",operator:"step",value:"10",cooldown_seconds:"300",step_anchor:"100"};
  assert.equal(alertPayload(form).step_anchor,100);
  assert.throws(()=>alertPayload({...form,step_anchor:""}));
  assert.throws(()=>alertPayload({...form,value:"0"}));
  assert.throws(()=>alertPayload({...form,cooldown_seconds:"1.5"}));
  assert.throws(()=>alertPayload({...form,asset_id:""}));
  assert.equal("step_anchor" in alertPayload({...form,operator:"crossing_up"}),false);
});
test("SQLite timestamps are interpreted as UTC",()=>{
  assert.equal(timestamp("2026-09-01T12:00:00").toISOString(),"2026-09-01T12:00:00.000Z");
  assert.equal(timestamp("2026-09-01T20:00:00+08:00").toISOString(),"2026-09-01T12:00:00.000Z");
  assert.equal(timestamp(null),null);
});
test("candlesticks use only complete and consistent real OHLC rows",()=>{
  const rows=[
    {date:"2026-09-02",open:100,high:110,low:90,close:95},
    {date:"2026-09-01",open:90,high:105,low:88,close:100},
    {date:"2026-09-03",open:100,high:null,low:90,close:95},
    {date:"2026-09-04",open:100,high:99,low:90,close:101},
  ];
  assert.deepEqual(candleSeries(rows).map(row=>[row.date,row.close>row.open]),[
    ["2026-09-01",true],["2026-09-02",false],
  ]);
});
