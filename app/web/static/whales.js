import {escapeHTML as e, number as n} from "./mobile-core.js?v=2026.10.11.4";

const labels={discovered:"新发现已有仓位",opened:"新开仓",increased:"加仓",reduced:"减仓",closed:"平仓",flipped:"反向开仓"};
const stamp=value=>value?new Date(value).toLocaleString("zh-CN"):"尚未收到";
const money=value=>value==null?"未提供":`$${n(value,2)}`;
const pnlMoney=value=>value==null||value===""||!Number.isFinite(Number(value))?"未提供":`${Number(value)>0?"+":Number(value)<0?"-":""}$${Math.abs(Number(value)).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const address=value=>`<span class="whale-address">${e(value)}</span>`;
export function matchingWhaleMarkets(markets,subscriptions,query="") {
  const term=query.trim().toLocaleLowerCase();
  const added=new Set(subscriptions.map(s=>s.coin));
  return markets.filter(m=>!added.has(m.coin)&&`${m.coin} ${m.name}`.toLocaleLowerCase().includes(term));
}
function fields(sub, markets) {
  return `${sub?"":'<label>搜索可添加市场<input type="search" data-whale-search placeholder="如 AAPL、GOLD、KORU" autocomplete="off"></label>'}<label>交易市场${sub?`<input name="coin" value="${e(sub.coin)}" readonly>`:`<select name="coin" required>${markets.map(m=>`<option value="${e(m.coin)}">${e(m.coin)} · ${e(m.name)}</option>`).join("")}</select>`}</label>
  <label>巨鲸仓位阈值（USD）<input name="min_position_usd" type="number" min="1000" max="1000000000000" step="any" inputmode="decimal" required value="${sub?.min_position_usd??1000000}"></label>
  <label>同地址同市场提醒间隔（秒）<input name="cooldown_seconds" type="number" min="0" max="86400" step="1" inputmode="numeric" required value="${sub?.cooldown_seconds??300}"></label>
  <label class="whale-enabled"><input name="enabled" type="checkbox"${!sub||sub.enabled?" checked":""}> 开启自动发现和提醒</label>`;
}
function snapshot(p) {
  return `<div class="whale-numbers"><span>仓位名义价值<strong>${money(p.notional_usd)}</strong></span><span>平均开仓价<strong>${money(p.entry_price)}</strong></span><span>当前未实现盈亏<strong class="${Number(p.unrealized_pnl)>0?"up":Number(p.unrealized_pnl)<0?"down":""}">${pnlMoney(p.unrealized_pnl)}</strong></span><span>当前杠杆设置<strong>${p.leverage==null?"未提供":`${e(p.leverage)}x`} ${e(({cross:"全仓",isolated:"逐仓"})[p.leverage_type]||"")}</strong></span></div>`;
}
export function whalePage(data, telegramConfigured) {
  const {markets=[],subscriptions=[],positions=[],events=[],runtime:r={}}=data||{};
  const active=subscriptions.filter(s=>s.enabled).length;
  const available=matchingWhaleMarkets(markets,subscriptions);
  const status=!r.online?"服务未连接":!active?"等待开启订阅":r.connected?"公开成交监听中":"正在重连成交源";
  return `<a class="back" href="#alerts">← 返回提醒中心</a><div class="page-heading"><div><p class="eyebrow">PUBLIC WALLET INTELLIGENCE</p><h1>链上巨鲸仓位</h1></div><span class="tag">${status}</span></div>
  <div class="notice"><strong>Hyperliquid / trade.xyz · 官方目录永续合约</strong><br>${e(data?.coverage||"自动从公开成交发现钱包，无需提供地址。仅覆盖已选市场；尚未导入全量历史。")}
  <br>可选 ${markets.length} 个经官方目录核验的市场，包含股票、ETF 及其他品种；仅监听已开启订阅的市场。
  <br>盈亏为核验时的持仓浮盈／浮亏，不代表已实现净利润；缺失时显示未提供。
  <br><strong>xyz:KORU 与 Binance KORUUSDT 是不同市场。</strong></div>
  ${!telegramConfigured?'<div class="notice">未绑定 Telegram，提醒会保存在站内通知。<a href="#settings">绑定 Telegram →</a></div>':""}
  <section class="card whale-health"><div class="section-title"><h2>监控覆盖</h2><button data-action="whale-refresh">刷新状态</button></div>
  <p>当前监听：${r.subscribed_coins?.length?r.subscribed_coins.map(e).join("、"):"尚无"}</p>
  <p>已发现 ${n(r.address_count??0,0)} 个地址 · 待核验 ${n(r.pending_checks??0,0)} 个 · 容量 ${n(r.address_cap??2000,0)}</p>
  <small>本次启动：${stamp(r.started_ms)}<br>最近成交：${stamp(r.last_trade_ms)}<br>最近核验：${stamp(r.last_scan_ms)}<br>服务心跳：${stamp(r.heartbeat_ms)}</small>
  <p class="quote-caption">大仓位约每 60 秒核验，普通候选约每 5 分钟核验；排队或限流时会延迟。首次发现不是刚开仓；核验间的开平仓可能遗漏。仅展示最近 50 个仓位和 50 条事件。</p>
  ${!r.online?'<p class="down">巨鲸服务未启动或心跳已过期；当前显示的是上次保存的数据。</p>':""}
  ${r.capacity_skips?`<p class="down">候选池已达容量，本次运行有 ${n(r.capacity_skips,0)} 次新候选被跳过；覆盖不完整。</p>`:""}
  ${[r.catalog_error,r.stream_error,r.last_scan_error,r.delivery_error].filter(Boolean).length?`<p class="down">连接或核验异常：${[r.catalog_error,r.stream_error,r.last_scan_error,r.delivery_error].filter(Boolean).map(e).join(" · ")}</p>`:""}</section>
  <div class="section-title"><h2>我的监控订阅</h2><small>${active} 个已开启</small></div><div class="sub-grid">${subscriptions.map(s=>`<section class="card form-card"><form class="whale-subscription-form" data-id="${s.id}">${fields(s,markets)}<div class="actions"><button type="submit" class="primary">保存设置</button><button type="button" class="danger" data-action="whale-delete" data-id="${s.id}">删除订阅</button></div></form></section>`).join("")}
  <section class="card form-card"><h3>＋ 添加市场</h3>${available.length?`<form class="whale-subscription-form">${fields(null,available)}<p class="quote-caption" data-whale-search-count aria-live="polite">${available.length} 个市场可添加</p><button class="primary full" type="submit">开启自动发现</button></form>`:`<p class="muted">${markets.length?"已添加所有支持的市场，可在订阅卡片中调整设置。":"等待巨鲸服务从官方 API 核验市场目录；不会显示虚构市场。"}</p>`}</section></div>
  <p class="quote-caption">无需填写钱包地址。阈值按核验仓位规模筛选；减仓、平仓按前后较大的仓位规模筛选。修改阈值不会补发历史消息。</p>
  <div class="section-title"><h2>已核验的大仓位</h2></div><div class="card">${positions.length?positions.map(p=>`<article class="news-item"><div class="news-meta"><span class="tag">${e(p.coin)}</span><span>${Number(p.qty)>0?"多单":"空单"}</span><span class="${p.stale?"down":"muted"}">${p.stale?"数据已过期 · ":""}${stamp(p.snapshot_ms)}</span></div>${address(p.address)}${snapshot(p)}<small>数量 ${e(p.qty)} · ${e(p.source)}</small></article>`).join(""):'<div class="empty"><strong>尚无符合阈值的已核验仓位</strong>开启订阅后自动发现。没有记录不代表市场没有巨鲸。</div>'}</div>
  <div class="section-title"><h2>仓位变化</h2></div><div class="card">${events.length?events.map(p=>`<article class="news-item"><div class="news-meta"><span class="tag">${e(p.coin)}</span><span>${stamp(p.snapshot_ms)}</span></div><h3>${e(labels[p.kind]||p.kind)} · ${p.side==="long"?"多单":"空单"}</h3>${address(p.address)}${snapshot(p)}<p>${p.previous_qty==null?"首次核验，无法确认实际开仓时间。":`数量 ${e(p.previous_qty)} → ${e(p.qty)}；两次核验间的净变化。`}</p><small>${e(p.source)}</small></article>`).join(""):'<div class="empty"><strong>暂无符合订阅条件的事件</strong>提醒也会出现在通知中心。</div>'}</div>`;
}
