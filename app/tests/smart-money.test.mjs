import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {smartMoneyPanel,smartMoneyValuation} from '../web/static/smart-money.js';

const asset={id:1,symbol:'KORUUSDT',venue:'BINANCE',asset_type:'crypto',segment:'FUTURES',currency:'USDT'};
const data={market:'binance:usdm:KORUUSDT',source_updated_at:new Date(Date.now()-8*3600000).toISOString(),fetched_at:new Date().toISOString(),
  source_time_older_than_limit:true,source_time_warning_seconds:900,total_traders:20,total_position_usd:1000000,long_short_ratio:.5,
  sides:{long:{traders:10,whales:3,quantity:100,profitable_whales:0,whale_avg_entry_price:14},short:{traders:10,whales:4,profitable_whales:null}}};

test('the card is opt-in and only appears for Binance USDT contracts',()=>{
  const html=smartMoneyPanel(asset);
  assert.match(html,/查看聪明钱快照/);
  assert.match(html,/data-action="smart-money-load"/);
  assert.equal(smartMoneyPanel({...asset,segment:'SPOT'}),'');
  assert.equal(smartMoneyPanel({...asset,venue:'LIGHTER'}),'');
});
test('stale aggregate time, real zero and missing values remain distinct',()=>{
  const html=smartMoneyPanel(asset,{smartMoney:data});
  assert.match(html,/源时间口径待核实/);
  assert.match(html,/币安返回时间（含义待核实）/);
  assert.match(html,/最近成功读取时间/);
  assert.doesNotMatch(html,/已过期|实时持仓/);
  assert.match(html,/盈利巨鲸人数<\/dt><dd>0<\/dd>/);
  assert.match(html,/盈利巨鲸人数<\/dt><dd>未提供<\/dd>/);
  assert.match(html,/不提供个人地址、杠杆或逐笔开平仓/);
});
test('failed refresh preserves the previous data and escapes messages',()=>{
  const html=smartMoneyPanel(asset,{smartMoney:{...data,refresh_error:'<script>bad</script>'},smartMoneyError:'<img src=x>'});
  assert.match(html,/保留上次快照/);
  assert.match(html,/&lt;script&gt;/);
  assert.doesNotMatch(html,/<script>|<img src=x>/);
  assert.match(html,/总持仓名义价值/);
});

const now=Date.parse('2026-10-18T00:00:00Z');
const cases=JSON.parse(fs.readFileSync(new URL('./fixtures/smart-money-pnl.json',import.meta.url),'utf8'));
for(const [index,c] of cases.entries()){
  test(`valuation agrees with the shared server contract: case ${index+1}`,()=>{
    const values={quantity:c.quantity,avg_entry_price:c.entry,whale_quantity:c.quantity,whale_avg_entry_price:c.entry};
    const snapshot={...data,fetched_at:new Date(now).toISOString(),sides:{long:values,short:values}};
    const quote={asset_id:1,price:c.price,event_time:new Date(now).toISOString()};
    const result=smartMoneyValuation(asset,snapshot,quote,now).sides?.[c.long?'long':'short']?.whales_usdt??null;
    if(c.expected===null)assert.equal(result,null);
    else assert.ok(Math.abs(result-c.expected)<1e-9,`${result} != ${c.expected}`);
  });
}

test('quotes from Spot, other markets, old observations and failed refreshes cannot show money',()=>{
  const snapshot={...data,fetched_at:new Date(now).toISOString()};
  const quote={asset_id:1,symbol:'KORUUSDT',venue:'BINANCE',segment:'FUTURES',price:12,event_time:new Date(now).toISOString()};
  for(const changed of [{...quote,asset_id:2},{...quote,segment:'SPOT'},{...quote,venue:'LIGHTER'},
    {...quote,event_time:new Date(now-121000).toISOString()},{...quote,price:NaN}]){
    assert.deepEqual(smartMoneyValuation(asset,snapshot,changed,now).sides,{});
  }
  assert.deepEqual(smartMoneyValuation(asset,{...snapshot,fetched_at:new Date(now-901000).toISOString()},quote,now).sides,{});
  assert.deepEqual(smartMoneyValuation(asset,{...snapshot,refresh_error:'unavailable'},quote,now).sides,{});
});

test('API valuation price fallback expires, and the card labels computed amounts separately from counts',()=>{
  const snapshot={...data,fetched_at:new Date(now).toISOString(),pnl:{asset_id:1,price:14,quote_at:new Date(now).toISOString()},
    sides:{long:{whales:3,whale_quantity:75,whale_avg_entry_price:14},short:{whales:4,whale_quantity:150,whale_avg_entry_price:19}}};
  assert.equal(smartMoneyValuation(asset,snapshot,undefined,now).sides.long.whales_usdt,0);
  assert.equal(smartMoneyValuation(asset,snapshot,undefined,now+121000).reason,'stale_quote');
  const current={...snapshot,fetched_at:new Date().toISOString(),pnl:{...snapshot.pnl,quote_at:new Date().toISOString()}};
  const html=smartMoneyPanel(asset,{smartMoney:current});
  assert.match(html,/巨鲸浮盈亏（计算，USDT）/);
  assert.match(html,/data-smart-pnl="long.whales_usdt">\$0<\/dd>/);
  assert.match(html,/不含手续费、资金费/);
  assert.match(html,/参考最新成交价/);
  assert.match(html,/取得两次有效监控快照/);
});
