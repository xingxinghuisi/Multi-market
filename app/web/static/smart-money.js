import {escapeHTML as e, number as n, supportsSubscriptions} from "./mobile-core.js?v=2026.10.14.1";

const money=value=>value==null?"未提供":`$${n(value,8)}`;
const count=value=>value==null?"未提供":n(value,0);
const stamp=value=>value?new Date(value).toLocaleString("zh-CN"):"未提供";
function group(side,label) {
  const rows=[["交易员人数",count(side.traders)],["持仓数量",side.quantity==null?"未提供":n(side.quantity,8)],
    ["交易员平均开仓价",money(side.avg_entry_price)],["盈利交易员人数",count(side.profitable_traders)],
    ["巨鲸人数",count(side.whales)],["巨鲸持仓数量",side.whale_quantity==null?"未提供":n(side.whale_quantity,8)],
    ["巨鲸平均开仓价",money(side.whale_avg_entry_price)],["盈利巨鲸人数",count(side.profitable_whales)]];
  return `<section><h3>${e(label)}</h3><dl>${rows.map(([key,value])=>`<div><dt>${e(key)}</dt><dd>${e(value)}</dd></div>`).join("")}</dl></section>`;
}

export function smartMoneyPanel(asset,detail={}) {
  if(!supportsSubscriptions(asset))return "";
  const data=detail?.smartMoney;
  const lagged=data&&(data.source_time_older_than_limit||Date.now()-Date.parse(data.source_updated_at)>data.source_time_warning_seconds*1000);
  const status=data?"源时间口径待核实":"按需查看";
  const button=`<button type="button" data-action="smart-money-load" data-id="${asset.id}"${detail?.smartMoneyLoading?" disabled":""}>${detail?.smartMoneyLoading?"读取中…":data?"刷新快照":"查看聪明钱快照"}</button>`;
  return `<div class="section-title"><h2>币安聪明钱</h2><span class="tag">${status}</span></div><div class="card smart-money-card" aria-busy="${Boolean(detail?.smartMoneyLoading)}">
    <p class="quote-caption">币安筛选的交易员与巨鲸持仓汇总，独立于链上钱包监控。</p>
    ${detail?.smartMoneyError?`<div class="notice error" role="alert">${e(detail.smartMoneyError)}</div>`:""}
    ${data?`${lagged?'<div class="notice">币安返回的时间字段较旧，期间数值可能仍变化。刷新周期尚未核实，不用于实时提醒。</div>':""}
      ${data.refresh_error?`<div class="notice error">更新暂不可用，保留上次快照。${e(data.refresh_error)}</div>`:""}
      <p class="quote-caption">币安返回时间（含义待核实）：${e(stamp(data.source_updated_at))}<br>最近成功读取时间：${e(stamp(data.fetched_at))}</p>
      <div class="whale-numbers"><span>交易员总数<strong>${count(data.total_traders)}</strong></span><span>总持仓名义价值<strong>${data.total_position_usd==null?"未提供":`$${n(data.total_position_usd,2)}`}</strong></span><span>多空比<strong>${data.long_short_ratio==null?"未提供":n(data.long_short_ratio,4)}</strong></span></div>
      <div class="smart-money-sides">${group(data.sides?.long||{},"多头")}${group(data.sides?.short||{},"空头")}</div>
      <p class="quote-caption">数量为合约基础单位，不是保证金。盈利人数不等于盈亏金额；此处不提供个人地址、杠杆或逐笔开平仓。</p>`:
      '<p>查看多空人数、巨鲸人数、持仓数量与平均开仓价。没有数据时不推断市场没有巨鲸。</p>'}
    <div class="actions">${button}<a href="https://www.binance.com/zh-CN/smart-money/signal/${e(asset.symbol)}" target="_blank" rel="noopener noreferrer">币安原页面 ↗</a></div>
  </div>`;
}
