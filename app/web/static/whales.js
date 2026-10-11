import {escapeHTML as e, number as n} from "./mobile-core.js?v=2026.10.12.2";

const labels={discovered:"新发现已有仓位",opened:"新开仓",increased:"加仓",reduced:"减仓",closed:"平仓",flipped:"反向开仓"};
const stamp=value=>value?new Date(value).toLocaleString("zh-CN"):"尚未收到";
const money=value=>value==null?"未提供":`$${n(value,2)}`;
const pnlMoney=value=>value==null||value===""||!Number.isFinite(Number(value))?"未提供":`${Number(value)>0?"+":Number(value)<0?"-":""}$${Math.abs(Number(value)).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const address=value=>`<span class="whale-address">${e(value)}</span>`;
const venue=value=>value.venue||(value.coin?.startsWith("lighter:")?"lighter":"trade_xyz");
export const whaleMarketLabel=m=>`${m.symbol||m.coin} · ${m.source||(venue(m)==="lighter"?"Lighter 主网":"trade.xyz")}${m.reduce_only?" · 仅减仓":""}${m.frozen?" · 暂停交易":""}${m.volume_24h_usd!=null&&Number(m.volume_24h_usd)===0?" · 24h 无成交":""}`;
const account=p=>venue(p)==="lighter"?`${p.wallet_address?address(p.wallet_address):""}<small> Lighter 账户 #${e(p.account_index??"未提供")}</small>`:address(p.address);
const outcomes={sent:"已发送 Telegram",in_app:"已存站内通知",below_position:"仓位规模未达标",below_change:"调仓门槛未达标",cooldown:"提醒间隔内",buffering:"累计等待中",merged:"已并入累计消息",failed:"发送失败",pending:"等待处理",inactive:"订阅已停用",settings_changed:"设置变更已取消",superseded:"后续仓位变化已取消",cancelled:"已取消重试",duplicate:"已去重"};
export function matchingWhaleMarkets(markets,subscriptions,query="",platform="") {
  const term=query.trim().toLocaleLowerCase();
  const added=new Set(subscriptions.map(s=>s.coin));
  return markets.filter(m=>!added.has(m.coin)&&(!platform||venue(m)===platform)&&`${m.coin} ${m.symbol||""} ${m.name} ${m.source||""}`.toLocaleLowerCase().includes(term));
}
function fields(sub, markets) {
  return `${sub?`<p><strong>${e(whaleMarketLabel(sub))}</strong></p>`:'<label>交易平台<select data-whale-platform><option value="">全部平台</option><option value="trade_xyz">Hyperliquid / trade.xyz</option><option value="lighter">Lighter 主网</option></select></label><label>搜索可添加市场<input type="search" data-whale-search placeholder="如 AAPL、GOLD、KORU" autocomplete="off"></label>'}<label>交易市场${sub?`<input type="hidden" name="coin" value="${e(sub.coin)}"><input value="${e(whaleMarketLabel(sub))}" readonly>`:`<select name="coin" required>${markets.map(m=>`<option value="${e(m.coin)}">${e(whaleMarketLabel(m))} · ${e(m.name)}</option>`).join("")}</select>`}</label>
  <label>巨鲸仓位阈值（USD）<input name="min_position_usd" type="number" min="1000" max="1000000000000" step="any" inputmode="decimal" required value="${sub?.min_position_usd??1000000}"></label>
  <label>同地址同市场提醒间隔（秒）<input name="cooldown_seconds" type="number" min="0" max="86400" step="1" inputmode="numeric" required value="${sub?.cooldown_seconds??300}"></label>
  <label>最小调仓金额（USD）<input name="min_change_usd" type="number" min="0" max="1000000000000" step="any" inputmode="decimal" required value="${sub?.min_change_usd??5000}"></label>
  <label>最小数量变化（原仓位 %）<input name="min_change_pct" type="number" min="0" max="1000" step="any" inputmode="decimal" required value="${sub?.min_change_pct??.5}"></label>
  <label>同向调仓累计窗口（秒）<input name="aggregation_seconds" type="number" min="0" max="3600" step="1" inputmode="numeric" required value="${sub?.aggregation_seconds??300}"></label>
  <p class="quote-caption">加仓／减仓须同时达到金额和比例门槛；设为 0 可关闭对应限制。窗口内连续同向调仓累计达标即提醒，未达标到期舍弃；窗口为 0 则逐次判断。无完整成交价格时，金额按仓位快照估算。</p>
  <label class="whale-enabled"><input name="priority_events" type="checkbox"${!sub||sub.priority_events!==false?" checked":""}> 新开仓／平仓／反向开仓优先提醒（跳过间隔）</label>
  <label class="whale-enabled"><input name="enabled" type="checkbox"${!sub||sub.enabled?" checked":""}> 开启自动发现和提醒</label>`;
}
function monitoringCard(m) {
  return `<article class="news-item"><h3>${e(venue(m)==="lighter"?m.symbol||m.coin:m.coin)}</h3><small>${e(whaleMarketLabel(m))}</small><div class="whale-numbers"><span>已知地址<strong>${n(m.known_addresses,0)}</strong></span><span>已核验地址<strong>${n(m.verified_addresses,0)}</strong></span><span>符合仓位门槛<strong>${n(m.eligible_positions,0)}</strong></span><span>待首次核验<strong>${n(m.pending_addresses,0)}</strong></span></div><small>最近核验：${stamp(m.last_verified_ms)} · 符合门槛但已过期：${n(m.stale_positions,0)}</small><p>近 24 小时：${Object.entries(m.outcomes_24h||{}).map(([key,count])=>`${e(outcomes[key]||key)} ${n(count,0)}`).join(" · ")||"尚无推送判断记录"}</p></article>`;
}
function snapshot(p) {
  return `<div class="whale-numbers"><span>仓位名义价值<strong>${money(p.notional_usd)}</strong></span><span>平均开仓价<strong>${money(p.entry_price)}</strong></span><span>当前未实现盈亏<strong class="${Number(p.unrealized_pnl)>0?"up":Number(p.unrealized_pnl)<0?"down":""}">${pnlMoney(p.unrealized_pnl)}</strong></span><span>${p.leverage_basis==="initial_margin_fraction"?"初始保证金率折算杠杆":"当前杠杆设置"}<strong>${p.leverage==null?"未提供":`${n(p.leverage,3)}x`} ${e(({cross:"全仓",isolated:"逐仓"})[p.leverage_type]||"")}</strong></span></div>`;
}
function sourceHealth(source) {
  const r=source.runtime||{};
  return `<article class="news-item"><h3>${e(source.label)} · ${!r.online?"服务未连接":r.connected?"公开成交监听中":"等待订阅或重连"}</h3><p>当前监听：${r.subscribed_coins?.length?r.subscribed_coins.map(e).join("、"):"尚无"}</p><p>候选池 ${n(r.address_count??0,0)} 个账户 · 待复核 ${n(r.pending_checks??0,0)} 个 · 容量 ${n(r.address_cap??2000,0)}</p><small>本次启动：${stamp(r.started_ms)}<br>最近成交：${stamp(r.last_trade_ms)}<br>最近核验：${stamp(r.last_scan_ms)}<br>服务心跳：${stamp(r.heartbeat_ms)}</small>${!r.online?'<p class="down">服务未启动或心跳已过期；当前显示的是上次保存的数据。</p>':""}${r.capacity_skips?`<p class="down">候选池已达容量，有 ${n(r.capacity_skips,0)} 次新候选被跳过；覆盖不完整。</p>`:""}${[r.catalog_error,r.stream_error,r.last_scan_error,r.delivery_error].filter(Boolean).length?`<p class="down">连接或核验异常：${[r.catalog_error,r.stream_error,r.last_scan_error,r.delivery_error].filter(Boolean).map(e).join(" · ")}</p>`:""}${r.last_fill_error?`<p class="quote-caption">成交价格查询暂不可用：${e(r.last_fill_error)}；仓位核验仍在继续。</p>`:""}</article>`;
}
export function whalePage(data, telegramConfigured) {
  const {markets=[],subscriptions=[],positions=[],events=[],monitoring=[],runtime:r={},sources=[]}=data||{};
  const active=subscriptions.filter(s=>s.enabled).length;
  const available=matchingWhaleMarkets(markets,subscriptions);
  const listening=sources.length?sources.some(s=>s.runtime?.online&&s.runtime?.connected):r.connected;
  const status=!r.online?"服务未连接":!active?"等待开启订阅":listening?"公开成交监听中":"正在重连成交源";
  return `<a class="back" href="#alerts">← 返回提醒中心</a><div class="page-heading"><div><p class="eyebrow">PUBLIC WALLET INTELLIGENCE</p><h1>链上巨鲸仓位</h1></div><span class="tag">${status}</span></div>
  <div class="notice"><strong>Hyperliquid / trade.xyz + Lighter 主网 · 官方目录永续合约</strong><br>${e(data?.coverage||"自动从公开成交发现钱包，无需提供地址。仅覆盖已选市场；尚未导入全量历史。")}
  <br>可选 ${markets.length} 个经官方目录核验的市场，包含股票、ETF 及其他品种；仅监听已开启订阅的市场。
  <br>盈亏为核验时的持仓浮盈／浮亏，不代表已实现净利润；缺失时显示未提供。
  <br><strong>xyz:KORU 与 Binance KORUUSDT 是不同市场。</strong>Lighter 同名合约也单独监控；不含 Robinhood。仅减仓／暂停交易的市场可能没有新成交。Lighter 核验时间为本服务读取时间，非逐笔开仓时间。</div>
  ${!telegramConfigured?'<div class="notice">未绑定 Telegram，提醒会保存在站内通知。<a href="#settings">绑定 Telegram →</a></div>':""}
  <section class="card whale-health"><div class="section-title"><h2>监控覆盖</h2><button data-action="whale-refresh">刷新状态</button></div>
  ${sources.length?sources.map(sourceHealth).join(""):sourceHealth({label:"Hyperliquid / trade.xyz",runtime:r})}
  ${!r.online?'<p class="down">共享推送服务未连接；Lighter 仓位已采集时也无法发送通知，请检查推送服务状态。</p>':""}
  <p class="quote-caption">大仓位约每 60 秒核验，普通候选约每 5 分钟核验；排队或限流时会延迟。首次发现不是刚开仓；核验间的开平仓可能遗漏。仅展示最近 50 个仓位和 50 条事件。</p>
  ${monitoring.map(monitoringCard).join("")}<p class="quote-caption">各市场地址来自升级后观察到的成交及已知持仓，随候选池保留；不是全网历史总数。推送判断仅统计你自己的订阅；网页保留达仓位门槛的变化，调仓推送另受下方设置筛选。</p></section>
  <div class="section-title"><h2>我的监控订阅</h2><small>${active} 个已开启</small></div><div class="sub-grid">${subscriptions.map(s=>`<section class="card form-card"><form class="whale-subscription-form" data-id="${s.id}">${fields(s,markets)}<div class="actions"><button type="submit" class="primary">保存设置</button><button type="button" class="danger" data-action="whale-delete" data-id="${s.id}">删除订阅</button></div></form></section>`).join("")}
  <section class="card form-card"><h3>＋ 添加市场</h3>${available.length?`<form class="whale-subscription-form">${fields(null,available)}<p class="quote-caption" data-whale-search-count aria-live="polite">${available.length} 个市场可添加</p><button class="primary full" type="submit">开启自动发现</button></form>`:`<p class="muted">${markets.length?"已添加所有支持的市场，可在订阅卡片中调整设置。":"等待巨鲸服务从官方 API 核验市场目录；不会显示虚构市场。"}</p>`}</section></div>
  <p class="quote-caption">无需填写钱包地址。仓位门槛按前后较大的仓位规模筛选；首次发现提醒不代表刚开仓。修改设置会取消尚未推送的累计记录，不会补发历史消息。</p>
  <div class="section-title"><h2>已核验的大仓位</h2></div><div class="card">${positions.length?positions.map(p=>`<article class="news-item"><div class="news-meta"><span class="tag">${e(p.symbol||p.coin)}</span><span>${Number(p.qty)>0?"多单":"空单"}</span><span class="${p.stale?"down":"muted"}">${p.stale?"数据已过期 · ":""}${stamp(p.snapshot_ms)}</span></div>${account(p)}${snapshot(p)}<small>数量 ${e(p.qty)} · ${e(p.source)}</small></article>`).join(""):'<div class="empty"><strong>尚无符合阈值的已核验仓位</strong>开启订阅后自动发现。没有记录不代表市场没有巨鲸。</div>'}</div>
  <div class="section-title"><h2>仓位变化</h2></div><div class="card">${events.length?events.map(p=>`<article class="news-item"><div class="news-meta"><span class="tag">${e(p.symbol||p.coin)}</span><span>${stamp(p.snapshot_ms)}</span></div><h3>${e(labels[p.kind]||p.kind)} · ${p.side==="long"?"多单":"空单"}</h3>${account(p)}${snapshot(p)}<p>${p.previous_qty==null?"首次核验，无法确认实际开仓时间。":`数量 ${e(p.previous_qty)} → ${e(p.qty)}；两次核验间的净变化。`}</p><small>${e(p.source)} · ${e(outcomes[p.push_outcome]||"尚无个人推送记录")}</small></article>`).join(""):'<div class="empty"><strong>暂无符合订阅条件的事件</strong>提醒也会出现在通知中心。</div>'}</div>`;
}
