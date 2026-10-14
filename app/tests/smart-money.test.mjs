import test from 'node:test';
import assert from 'node:assert/strict';
import {smartMoneyPanel} from '../web/static/smart-money.js';

const asset={id:1,symbol:'KORUUSDT',venue:'BINANCE',asset_type:'crypto',segment:'FUTURES',currency:'USDT'};
const data={source_updated_at:new Date(Date.now()-8*3600000).toISOString(),fetched_at:new Date().toISOString(),
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
