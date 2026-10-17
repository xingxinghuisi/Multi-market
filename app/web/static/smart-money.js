import {escapeHTML as e, number as n, supportsSubscriptions, timestamp} from "./mobile-core.js?v=2026.10.18.1";

const money=value=>value==null?"未提供":`$${n(value,8)}`;
const count=value=>value==null?"未提供":n(value,0);
const stamp=value=>value?new Date(value).toLocaleString("zh-CN"):"未提供";
const signedMoney=value=>!signedValid(value)?"未提供":`${value<0?"-":value>0?"+":""}$${n(Math.abs(value),2)}`;
const numeric=value=>typeof value==="number"&&Number.isFinite(value)&&value>=0&&value<=1e30;
const signedValid=value=>typeof value==="number"&&Number.isFinite(value)&&Math.abs(value)<=1e30;

export function smartMoneyValuation(asset,data,quote,now=Date.now()) {
  const result={status:"unavailable",reason:"missing_quote",price:null,quote_at:null,sides:{}};
  if(!supportsSubscriptions(asset)||asset.enabled===false||data?.market!==`binance:usdm:${asset.symbol}`){result.reason="market_mismatch";return result;}
  if(data.refresh_error){result.reason="source_error";return result;}
  const read=timestamp(data.fetched_at)?.getTime(),readAge=now-read;
  if(!Number.isFinite(readAge)||readAge< -60000||readAge>900000){result.reason="stale_snapshot";return result;}
  // The API's validated price is a fallback when the initial quote list has not arrived yet.
  const candidate=quote??(data.pnl?.price!=null?{asset_id:data.pnl.asset_id,price:data.pnl.price,event_time:data.pnl.quote_at}:null);
  if(!candidate)return result;
  if(candidate.asset_id!==asset.id||(candidate.symbol&&candidate.symbol!==asset.symbol)||
    (candidate.venue&&candidate.venue!==asset.venue)||(candidate.segment&&candidate.segment!==asset.segment)){
    result.reason="market_mismatch";return result;
  }
  const time=timestamp(candidate.event_time),age=now-time?.getTime();result.quote_at=time?.toISOString()??null;
  if(!Number.isFinite(age)||age< -60000||age>120000){result.reason="stale_quote";return result;}
  if(!numeric(candidate.price)||candidate.price<=0){result.reason="invalid_price";return result;}
  result.price=candidate.price;
  const calculate=(qty,entry,isLong)=>{
    if(!numeric(qty))return null;if(qty===0)return 0;
    if(!numeric(entry)||entry<=0)return null;
    const value=(result.price-entry)*qty*(isLong?1:-1);
    return signedValid(value)?value:null;
  };
  for(const side of ["long","short"]){
    const values=data.sides?.[side]||{};
    result.sides[side]={traders_usdt:calculate(values.quantity,values.avg_entry_price,side==="long"),
      whales_usdt:calculate(values.whale_quantity,values.whale_avg_entry_price,side==="long")};
  }
  result.status=Object.values(result.sides).every(side=>Object.values(side).every(v=>v!==null))?"ok":"partial";
  result.reason=result.status==="ok"?null:"missing_fields";return result;
}

function pnlMeta(pnl) {
  const reason={missing_quote:"尚无该合约行情",market_mismatch:"市场标识不匹配",source_error:"聪明钱更新暂不可用",stale_snapshot:"持仓快照较旧，请刷新快照",stale_quote:"成交行情较旧，暂停计算",invalid_price:"价格无效",missing_fields:"部分持仓字段未提供"}[pnl.reason];
  return `${pnl.price!=null?`参考最新成交价：${e(money(pnl.price))}<br>成交时间：${e(stamp(pnl.quote_at))}`:"浮盈亏暂不可算"}${reason?`<br>${e(reason)}`:""}`;
}

