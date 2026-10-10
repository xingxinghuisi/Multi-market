import test from "node:test";
import assert from "node:assert/strict";
import {whalePage,matchingWhaleMarkets} from "../web/static/whales.js";

test("market search uses the verified catalog, includes non-equities and excludes existing subscriptions",()=>{
  const markets=[{coin:"xyz:KORU",name:"韩国 ETF"},{coin:"xyz:GOLD",name:"GOLD 永续合约"},{coin:"xyz:AAPL",name:"AAPL 永续合约"}];
  const subscriptions=[{coin:"xyz:KORU",enabled:false}];
  assert.deepEqual(matchingWhaleMarkets(markets,subscriptions," gold "),[markets[1]]);
  assert.deepEqual(matchingWhaleMarkets(markets,subscriptions,"aapl"),[markets[2]]);
  assert.deepEqual(matchingWhaleMarkets(markets,subscriptions,"KORU"),[]);
  assert.deepEqual(matchingWhaleMarkets(markets,subscriptions,"fake"),[]);
  const html=whalePage({markets,subscriptions},true);
  assert.ok(html.includes("可选 3 个经官方目录核验的市场"));
  assert.ok(html.includes('value="xyz:GOLD"'));
  assert.ok(!html.includes("股票及 ETF 关联永续"));
});

test("unconfigured service shows coverage and never invents wallets or markets",()=>{
  const html=whalePage({},false);
  assert.ok(html.includes("服务未连接"));
  assert.ok(html.includes("等待巨鲸服务"));
  assert.ok(html.includes("xyz:KORU 与 Binance KORUUSDT 是不同市场"));
  assert.ok(!html.includes("0x123"));
});

test("unrealized P&L distinguishes profit, loss, zero and unavailable old records",()=>{
  for(const [pnl,display] of [["1234.50","+$1,234.50"],["-987.65","-$987.65"],["0","$0.00"],[undefined,"未提供"],[null,"未提供"],["NaN","未提供"]]){
    const html=whalePage({positions:[{coin:"xyz:KORU",address:"Synthetic test",qty:"1",notional_usd:"1000",unrealized_pnl:pnl}]},true);
    assert.match(html,new RegExp(`当前未实现盈亏<strong[^>]*>${display.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}</strong>`));
  }
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
