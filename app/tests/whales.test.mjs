import test from "node:test";
import assert from "node:assert/strict";
import {whalePage} from "../web/static/whales.js";

test("unconfigured service shows coverage and never invents wallets or markets",()=>{
  const html=whalePage({},false);
  assert.ok(html.includes("服务未连接"));
  assert.ok(html.includes("等待巨鲸服务"));
  assert.ok(html.includes("xyz:KORU 与 Binance KORUUSDT 是不同市场"));
  assert.ok(!html.includes("0x123"));
});
test("known wallets are escaped and existing subscriptions cannot be accidentally added twice",()=>{
  const html=whalePage({runtime:{online:true,connected:true},markets:[{coin:"xyz:KORU",name:"ETF"}],
    subscriptions:[{id:1,coin:"xyz:KORU",enabled:true,min_position_usd:1000000,cooldown_seconds:300}],
    positions:[{address:'<script>alert(1)</script>',coin:"xyz:KORU",qty:"100000",notional_usd:"2000000",entry_price:"19.5",leverage:"10",source:"Test",stale:true}],
    events:[{address:"test",coin:"xyz:KORU",kind:"discovered",side:"long",notional_usd:"2000000",previous_qty:null}]},true);
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
  assert.equal((html.match(/class="whale-subscription-form"/g)||[]).length,1);
  assert.ok(html.includes("数据已过期"));
  assert.ok(html.includes("首次核验，无法确认实际开仓时间"));
  assert.ok(html.includes("10x"));
});