function comparisonHTML(monitoring) {
  const data=monitoring?.pnl_comparison;
  if(!data)return '<p class="quote-caption">取得两次有效监控快照后显示浮盈亏变化。</p>';
  return `<p class="quote-caption">最近监控快照浮盈亏变化<br>多头巨鲸 ${e(signedMoney(data.sides?.long?.whales_usdt))} · 空头巨鲸 ${e(signedMoney(data.sides?.short?.whales_usdt))}<br>${e(stamp(data.before_observed_at))} → ${e(stamp(data.after_observed_at))}<br>变化同时受价格、持仓和样本成员变化影响，不代表期间已实现收益。</p>`;
}

function group(side,label,pnl,sideKey) {
  const rows=[["巨鲸平均开仓价",money(side.whale_avg_entry_price)],
    ["巨鲸浮盈亏（计算，USDT）",signedMoney(pnl.sides?.[sideKey]?.whales_usdt),`${sideKey}.whales_usdt`],
    ["交易员平均开仓价",money(side.avg_entry_price)],
    ["交易员浮盈亏（计算，USDT）",signedMoney(pnl.sides?.[sideKey]?.traders_usdt),`${sideKey}.traders_usdt`],
    ["巨鲸人数",count(side.whales)],["巨鲸持仓数量",side.whale_quantity==null?"未提供":n(side.whale_quantity,8)],
    ["盈利巨鲸人数",count(side.profitable_whales)],["交易员人数",count(side.traders)],
    ["持仓数量",side.quantity==null?"未提供":n(side.quantity,8)],["盈利交易员人数",count(side.profitable_traders)]];
  return `<section><h3>${e(label)}</h3><dl>${rows.map(([key,value,field])=>`<div><dt>${e(key)}</dt><dd${field?` data-smart-pnl="${field}"`:""}>${e(value)}</dd></div>`).join("")}</dl></section>`;
}

export function smartMoneyPanel(asset,detail={},quote,monitoring) {
  if(!supportsSubscriptions(asset))return "";
  const data=detail?.smartMoney;
  const pnl=data?smartMoneyValuation(asset,detail.smartMoneyError?{...data,refresh_error:true}:data,quote):null;
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
      <p class="quote-caption" data-smart-pnl-meta>${pnlMeta(pnl)}</p>
      <div class="smart-money-sides">${group(data.sides?.long||{},"多头",pnl,"long")}${group(data.sides?.short||{},"空头",pnl,"short")}</div>
      <p class="quote-caption">浮盈亏按快照持仓和最新成交价计算，非账户结算值，不含手续费、资金费；报价与持仓快照时间分别展示。</p>
      <div data-smart-pnl-comparison>${comparisonHTML(monitoring)}</div>
      <p class="quote-caption">数量为合约基础单位，不是保证金。盈利人数不等于盈亏金额；此处不提供个人地址、杠杆或逐笔开平仓。</p>`:
      '<p>查看多空人数、巨鲸人数、持仓数量与平均开仓价。没有数据时不推断市场没有巨鲸。</p>'}
    <div class="actions">${button}<button type="button" data-action="smart-money-subscribe" data-id="${asset.id}">设置群体变化提醒</button><a href="https://www.binance.com/zh-CN/smart-money/signal/${e(asset.symbol)}" target="_blank" rel="noopener noreferrer">币安原页面 ↗</a></div>
  </div>`;
}

export function paintSmartMoney(root,asset,detail,quote,monitoring) {
  if(!detail?.smartMoney||!root.querySelector("[data-smart-pnl-meta]"))return;
  const pnl=smartMoneyValuation(asset,detail.smartMoneyError?{...detail.smartMoney,refresh_error:true}:detail.smartMoney,quote);
  root.querySelectorAll("[data-smart-pnl]").forEach(element=>{
    const [side,cohort]=element.dataset.smartPnl.split(".");
    const value=signedMoney(pnl.sides?.[side]?.[cohort]);if(element.textContent!==value)element.textContent=value;
  });
  for(const [selector,html] of [["[data-smart-pnl-meta]",pnlMeta(pnl)],["[data-smart-pnl-comparison]",comparisonHTML(monitoring)]]){
    const element=root.querySelector(selector);if(element&&element.innerHTML!==html)element.innerHTML=html;
  }
}

export function smartMoneyForm(asset,subscription) {
  const config={watch_whale_count:true,watch_whale_quantity:true,min_whale_count_change:5,min_whale_quantity_change_pct:5,cooldown_seconds:3600,...subscription?.config};
  const monitoring=subscription?.monitoring;
  const labels={waiting:"等待首次采样",baseline:"已建立对照快照",gap_reset:"采样中断后已重新建立对照",below_threshold:"本次变化未达门槛",cooldown:"本次处于提醒间隔内",sent:"本次已推送",in_app:"本次已记录站内通知",failed:"本次投递失败",pending:"投递结果待确认",paused:"已暂停",source_error:"数据源暂不可用，保留上次快照",invalid_observation:"未取得可用于比较的新快照",inactive:"已暂停",invalid_config:"配置无效，请重新保存"};
  const date=timestamp(monitoring?.checked_at),late=date&&Date.now()-date.getTime()>1800000;
  const status=monitoring?(late&&subscription.enabled?"采样较久未更新，请检查服务":labels[monitoring.status]||"等待下次采样"):"默认关闭，保存后生效";
  return `<section class="smart-money-settings"><h3>币安聪明钱群体变化</h3><p class="quote-caption">比较多空巨鲸群体的相邻快照；不是地址监控，也不是逐笔成交。</p>
    <form data-smart-money-form data-asset="${asset.id}">
      <label class="checkbox"><input type="checkbox" name="enabled"${subscription?.enabled?" checked":""}>开启群体变化提醒</label>
      <label class="checkbox"><input type="checkbox" name="watch_whale_count"${config.watch_whale_count?" checked":""}>监控巨鲸人数变化</label>
      <label>人数变化门槛（人）<input name="min_whale_count_change" type="number" min="1" max="1000000" step="1" inputmode="numeric" value="${e(String(config.min_whale_count_change))}" required></label>
      <label class="checkbox"><input type="checkbox" name="watch_whale_quantity"${config.watch_whale_quantity?" checked":""}>监控巨鲸持仓数量变化</label>
      <label>数量相对变化门槛（%）<input name="min_whale_quantity_change_pct" type="number" min="0.000001" max="10000" step="any" inputmode="decimal" value="${e(String(config.min_whale_quantity_change_pct))}" required></label>
      <label>提醒间隔（秒）<input name="cooldown_seconds" type="number" min="600" max="86400" step="1" inputmode="numeric" value="${e(String(config.cooldown_seconds))}" required></label>
      <p class="quote-caption">所选指标任一方向达到门槛即触发。数量是合约基础单位；原数量为 0 时不计算百分比。共享采样最快约 10 分钟一次，多币种会顺序读取；这不是币安承诺的更新频率。首次开启、修改配置或中断超过 30 分钟后只建立对照，不推送；低于门槛或提醒间隔内的变化不累计补发。</p>
      <p class="quote-caption" role="status">${e(status)}${date?`<br>最近检查：${e(date.toLocaleString("zh-CN"))}`:""}${monitoring?.observed_at?`<br>最近成功读取：${e(stamp(monitoring.observed_at))}`:""}</p>
      <p class="form-error down" role="alert"></p><button type="submit">保存聪明钱订阅</button>
    </form></section>`;
}

export function smartMoneyPayload(form) {
  const values=Object.fromEntries(new FormData(form));
  const config={watch_whale_count:values.watch_whale_count==="on",watch_whale_quantity:values.watch_whale_quantity==="on",
    min_whale_count_change:Number(values.min_whale_count_change),min_whale_quantity_change_pct:Number(values.min_whale_quantity_change_pct),cooldown_seconds:Number(values.cooldown_seconds)};
  if(!config.watch_whale_count&&!config.watch_whale_quantity)throw Error("至少选择巨鲸人数或持仓数量中的一项。");
  return {asset_id:Number(form.dataset.asset),alert_type:"smart_money",enabled:values.enabled==="on",config};
}
