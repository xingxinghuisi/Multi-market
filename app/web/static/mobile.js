import {escapeHTML as e, number as n, percent, timestamp, safeURL, kind, marketMatches, candleSeries, alertPayload, supportsSubscriptions} from "./mobile-core.js?v=2026.10.11.4";
import {whalePage,matchingWhaleMarkets} from "./whales.js?v=2026.10.11.4";
import {createAppUpdater} from "./app-update.js?v=2026.10.11.4";
const APP_VERSION = "2026.10.11.4";

const $ = selector => document.querySelector(selector);
const content = $("#content");
$(".skip-link").addEventListener("click", event => {event.preventDefault(); content.focus();});
let pendingWrites = 0;
const interacting = () => pendingWrites > 0 || (document.activeElement !== content && content.contains(document.activeElement)) || !!content.querySelector("details[open]");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const nav = $(".glass-nav");
const navIndicator = $(".nav-indicator");
let navHasPosition = false;
function positionNavIndicator() {
  if (nav.hidden) return;
  const active = nav.querySelector('[aria-current="page"]');
  if (!active) return;
  navIndicator.style.width = `${active.offsetWidth}px`;
  navIndicator.style.transform = `translate3d(${active.offsetLeft}px, 0, 0)`;
  if (!navHasPosition) {
    navHasPosition = true;
    requestAnimationFrame(() => nav.classList.add("nav-ready"));
  }
}
window.addEventListener("resize", () => requestAnimationFrame(positionNavIndicator));
const paths = {home:'<path d="m3 10 9-7 9 7v10H4V10m5 10v-7h6v7"/>',star:'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9Z"/>',news:'<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 7h8M8 11h8M8 15h3m3 0h2"/>',bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M9 21h6"/>',user:'<circle cx="12" cy="7" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',plus:'<path d="M12 5v14M5 12h14"/>',back:'<path d="m14 5-7 7 7 7"/>'};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.star}</svg>`;
document.querySelectorAll("[data-icon]").forEach(el => el.innerHTML = icon(el.dataset.icon));
const store = {get(key, fallback) {try{return localStorage.getItem(`radar.${key}`) ?? fallback;}catch{return fallback;}},set(key, value){try{localStorage.setItem(`radar.${key}`, value);}catch{/* Private mode still works. */}}};
const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
const themeChoice = () => ["light","dark"].includes(store.get("theme","system")) ? store.get("theme","system") : "system";
function applyTheme(choice=themeChoice()) {
  document.documentElement.dataset.theme=choice==="system"?(systemTheme.matches?"dark":"light"):choice;
  const themeColor=document.querySelector('meta[name="theme-color"]');
  if(themeColor)themeColor.content=document.documentElement.dataset.theme==="dark"?"#101918":"#f5f7f3";
}
systemTheme.addEventListener?.("change",()=>{if(themeChoice()==="system")applyTheme();});
applyTheme();
const state = {assets:[], quotes:[], watchlist:[], hiddenAssets:[], alerts:[], subs:[], alertTab:store.get("alertTab","rules")==="subs"?"subs":"rules", subSheet:false, subSearch:"", subOpen:new Set(), news:[], notifications:[], profile:null, bot:null, telegramChallengeSent:false, session:null,
  errors:{}, loading:true, filter:"all", newsFilter:"all", notificationFilter:"all", detail:new Map(), searchResults:[], searchSequence:0,
  refreshSeconds:[15,30,60].includes(Number(store.get("refresh", "30")))?Number(store.get("refresh", "30")):30, refreshing:false, socket:null, socketUp:false, lastSync:null};
state.whales={markets:[],subscriptions:[],positions:[],events:[],runtime:{}};
const endpoints = {assets:"/api/assets", quotes:"/api/market/latest", watchlist:"/api/watchlist", hiddenAssets:"/api/client-assets/hidden", alerts:"/api/alert-rules", subs:"/api/subscriptions", whales:"/api/whales", news:"/api/news?limit=100", notifications:"/api/notifications?limit=100", profile:"/api/client-profile"};
const operatorNames = {crossing_up:"向上突破",crossing_down:"向下跌破",step:"每变动"};
const timeText = value => timestamp(value)?.toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}) ?? "时间未提供";
const changeClass = value => value == null ? "muted" : Number(value) >= 0 ? "up" : "down";
const assetId = asset => asset.asset_id ?? asset.id;
const quoteFor = id => state.quotes.find(q => q.asset_id === Number(id));
const followed = id => state.watchlist.some(a => a.asset_id === Number(id));
const visibleAssets = () => state.assets.filter(a => !state.hiddenAssets.includes(a.id));
const current = () => {const [page, id] = location.hash.slice(1).split("/"); return {page:page || "home", id:Number(id)};};
const empty = (title, description="", action="") => `<div class="empty"><strong>${e(title)}</strong>${e(description)}${action}</div>`;
const errorBox = key => state.errors[key] ? `<div class="notice error" role="alert">${e(state.errors[key])} <button class="subtle" data-action="retry">重试</button></div>` : "";
const heading = (title, subtitle="MIRAO", action="") => `<div class="page-heading"><div><p class="eyebrow">${e(subtitle)}</p><h1>${e(title)}</h1></div>${action}</div>`;
const linkButton = (href, text, primary=false) => `<a class="button ${primary?"primary":""}" href="${href}">${text}</a>`;
const back = (href="#home", label="返回总览") => `<a class="back" href="${href}">${icon("back")}${e(label)}</a>`;
function toast(text) {
  const element = $("#toast");
  element.textContent = text;
  element.hidden = false;
  element.classList.remove("toast-enter");
  if (!reducedMotion.matches) {
    void element.offsetWidth;
    element.classList.add("toast-enter");
  }
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.hidden = true, 4500);
}

async function request(url, {method="GET", body, signal}={}) {
  const writing = !["GET","HEAD","OPTIONS"].includes(method);
  if(writing)pendingWrites++;
  const controller = new AbortController();
  const timer=setTimeout(()=>controller.abort(),20000);
  const abort=()=>controller.abort();
  if(signal) {if(signal.aborted) controller.abort();else signal.addEventListener("abort",abort,{once:true});}
  try {
    const headers=body?{"Content-Type":"application/json"}:{};
    if(method!=="GET"&&state.session?.csrf_token)headers["X-CSRF-Token"]=state.session.csrf_token;
    const response=await fetch(url,{method,cache:"no-store",credentials:"same-origin",signal:controller.signal,
      headers,body:body?JSON.stringify(body):undefined});
    const data=await response.json().catch(()=>null);
    if(!response.ok) {
      const detail=typeof data?.detail === "string"?data.detail: "请稍后重试";
      const error = new Error(`请求失败（${response.status}）：${detail}`);
      error.status = response.status;
      if(response.status===401&&state.session&&url!=="/api/auth/login") {
        state.session=null;state.whales={markets:[],subscriptions:[],positions:[],events:[],runtime:{}};state.watchlist=[];state.hiddenAssets=[];state.alerts=[];state.subs=[];state.notifications=[];state.profile=null;
        state.socket?.close();location.hash="login";
      }
      throw error;
    }
    return data;
  } catch(error) {
    if(error.name === "AbortError") throw new Error("请求超时，请检查连接后重试。");
    throw error;
  } finally {
    clearTimeout(timer);signal?.removeEventListener("abort",abort);
    if(writing){pendingWrites--;setTimeout(applyAppUpdate,0);}
  }
}

async function load(keys) {
  await Promise.all(keys.map(async key=>{
    try{state[key]=await request(endpoints[key]);delete state.errors[key];if(key==="quotes")state.lastSync=new Date();}
    catch(error){state.errors[key]=`${({assets:"资产",quotes:"行情",watchlist:"关注列表",hiddenAssets:"个人目录",alerts:"提醒规则",subs:"推送订阅",whales:"链上巨鲸",news:"新闻",notifications:"通知",profile:"账户"})[key]}加载失败。${error.message}`;}
  }));
  updateConnection();
}
function updateConnection() {
  const offline=!navigator.onLine;
  const el=$("#connection");
  el.textContent=offline?"离线":state.errors.quotes?"连接异常":!state.quotes.length?"等待行情":state.socketUp?"行情已连接":"定时更新";
  el.classList.toggle("online",!offline&&!state.errors.quotes&&!!state.quotes.length);
  $("#network-banner").hidden=!offline;
  $("#network-banner").textContent="当前离线。显示的是本次打开后已读取的记录，恢复网络后才能更新或保存。";
}
function filters(selected, attribute="filter") {
  return `<div class="filters" role="group" aria-label="市场筛选">${[["all","全部"],["crypto","加密货币"],["US","美股"],["KRX","韩股"],["HK","港股"]].map(([key,name])=>`<button data-${attribute}="${key}" class="${selected===key?"active":""}" aria-pressed="${selected===key}">${name}</button>`).join("")}</div>`;
}
function assetRows(assets, limit=Infinity, controls=false) {
  if(!assets.length)return empty("这里还很安静", "添加你想持续关注的资产。",linkButton("#add","＋ 添加资产"));
  return assets.slice(0,limit).map(asset=>{
    const id=assetId(asset), q=quoteFor(id), full=state.assets.find(a=>a.id===id)||asset;
    const followButton=`<button class="row-follow ${followed(id)?"is-followed":""}" data-action="follow" data-id="${id}" aria-label="${followed(id)?"移除关注":"关注"} ${e(asset.symbol)}" aria-pressed="${followed(id)}">${followed(id)?"移除关注":"＋ 关注"}</button>`;
    const deleteButton=controls==="catalog"?`<button class="row-delete danger" data-action="hide-asset" data-id="${id}" aria-label="从我的资产目录删除 ${e(asset.symbol)}">删除资产</button>`:"";
    return `<div class="asset-row" data-asset-id="${id}"><span class="asset-avatar ${asset.asset_type==="crypto"?"crypto":""}">${e(asset.symbol.slice(0,2))}</span><div class="asset-info"><a href="#asset/${id}">${e(asset.symbol)}</a><small>${e(asset.name)} · ${e(asset.venue)} · ${kind(asset)}</small>${asset.enabled===false?'<small>已停用 · 仅查看历史记录</small>':""}</div><div class="price"><span data-quote-price>${n(q?.price,6)}</span><small data-quote-change class="${changeClass(q?.change_pct)}">${q?percent(q.change_pct):"等待行情"} <span class="muted" data-quote-currency>${e(full.currency||q?.currency||"")}</span></small></div>${controls?`<div class="row-actions">${followButton}${deleteButton}</div>`:""}</div>`;
  }).join("");
}
function paintQuotes() {
  content.querySelectorAll(".asset-row[data-asset-id]").forEach(row=>{
    const q=quoteFor(row.dataset.assetId), asset=state.assets.find(a=>a.id===Number(row.dataset.assetId));
    const price=row.querySelector("[data-quote-price]"), change=row.querySelector("[data-quote-change]");
    if(!price||!change)return;
    price.textContent=n(q?.price,6);
    change.className=changeClass(q?.change_pct);
    change.firstChild.textContent=`${q?percent(q.change_pct):"等待行情"} `;
    const currency=change.querySelector("[data-quote-currency]");
    if(currency)currency.textContent=asset?.currency||q?.currency||"";
  });
  const detailPrice=content.querySelector("[data-detail-price]");
  if(detailPrice){
    const q=quoteFor(detailPrice.dataset.detailPrice);
    detailPrice.textContent=n(q?.price,8);
    const change=content.querySelector("[data-detail-change]");
    if(change){change.className=changeClass(q?.change_pct);change.textContent=`${percent(q?.change_pct)}　${q?.change_amount!=null?n(q.change_amount,8):""}`;}
  }
}
function newsRows(rows,limit=Infinity) {
  if(!rows.length)return empty("暂无相关新闻", "新闻采集完成后会出现在这里。");
  return rows.slice(0,limit).map(row=>{
    const url=safeURL(row.url), sentiment={positive:"正面",negative:"负面",neutral:"中性"}[row.sentiment]||"未分类";
    return `<article class="news-item"><div class="news-meta"><span class="tag">${e(row.symbol)}</span><span>${e(row.source)}</span><span>${timeText(row.published_at)}</span></div><h3>${url?`<a class="news-title" href="${e(url)}" target="_blank" rel="noopener noreferrer">${e(row.title)} ↗</a>`:e(row.title)}</h3>${row.summary?`<p>${e(row.summary)}</p>`:""}<div class="news-meta"><span>${sentiment}</span>${row.analysis_source?`<span>分析来源：${e(row.analysis_source)}</span>`:""}</div></article>`;
  }).join("");
}
function home() {
  const assets=visibleAssets().filter(a=>marketMatches(a,state.filter));
  const watched=state.watchlist.map(a=>({...state.assets.find(b=>b.id===a.asset_id),...a}));
  return heading("市场，尽在掌握", new Date().toLocaleDateString("zh-CN",{month:"long",day:"numeric",weekday:"long"}),linkButton("#add",`${icon("plus")} 添加资产`,true))+
    `<section class="hero"><span class="orbit" aria-hidden="true"></span><p class="eyebrow">MARKETS IN FOCUS</p><h2>看清市场，<br>从容每一步。</h2><p>真实行情、专属关注与价格提醒，汇集于此。</p><a class="hero-action" href="#watchlist">查看我的关注 <span aria-hidden="true">↗</span></a></section>${!state.quotes.length?'<div class="notice">资产目录已加载，当前尚无采集到的报价。请检查行情服务与数据源；本机预览不会生成价格。</div>':""}<div class="stats"><a class="stat" href="#catalog" aria-label="查看资产目录"><span>资产目录 ↗</span><strong>${state.errors.assets||state.errors.hiddenAssets?"—":visibleAssets().length}</strong></a><a class="stat" href="#watchlist" aria-label="查看我的关注"><span>我的关注 ↗</span><strong>${state.errors.watchlist?"—":state.watchlist.length}</strong></a><a class="stat" href="#alerts" aria-label="查看价格提醒"><span>已启用的提醒 ↗</span><strong>${state.errors.alerts?"—":state.alerts.filter(a=>a.enabled).length}</strong></a></div>`+
    `<div class="grid-two"><section><div class="section-title"><h2>市场总览</h2><small>已接入资产</small></div>${filters(state.filter)}${errorBox("assets")}${errorBox("quotes")}<div class="card list-card">${assetRows(assets,8)}</div><p class="quote-caption">涨跌基准按数据源定义；详情页显示报价时间。未接入指数不显示虚拟行情。</p></section><section><div class="section-title"><h2>我的关注</h2><a href="#watchlist">查看全部 ↗</a></div>${errorBox("watchlist")}<div class="card list-card">${assetRows(watched,3)}</div><div class="section-title"><h2>市场快讯</h2><a href="#news">更多新闻 ↗</a></div>${errorBox("news")}<div class="card list-card">${newsRows(state.news,2)}</div></section></div><p class="footer-note">MIRAO · 每一份洞察，都有真实数据为依据</p>`;
}
function watchlist() {
  const assets=state.watchlist.map(a=>({...state.assets.find(b=>b.id===a.asset_id),...a})).filter(a=>marketMatches(a,state.filter));
  return heading("我的关注","YOUR WATCHLIST",linkButton("#add",`${icon("plus")} 添加`,true))+filters(state.filter)+errorBox("watchlist")+errorBox("quotes")+`<div class="card list-card">${assetRows(assets,Infinity,true)}</div><p class="quote-caption">取消关注不会删除资产或既有提醒规则；规则可在提醒中心单独暂停。</p>`;
}
function catalog() {
  const assets=visibleAssets().filter(a=>marketMatches(a,state.filter));
  return heading("资产目录","ALL TRACKED MARKETS",linkButton("#add",`${icon("plus")} 添加资产`,true))+
    filters(state.filter)+errorBox("assets")+errorBox("hiddenAssets")+errorBox("quotes")+
    `<div class="card list-card">${assetRows(assets,Infinity,"catalog")}</div><p class="quote-caption">删除资产会从你的目录和关注中移除，并暂停该资产的提醒；其他用户的数据不受影响。可通过“添加资产”重新加入。</p>`;
}
function alerts() {
  const tab=state.alertTab==="subs"?"subs":"rules";
  const seg=`<div class="seg-tabs" role="tablist" aria-label="提醒类型"><button data-action="alert-tab" data-tab="rules" role="tab" aria-selected="${tab==="rules"}" class="${tab==="rules"?"active":""}">价格提醒</button><button data-action="alert-tab" data-tab="subs" role="tab" aria-selected="${tab==="subs"}" class="${tab==="subs"?"active":""}">推送订阅</button></div><a class="menu-row card whale-entry" href="#whales"><span>🐋 链上巨鲸仓位<small>自动发现钱包 · Hyperliquid / trade.xyz</small></span><span>→</span></a>`;
  if(tab==="subs")return subscriptionsPage(seg);
  return heading("价格提醒","STAY ONE STEP AHEAD",linkButton("#create-alert","＋ 创建提醒",true))+seg+errorBox("alerts")+`<div class="card">${state.alerts.length?state.alerts.map(rule=>`<article class="rule"><div class="rule-head"><div><h3><a href="#asset/${rule.asset.id}">${e(rule.asset.symbol)}</a> <span class="tag">${kind(rule.asset)}</span></h3><p>${e(({price:"价格",change_pct:"涨跌幅",price_change:"价格变化"})[rule.metric]||rule.metric)}${e(operatorNames[rule.operator]||rule.operator)} <strong>${n(rule.value,8)} ${rule.metric==="change_pct"?"%":e(rule.asset.currency)}</strong></p><small>冷却 ${rule.cooldown_seconds} 秒${rule.operator==="step"?` · 初始锚点 ${n(rule.step_anchor,8)}`:""}</small></div><span class="tag">${rule.enabled?"监控中":"已暂停"}</span></div><div class="actions"><button data-action="toggle-alert" data-id="${rule.id}">${rule.enabled?"暂停":"启用"}</button><button class="danger" data-action="delete-alert" data-id="${rule.id}">删除</button></div></article>`).join(""):empty("还没有价格提醒","选择已关注资产，设置你的第一个触发条件。",linkButton("#create-alert","创建提醒"))}</div><div class="notice">提醒由现有行情服务触发，Telegram 由服务端配置发送。当前未接入手机系统推送。</div>`;
}
const subTypeNames={longshort_digest:"1H 多空播报",whale_print:"巨鲸大单",whale_position:"链上巨鲸"};
function subGroups() {
  const map=new Map();
  for(const s of state.subs) {
    let g=map.get(s.asset.id);
    if(!g){g={asset:s.asset,byType:{}};map.set(s.asset.id,g);}
    g.byType[s.alert_type]=s;
  }
  return [...map.values()];
}
function subPool() {
  const existing=new Set(state.subs.map(s=>s.asset.id));
  const q=state.subSearch.trim().toLowerCase();
  return visibleAssets().filter(a=>supportsSubscriptions(a)&&!existing.has(a.id)&&(!q||a.symbol.toLowerCase().includes(q)||(a.name||"").toLowerCase().includes(q)));
}
function subCard(g) {
  const {asset,byType}=g,digest=byType.longshort_digest,whale=byType.whale_print;
  const on=!!(digest?.enabled||whale?.enabled);
  const threshold=whale?.config?.whale_min_usd??50000,cooldown=whale?.config?.cooldown_seconds??300;
  return `<details class="card sub-card" data-asset="${asset.id}"${state.subOpen.has(asset.id)?" open":""}><summary class="sub-head"><span class="sub-title"><h3>${e(asset.symbol)} <span class="tag">${kind(asset)}</span></h3><span class="muted">${e(asset.name)}</span></span><span class="sub-status${on?"":" off"}"><span class="dot"></span>${on?"订阅中":"未订阅"}</span><button class="sub-del" data-action="sub-delete" data-id="${asset.id}" aria-label="删除 ${e(asset.symbol)} 的订阅">×</button><span class="sub-chev">▾</span></summary><div class="sub-detail">
  <div class="sub-row"><div class="lb">${subTypeNames.longshort_digest}<small>每小时推送完整周期的多空数据</small></div><label class="switch"><input aria-label="${e(asset.symbol)} 1H 多空播报" type="checkbox" data-sub-toggle="longshort_digest" data-asset="${asset.id}"${digest?.enabled?" checked":""}><span class="tr"></span></label></div>
  <div class="sub-row"><div class="lb">${subTypeNames.whale_print}<small>Binance 聚合成交达到阈值时提醒</small></div><label class="switch"><input aria-label="${e(asset.symbol)} 巨鲸大单" type="checkbox" data-sub-toggle="whale_print" data-asset="${asset.id}"${whale?.enabled?" checked":""}><span class="tr"></span></label></div>
  <div class="sub-row"><label class="lb" for="whale-threshold-${asset.id}">大额成交阈值（USDT）</label><span class="thr"><input id="whale-threshold-${asset.id}" type="number" min="0.01" max="1000000000000" step="any" inputmode="decimal" value="${e(String(threshold))}" data-sub-threshold="${asset.id}"${whale?.enabled?"":" disabled"}></span></div>
  <div class="sub-row"><label class="lb" for="whale-cooldown-${asset.id}">提醒间隔（秒）<small>每个币种独立；0 表示不设间隔</small></label><span class="thr"><input id="whale-cooldown-${asset.id}" type="number" min="0" max="86400" step="1" inputmode="numeric" value="${e(String(cooldown))}" data-sub-cooldown="${asset.id}"${whale?.enabled?"":" disabled"}></span></div>
  ${[whale,digest].some(s=>s?.config_valid===false)?'<p class="notice error">旧订阅配置无效，请重新保存阈值和提醒间隔。</p>':""}<a class="inline-link" href="#asset/${asset.id}">查看行情与多空数据 →</a></div></details>`;
}
function subscriptionsPage(seg) {
  const groups=subGroups();
  const onCount=groups.filter(g=>g.byType.longshort_digest?.enabled||g.byType.whale_print?.enabled).length;
  return heading("推送订阅","STAY ONE STEP AHEAD",`<span class="tag">${onCount} / ${groups.length} 已订阅</span>`)+seg+errorBox("subs")+(!state.profile?.telegram_configured?'<div class="notice">尚未绑定 Telegram，提醒会保存在站内通知中心。<a class="inline-link" href="#settings">绑定 Telegram →</a></div>':"")+(groups.length?`<div class="sub-grid">${groups.map(subCard).join("")}</div><button class="sub-add" data-action="sub-add-open">＋ 添加币种</button>`:empty("还没有推送订阅","为合约币种开启 1H 多空播报或巨鲸大单提醒。")+`<button class="sub-add" data-action="sub-add-open">＋ 添加币种</button>`)+`<p class="quote-caption">修改即时保存；巨鲸监听通常在 15 秒内更新，投递时会再次检查开关与阈值。1H 播报在每小时第 2 分钟读取完整周期数据。巨鲸大单表示聚合成交，无法识别真实钱包。价格步进类提醒请前往「价格提醒」页。</p>`+subSheet();
}
function poolRows(pool) {
  return pool.length?pool.map(a=>`<div class="prow"><div class="inf"><b>${e(a.symbol)}</b><small>${e(a.name)} · 合约</small></div><button class="plus" data-action="sub-add" data-id="${a.id}" aria-label="添加 ${e(a.symbol)}">＋</button></div>`).join(""):`<div class="empty"><strong>没有匹配的币种</strong><p>可从资产目录先添加该合约。</p></div>`;
}
function subSheet() {
  if(!state.subSheet)return "";
  return `<div class="sheet-mask"><div class="sheet" role="dialog" aria-modal="true" aria-label="添加币种"><div class="grab"></div><div class="section-title"><h3>添加币种</h3><button data-action="sub-add-close" aria-label="关闭添加币种">关闭</button></div><p class="sheet-sub">从资产目录的 Binance USDT 合约中选择；默认开启巨鲸大单（阈值 50000 U），1H 多空播报关闭。</p><input class="search" id="sub-search" placeholder="搜索币种，如 SOL" value="${e(state.subSearch)}" autocomplete="off"><div class="plist" id="sub-pool-list">${poolRows(subPool())}</div></div></div>`;
}
function createAlert(id) {
  const options=state.watchlist.filter(a=>a.enabled!==false&&a.price_alerts_enabled);
  return back("#alerts","返回提醒中心")+heading("创建价格提醒","MAKE IT PERSONAL")+errorBox("watchlist")+`<div class="card form-card">${!options.length?empty("先关注一个资产","只有已启用价格提醒的关注资产可以创建规则。",linkButton("#add","添加资产")):`<form id="alert-form"><label>关注资产<select name="asset_id" required><option value="">选择资产</option>${options.map(a=>`<option value="${a.asset_id}" ${a.asset_id===id?"selected":""}>${e(a.symbol)} · ${kind(a)} · ${e(a.venue)}</option>`).join("")}</select></label><label>触发条件<select name="operator"><option value="crossing_up">向上突破</option><option value="crossing_down">向下跌破</option><option value="step">动态追踪（Step）</option></select></label><label><span id="value-label">目标价格</span><input name="value" type="number" step="any" min="0.00000001" inputmode="decimal" placeholder="输入价格，按资产计价货币" required></label><label id="anchor-field" hidden>初始锚点价格<input name="step_anchor" type="number" step="any" min="0.00000001" inputmode="decimal"></label><label>冷却时间（秒）<input name="cooldown_seconds" type="number" min="0" step="1" value="300" required></label><div class="notice">记录触发结果，并按已有 Telegram 配置发送。Step 使用固定价格步长，不是百分比。</div><p id="form-error" class="down" role="alert"></p><button class="primary full" type="submit">创建提醒</button></form>`}</div>`;
}
function notifications() {
  const rows=state.notifications.filter(row=>state.notificationFilter==="all"||row.category===state.notificationFilter);
  const categories=[...new Set(state.notifications.map(row=>row.category))];
  return heading("通知中心","NOTIFICATIONS")+`<div class="filters"><button data-notification-filter="all" class="${state.notificationFilter==="all"?"active":""}">全部</button>${categories.map(category=>`<button data-notification-filter="${e(category)}" class="${state.notificationFilter===category?"active":""}">${e(({price:"价格提醒",news:"新闻提醒",price_alert:"价格提醒",news_alert:"新闻提醒",longshort_digest:"1H 多空播报",whale_print:"巨鲸大单",whale_position:"链上巨鲸"})[category]||category)}</button>`).join("")}</div>`+errorBox("notifications")+`<div class="card">${rows.length?rows.map(row=>`<article class="news-item"><div class="news-meta"><span class="tag">${e(row.channel)}</span><span>${timeText(row.created_at)}</span><span>${e(({sent:"已发送",failed:"发送失败",pending:"待发送",in_app:"站内记录",cancelled:"已取消"})[row.status]||row.status)}</span></div><h3>${e(row.title)}</h3><p class="notification-text">${e(row.message)}</p>${row.asset_id?`<a class="inline-link" href="#asset/${row.asset_id}">查看资产 →</a>`:""}</article>`).join(""):empty("暂无通知记录","价格、新闻、多空播报和巨鲸提醒触发后会显示在这里。")}</div><p class="quote-caption">显示最近 100 条通知。发送状态来自服务端，不代表设备已读。</p>`;
}
function news() {
  const rows=state.news.filter(row=>{
    if(state.hiddenAssets.includes(row.asset_id))return false;
    const a=state.assets.find(a=>a.id===row.asset_id)||{venue:row.venue};return marketMatches(a,state.newsFilter);
  });
  return heading("新闻中心","THE STORIES THAT MATTER")+filters(state.newsFilter,"news-filter")+errorBox("news")+`<div class="card wide-card">${newsRows(rows)}</div><p class="quote-caption">最近 100 条资产关联新闻；情绪标签来自已有分析结果。</p>`;
}
function chart(rows, animate = false) {
  const data=candleSeries(rows);
  if(!data.length)return empty("暂无完整日 K 数据","历史记录需要真实的开盘、最高、最低和收盘价才能绘制 K 线。");
  const minimum=Math.min(...data.map(row=>row.low)), maximum=Math.max(...data.map(row=>row.high));
  const padding=(maximum-minimum||Math.max(Math.abs(maximum)*.02,1))*.08;
  const low=minimum-padding, high=maximum+padding, y=value=>190-(value-low)*160/(high-low);
  const cell=490/data.length, width=Math.max(3,Math.min(12,cell*.64));
  const grid=[0,1,2,3,4].map(step=>{
    const value=high-(high-low)*step/4, at=y(value);
    return `<path d="M20 ${at.toFixed(2)}H515" stroke="#e9eff7"/><text x="524" y="${(at+4).toFixed(2)}" fill="#7a89a1" font-size="11">${n(value,4)}</text>`;
  }).join("");
  const candles=data.map((row,index)=>{
    const x=20+cell*(index+.5), top=Math.min(y(row.open),y(row.close)), bottom=Math.max(y(row.open),y(row.close));
    const trend=row.close>row.open?"up":row.close<row.open?"down":"flat";
    return `<g class="candle ${trend}" style="--candle-index:${index}" tabindex="0"><title>${e(row.date)} 开 ${n(row.open,6)} 高 ${n(row.high,6)} 低 ${n(row.low,6)} 收 ${n(row.close,6)}</title><line x1="${x.toFixed(2)}" y1="${y(row.high).toFixed(2)}" x2="${x.toFixed(2)}" y2="${y(row.low).toFixed(2)}"/><rect x="${(x-width/2).toFixed(2)}" y="${top.toFixed(2)}" width="${width.toFixed(2)}" height="${Math.max(bottom-top,1.5).toFixed(2)}"/></g>`;
  }).join("");
  return `<div class="chart-legend"><span><i class="candle-key up"></i>上涨</span><span><i class="candle-key down"></i>下跌</span><span>日 K · 真实 OHLC</span></div><svg class="chart candle-chart ${animate?"chart-reveal":""}" viewBox="0 0 600 215" role="img" aria-label="最近 ${data.length} 个交易日的日 K 线图；具体价格可展开下方数据表">${grid}${candles}</svg><div class="chart-labels"><span>${e(data[0].date)}</span><span>${data.length} 个交易日</span><span>${e(data.at(-1).date)}</span></div><details><summary>查看历史数据</summary><div class="chart-scroll"><table class="chart-table"><thead><tr><th>日期</th><th>开盘</th><th>最高</th><th>最低</th><th>收盘</th></tr></thead><tbody>${data.map(row=>`<tr><td>${e(row.date)}</td><td>${n(row.open,6)}</td><td>${n(row.high,6)}</td><td>${n(row.low,6)}</td><td>${n(row.close,6)}</td></tr>`).join("")}</tbody></table></div></details>`;
}
const kv = fields=>`<dl class="kv">${fields.map(([label,value])=>`<div><dt>${e(label)}</dt><dd>${e(value)}</dd></div>`).join("")}</dl>`;
function futuresMetrics(asset, detail) {
  if (asset.venue !== "BINANCE") return "";
  const metrics = detail?.metrics;
  const note = detail?.metricsError
    ? `<div class="notice error">合约指标读取失败：${e(detail.metricsError)} <button data-action="detail-retry" data-id="${asset.id}">重试</button></div>`
    : metrics?.unavailable?.length ? `<div class="notice">${metrics.unavailable.length===2?"Binance 合约指标暂不可用，请稍后重试。":"部分指标暂时无法从 Binance 读取；缺失值以“—”显示。"}</div>` : "";
  const funding = metrics?.last_funding_rate == null ? "—" : percent(metrics.last_funding_rate * 100);
  const age = timestamp(metrics?.premium_time);
  const stale = age && Date.now() - age.getTime() > 5 * 60 * 1000;
  return `<div class="section-title"><h2>合约指标</h2><small>Binance USD-M</small></div><div class="card">${kv([["标记价格",n(metrics?.mark_price,8)],["指数价格",n(metrics?.index_price,8)],["最新资金费率",funding],["未平仓量",n(metrics?.open_interest,4)],["下次资金费时间",metrics?.next_funding_time?timeText(metrics.next_funding_time):"—"]])}<p class="quote-caption">标记价格与资金费率更新时间：${metrics?.premium_time?timeText(metrics.premium_time):"未提供"}${stale?" · 数据可能已过期":""}；未平仓量更新时间：${metrics?.open_interest_time?timeText(metrics.open_interest_time):"未提供"}。资金费率直接取自 Binance，未平仓量按 Binance 返回的原始数量显示。</p>${note || (!metrics ? '<p class="quote-caption">正在读取 Binance 公开合约数据…</p>' : "")}</div>`;
}

function longshortPanel(asset, detail) {
  if(!supportsSubscriptions(asset))return "";
  const data=detail?.longshort;
  const rows=[["全市场账户多空比","global"],["大户账户多空比","top_account"],["大户持仓多空比","top_position"],["主动买卖比","taker"]];
  return '<div class="section-title"><h2>1H 多空数据</h2><a href="#alerts" data-action-link="subscriptions">管理订阅 →</a></div><div class="card">'+
    (detail?.longshortError?`<div class="notice error">${e(detail.longshortError)} <button data-action="detail-retry" data-id="${asset.id}">重试</button></div>`:data?
      kv(rows.map(([label,key])=>[label,`${n(data.ratios[key]?.current,4)} · 上期 ${n(data.ratios[key]?.previous,4)}`]))+
      kv([["多头账户占比",data.long_account_pct==null?"—":`${n(data.long_account_pct)}%`],["空头账户占比",data.short_account_pct==null?"—":`${n(data.short_account_pct)}%`]])+
      `<p class="quote-caption">周期：${timeText(data.hour_start)} — ${timeText(data.hour_end)} · ${e(data.source)}。完整周期数据，非实时价格。</p>`:empty("正在读取完整 1H 数据…"))+'</div>';
}
function detail(id) {
  const d=state.detail.get(id),asset=state.assets.find(a=>a.id===id)||d?.asset||state.watchlist.find(a=>a.asset_id===id);
  if(!asset)return back()+heading("资产详情")+(d?.error?`<div class="notice error">${e(d.error)} <button data-action="detail-retry" data-id="${id}">重试</button></div>`:empty("正在读取资产…"));
  const q=quoteFor(id)||d?.quote, type=kind(asset), stamp=timestamp(q?.event_time),old=stamp&&Date.now()-stamp.getTime()>15*60*1000;
  const animateChart = Boolean(d?.history?.length && !d.chartShown && !reducedMotion.matches);
  if (d?.history?.length) d.chartShown = true;
  return back("#watchlist","返回关注列表")+`<div class="page-heading"><div class="detail-title"><span class="asset-avatar ${asset.asset_type==="crypto"?"crypto":""}">${e(asset.symbol.slice(0,2))}</span><div><h1>${e(asset.symbol)}</h1><small>${e(asset.name)} · ${e(asset.venue)} · ${type}</small></div></div><button data-action="follow" data-id="${id}" aria-pressed="${followed(id)}">${followed(id)?"★ 已关注":"☆ 关注"}</button></div><div class="grid-two"><section><div class="card"><span class="tag">${type==="合约"?"Crypto · 合约":type==="Spot"?"Crypto · Spot":"股票行情"}</span><div class="quote-large"><span data-detail-price="${id}">${n(q?.price,8)}</span> <small>${e(asset.currency)}</small></div><span data-detail-change class="${changeClass(q?.change_pct)}">${percent(q?.change_pct)}　${q?.change_amount!=null?n(q.change_amount,8):""}</span><p class="quote-caption">${q?`报价时间 ${timeText(q.event_time)}${old?" · 历史快照 / 可能已收市":""}`:"尚无报价，等待行情服务采集。"}</p>${d?.quoteError?`<div class="notice error">${e(d.quoteError)}</div>`:""}<div class="section-title"><h3>历史走势</h3><span class="tag">最近 30 个交易日</span></div>${d?.historyError?`<div class="notice error">${e(d.historyError)} <button data-action="detail-retry" data-id="${id}">重试</button></div>`:d?.history?chart(d.history, animateChart):empty("正在加载历史行情…")}</div><div class="actions">${followed(id)?linkButton(`#create-alert/${id}`,`${icon("bell")} 创建价格提醒`,true):'<span class="muted">关注后可创建价格提醒</span>'}</div></section><section><div class="section-title"><h2>${type==="合约"?"合约行情":type==="Spot"?"现货行情":"交易数据"}</h2></div><div class="card">${kv([["开盘",n(q?.open,8)],["最高",n(q?.high,8)],["最低",n(q?.low,8)],["成交量",n(q?.volume)],["成交额",n(q?.quote_volume)],["涨跌基准价",n(q?.reference_price,8)]])}<p class="quote-caption">基准：${e(q?.reference_type||"未提供")} · ${e(q?.reference_timezone||"时区未提供")}</p>${type==="股票"?kv([["交易时段",q?.market_session||"未提供"],["常规时段",n(q?.regular_price,8)],["盘前",n(q?.pre_price,8)],["盘后",n(q?.after_price,8)],["隔夜",n(q?.overnight_price,8)]]):""}</div>${type==="合约"?futuresMetrics(asset,d)+longshortPanel(asset,d):""}<div class="section-title"><h2>相关新闻</h2><a href="#news">全部 ↗</a></div><div class="card list-card">${d?.newsError?`<div class="notice error">${e(d.newsError)}</div>`:d?.news?newsRows(d.news,5):empty("正在加载新闻…")}</div></section></div>`;
}
async function loadDetail(id) {
  if(!Number.isInteger(id)||id<=0)return;
  const previous=state.detail.get(id)||{};
  const d={...previous};state.detail.set(id,d);
  await Promise.all([
    ["asset",`/api/assets/${id}`], ["quote",`/api/market/latest/assets/${id}`],
    ["history",`/api/market/history/assets/${id}?limit=30`], ["news",`/api/assets/${id}/news?limit=20`]
  ].map(async([key,url])=>{
    try{const result=await request(url);d[key]=key==="history"?result.data:result;delete d[key==="asset"?"error":`${key}Error`];}
    catch(error){
      if(key==="quote"&&error.status===404){d.quote=null;delete d.quoteError;}
      else d[key==="asset"?"error":`${key}Error`]=error.message;
    }
  }));
  if(current().page==="asset"&&current().id===id)render();
  const asset=state.assets.find(a=>a.id===id)||d.asset;
  if(asset?.venue==="BINANCE"&&kind(asset)==="合约")await loadMetrics(id);
}
async function loadMetrics(id) {
  const d=state.detail.get(id);
  if(!d)return;
  await Promise.all([["metrics","crypto-metrics"],["longshort","longshort-metrics"]].map(async([key,path])=>{
    try{d[key]=await request(`/api/assets/${id}/${path}`);delete d[`${key}Error`];}
    catch(error){delete d[key];d[`${key}Error`]=error.message;}
  }));
  if(current().page==="asset"&&current().id===id&&!interacting())render();
}
function addAsset() {
  return back("#watchlist","返回关注列表")+heading("发现下一份关注","EXPLORE MARKETS")+`<div class="card form-card"><form id="search-form"><label>选择市场<select name="market"><option value="CRYPTO">加密货币 · Binance</option><option value="US">美股 · Moomoo</option><option value="HK">港股 · Moomoo</option><option value="KRX">韩股 · 已有资产</option></select></label><label>资产代码或名称<input name="query" type="search" placeholder="搜索 BTC、AAPL、Samsung…" autocomplete="off" required maxlength="100"></label><button class="primary full" type="submit">搜索资产</button></form><div id="search-results" aria-live="polite"><p class="quote-caption">请选择市场搜索。同名币种的 Spot 和合约会分开列出；韩股目前仅能添加库内已有资产。</p></div></div><div class="section-title"><h2>已接入资产</h2></div>${errorBox("assets")}<div class="card list-card">${assetRows(visibleAssets(),Infinity,true)}</div>`;
}
function profile() {
  return heading("我的 MIRAO","YOUR SPACE")+errorBox("profile")+`<div class="grid-two"><section><div class="card profile-head"><span class="avatar">MI</span><h2>${e(state.session?.username||"账户暂不可用")}</h2><p class="muted">你的个人市场工作区</p><div class="stats"><div><strong>${state.errors.watchlist?"—":state.watchlist.length}</strong><small>关注</small></div><div><strong>${state.errors.alerts?"—":state.alerts.length}</strong><small>提醒</small></div><div><strong>${state.errors.notifications?"—":state.notifications.length}</strong><small>近期通知</small></div></div><div class="actions"><button data-action="logout">退出登录</button></div></div><div class="notice">关注、提醒与通知按账户分别保存。Telegram 接收目标可在设置中绑定并发送测试消息。</div></section><section><div class="card"><a class="menu-row" href="#alerts"><span>我的提醒</span><span>›</span></a><a class="menu-row" href="#notifications"><span>通知中心</span><span>›</span></a><a class="menu-row" href="#settings"><span>设置与 Telegram</span><span>›</span></a><a class="menu-row" href="#welcome"><span>关于 MIRAO</span><span>›</span></a><a class="menu-row" href="/legacy"><span>经典桌面工作台</span><span>↗</span></a></div></section></div>`;
}
function settings() {
  const mode=state.profile?.telegram_mode;
  const telegramStatus=!state.profile?"读取失败":!state.profile.telegram_bot_available?"Bot 未配置":mode==="legacy"?"服务器默认目标（旧账户）":mode==="personal"?"已绑定个人目标":"尚未绑定目标";
  const botLink=state.bot?.url?`<a class="inline-link" href="${e(state.bot.url)}" target="_blank" rel="noopener noreferrer">打开 @${e(state.bot.username)} ↗</a>`:"请先在 Telegram 中打开项目 Bot 并发送 /start";
  return back("#profile","返回个人中心")+heading("设置","MAKE IT YOURS")+`<div class="card form-card"><div class="section-title appearance-title"><h2>外观</h2><span class="tag">即时生效</span></div><div class="theme-options" role="group" aria-label="外观模式">${[["system","跟随系统"],["light","浅色"],["dark","夜间"]].map(([value,label])=>`<button type="button" data-theme-choice="${value}" aria-pressed="${themeChoice()===value}" class="${themeChoice()===value?"active":""}">${label}</button>`).join("")}</div><p class="quote-caption">玻璃效果用于导航和浮动控件，深浅主题均保留清晰的文字对比。</p><div class="menu-row"><span>语言</span><small>简体中文</small></div><div class="section-title"><h2>Telegram 推送</h2><span class="tag">${telegramStatus}</span></div><p class="muted">价格提醒和新闻提醒会发给绑定的 Telegram 会话；未绑定时仅保留站内通知。${mode==="legacy"?"当前账户仍沿用服务器原有接收目标。":""}</p>${state.profile?.telegram_configured&&state.profile.telegram_bot_available?'<button data-action="telegram-test">发送测试消息</button>':""}${state.profile?.telegram_bot_available?`<div class="telegram-connect"><p class="quote-caption">${botLink}，再填写你的数字 Chat ID。系统会发验证码，输入后才绑定目标。</p><form id="telegram-request-form"><label>Telegram Chat ID<input name="chat_id" inputmode="numeric" pattern="-?[0-9]{5,20}" maxlength="20" autocomplete="off" required placeholder="例如 123456789"></label><p class="form-error down" role="alert"></p><button type="submit">发送绑定验证码</button></form>${state.telegramChallengeSent?'<form id="telegram-confirm-form"><label>Telegram 收到的 8 位验证码<input name="code" autocomplete="one-time-code" pattern="[0-9a-fA-F]{8}" minlength="8" maxlength="8" required></label><p class="form-error down" role="alert"></p><button class="primary" type="submit">确认绑定</button></form>':""}</div>`:'<div class="notice error">服务器未配置 Telegram Bot，暂时无法发送推送；请检查服务器环境变量。</div>'}<form id="settings-form"><label>数据刷新间隔<select name="refresh">${[15,30,60].map(value=>`<option value="${value}" ${state.refreshSeconds===value?"selected":""}>${value} 秒</option>`).join("")}</select></label><button type="submit">保存设置</button></form><div class="section-title"><h2>添加到主屏幕</h2></div><p class="muted">iPhone：在 Safari 中打开，点“分享”，再选“添加到主屏幕”。电脑或 Android：使用浏览器的安装应用入口。</p><button data-action="install" ${installPrompt?"":"hidden"}>安装 MIRAO</button><p class="quote-caption">安装需 HTTPS 或本机 localhost。离线时可打开界面，行情和保存操作需要联网。</p></div>`;
}
function welcome() {
  return `<section class="welcome"><div class="welcome-orbit"><img src="/static/radar-icon.svg" alt="MIRAO 标志"></div><p class="eyebrow">MIRAO · MARKETS IN FOCUS</p><h1>看见变化。<br>看得更远。</h1><p>从加密货币到全球股票，<br>把你的关注、行情与提醒放在一起。</p><div class="actions"><button class="primary full" data-action="start">${state.session?"进入 MIRAO":"登录"} →</button>${linkButton(state.session?"#home":"#register",state.session?"返回总览":"创建账户")}</div><p class="quote-caption app-version">当前版本 <span>${e(APP_VERSION)}</span></p></section>`;
}
function login() {
  return back("#welcome","返回欢迎页")+heading("登录","WELCOME BACK")+`<section class="card form-card auth-card"><p class="muted">继续查看你的关注与提醒。</p><form id="login-form"><label>用户名<input name="username" autocomplete="username" minlength="3" maxlength="32" required></label><label>密码<input name="password" type="password" autocomplete="current-password" minlength="12" maxlength="128" required></label><p class="form-error down" role="alert"></p><button class="primary full" type="submit">登录</button></form><p class="auth-switch">还没有账户？ <a class="inline-link" href="#register">创建账户 →</a></p></section>`;
}
function register() {
  return back("#login","返回登录")+heading("创建账户","JOIN MIRAO")+`<section class="card form-card auth-card"><p class="muted">开放注册；用户名使用 3–32 位英文字母、数字或下划线，密码至少 12 位。</p><form id="register-form"><label>用户名<input name="username" autocomplete="username" minlength="3" maxlength="32" pattern="[A-Za-z0-9_]{3,32}" required></label><label>密码<input name="password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label><p class="form-error down" role="alert"></p><button class="primary full" type="submit">注册并进入</button></form><p class="auth-switch">已有账户？ <a class="inline-link" href="#login">返回登录 →</a></p></section><p class="quote-caption auth-note">请在可信任的 HTTPS 站点使用正式账户。本机预览的账户和数据仅保存在运行期间的内存中。</p>`;
}
let installPrompt=null;
function render() {
  const {page,id}=current();
  const pages={home,watchlist,catalog,news,alerts,whales:()=>errorBox("whales")+whalePage(state.whales,state.profile?.telegram_configured),notifications,profile,settings,welcome,login,register,add:addAsset,"create-alert":()=>createAlert(id),asset:()=>detail(id)};
  content.innerHTML=state.loading&&!["welcome","login","register"].includes(page)?empty("正在读取你的工作区…"):(pages[page]||(()=>back()+empty("找不到这个页面")))();
  document.title=`${({home:"市场总览",watchlist:"我的关注",catalog:"资产目录",news:"新闻中心",alerts:"价格提醒",notifications:"通知中心",profile:"个人中心",settings:"设置",welcome:"欢迎",login:"登录",register:"创建账户",add:"添加资产","create-alert":"创建提醒",asset:"资产详情"})[page]||"MIRAO"} · MIRAO`;
  const active=({asset:"watchlist",catalog:"watchlist",add:"watchlist","create-alert":"alerts",notifications:"alerts",whales:"alerts",settings:"profile"})[page]||page;
  if(page==="whales")document.title="链上巨鲸仓位 · MIRAO";
  document.querySelectorAll("[data-page]").forEach(a=>{if(a.dataset.page===active)a.setAttribute("aria-current","page");else a.removeAttribute("aria-current");});
  nav.hidden=["welcome","login","register"].includes(page);
  requestAnimationFrame(positionNavIndicator);
}
let routeAnimationTimer;
async function route() {
  if(current().page==="account")history.replaceState(null,"","#login");
  if(!state.session&&!(["login","register","welcome"].includes(current().page)))history.replaceState(null,"","#login");
  state.searchSequence++;
  clearTimeout(routeAnimationTimer);
  content.classList.remove("screen-animated");
  render();window.scrollTo(0,0);content.focus({preventScroll:true});
  if(appUpdater.pending&&applyAppUpdate())return;
  if (!reducedMotion.matches) {
    // Restart only on navigation. Quote refreshes should not replay entrance motion.
    void content.offsetWidth;
    content.classList.add("screen-animated");
    routeAnimationTimer = setTimeout(() => content.classList.remove("screen-animated"), 850);
  }
  const {page,id}=current();
  if(page==="asset")await loadDetail(id);
  if(page==="whales"){await load(["whales"]);if(current().page==="whales"&&!interacting())render();}
  if(page==="settings"&&state.bot===null&&state.profile?.telegram_bot_available){
    state.bot={};
    try{state.bot=await request("/api/client-profile/telegram/bot");}catch{/* Chat ID binding remains available. */}
    if(current().page==="settings"&&!interacting())render();
  }
}
async function refresh() {
  if(state.refreshing||!state.session||document.hidden||!navigator.onLine)return;
  state.refreshing=true;
  try {
    const before=JSON.stringify([state.assets,state.watchlist,state.hiddenAssets,state.alerts,state.subs,state.news,state.notifications,state.profile,state.errors,current().page==="whales"?state.whales:null]);
    await load(Object.keys(endpoints));
    paintQuotes();
    if(before!==JSON.stringify([state.assets,state.watchlist,state.hiddenAssets,state.alerts,state.subs,state.news,state.notifications,state.profile,state.errors,current().page==="whales"?state.whales:null])&&
       ["home","watchlist","catalog","asset","alerts","whales","news","notifications","profile","settings"].includes(current().page)&&!interacting())render();
    const {page,id}=current();
    const asset=state.assets.find(a=>a.id===id);
    if(page==="asset"&&asset?.venue==="BINANCE"&&kind(asset)==="合约")await loadMetrics(id);
  } finally {state.refreshing=false;}
}
let refreshTimer;
function scheduleRefresh() {clearInterval(refreshTimer);refreshTimer=setInterval(refresh,state.refreshSeconds*1000);}
async function mutate(button,operation,keys) {
  if(button.disabled)return;
  button.disabled=true;
  try {await operation();await load(keys);render();}
  catch(error){toast(error.message);}
  finally {button.disabled=false;}
}
content.addEventListener("click",async event=>{
  if(event.target.closest('[data-action-link="subscriptions"]')){state.alertTab="subs";store.set("alertTab","subs");}

  const summary=event.target.closest("summary.sub-head");
  if(summary){
    const card=summary.closest("details.sub-card"),assetId=Number(card.dataset.asset);
    setTimeout(()=>{if(card.isConnected){if(card.open)state.subOpen.add(assetId);else state.subOpen.delete(assetId);}},0);
  }
  const mask=event.target.closest(".sheet-mask");
  if(mask&&!event.target.closest(".sheet")){state.subSheet=false;state.subSearch="";render();return;}
  const button=event.target.closest("button");if(!button)return;
  if(button.dataset.themeChoice){
    store.set("theme",button.dataset.themeChoice);
    applyTheme(button.dataset.themeChoice);
    render();
    return;
  }
  for(const [attribute,key] of [["filter","filter"],["newsFilter","newsFilter"],["notificationFilter","notificationFilter"]]) {
    if(button.dataset[attribute]!==undefined){state[key]=button.dataset[attribute];render();return;}
  }
  const {action,id}=button.dataset;
  if(action==="whale-refresh"){await mutate(button,async()=>{},["whales"]);return;}
  if(action==="whale-delete"&&confirm("删除这个市场的链上巨鲸订阅？")){
    await mutate(button,()=>request(`/api/whales/subscriptions/${id}`,{method:"DELETE"}),["whales"]);return;
  }
  if(action==="alert-tab"){state.alertTab=button.dataset.tab==="subs"?"subs":"rules";store.set("alertTab",state.alertTab);render();return;}
  if(action==="start"){store.set("welcome","seen");location.hash=state.session?"home":"login";}
  if(action==="logout")await mutate(button,async()=>{
    state.whales={markets:[],subscriptions:[],positions:[],events:[],runtime:{}};
    await request("/api/auth/logout",{method:"POST"});state.session=null;
    state.watchlist=[];state.hiddenAssets=[];state.alerts=[];state.subs=[];state.notifications=[];state.profile=null;state.bot=null;
    state.socket?.close();location.hash="login";toast("已退出登录");
  },[]);
  if(action==="retry"){button.disabled=true;await load(Object.keys(endpoints));render();}
  if(action==="detail-retry"){button.disabled=true;await loadDetail(Number(id));}
  if(action==="follow")await mutate(button,async()=>{
    const existing=followed(id);
    if(!existing&&state.hiddenAssets.includes(Number(id)))await request(`/api/client-assets/${id}/hidden`,{method:"DELETE"});
    await request(`/api/watchlist${existing?`/${id}`:""}`,{method:existing?"DELETE":"POST",body:existing?undefined:{asset_id:Number(id)}});
    toast(existing?"已取消关注，提醒规则仍可单独管理。":"已加入关注列表。");
  },["watchlist","hiddenAssets"]);
  if(action==="hide-asset"){
    const asset=state.assets.find(a=>a.id===Number(id));
    if(asset&&confirm(`从你的资产目录删除 ${asset.symbol}？该资产的关注会移除，相关提醒会暂停；以后可重新添加。`))
      await mutate(button,async()=>{await request(`/api/client-assets/${id}/hidden`,{method:"PUT"});toast(`${asset.symbol} 已从你的目录删除`);},["hiddenAssets","watchlist","alerts"]);
  }
  if(action==="telegram-test")await mutate(button,async()=>{
    await request("/api/client-profile/telegram/test",{method:"POST"});toast("Telegram 测试消息已发送，请检查接收会话。");
  },[]);
  if(action==="toggle-alert")await mutate(button,()=>request(`/api/alert-rules/${id}`,{method:"PATCH",body:{enabled:!state.alerts.find(r=>r.id===Number(id)).enabled}}),["alerts"]);
  if(action==="delete-alert"&&confirm("删除这条价格提醒？"))await mutate(button,()=>request(`/api/alert-rules/${id}`,{method:"DELETE"}),["alerts"]);
  if(action==="add-result") {
    const item=state.searchResults[Number(button.dataset.index)];if(!item)return;
    await mutate(button,async()=>{
      let asset=state.assets.find(a=>a.symbol===item.symbol&&a.venue===item.venue&&a.segment===item.segment);
      if(!asset) {
        asset=await request("/api/assets/quick",{method:"POST",body:{market:item.market,symbol:item.symbol,segment:item.segment,name:item.name}});
        // Persist the created asset locally before following so a failed follow can be retried safely.
        state.assets.push(asset);
      }
      await request(`/api/client-assets/${asset.id}/hidden`,{method:"DELETE"});
      await request("/api/watchlist",{method:"POST",body:{asset_id:asset.id}});
      toast(`${item.symbol} 已加入关注`);location.hash="watchlist";
    },["assets","watchlist","hiddenAssets","quotes"]);
  }
  if(action==="install"&&installPrompt){await installPrompt.prompt();installPrompt=null;button.hidden=true;}
  if(action==="sub-add-close"){state.subSheet=false;state.subSearch="";render();return;}
  if(action==="sub-add-open"){state.subSheet=true;state.subSearch="";render();const input=$("#sub-search");input?.focus();return;}
  if(action==="sub-add"){
    const assetId=Number(id);
    await mutate(button,async()=>{
      await request("/api/subscriptions",{method:"PUT",body:{asset_id:assetId,alert_type:"whale_print",enabled:true,config:{whale_min_usd:50000}}});
      state.subSheet=false;state.subSearch="";state.subOpen.add(assetId);
      toast("已添加订阅");
    },["subs"]);
    return;
  }
  if(action==="sub-delete"){
    event.preventDefault();
    const assetId=Number(id);
    const asset=state.assets.find(a=>a.id===assetId);
    if(!confirm(`删除 ${asset?asset.symbol:"该币种"} 的全部推送订阅？`))return;
    await mutate(button,async()=>{
      for(const s of state.subs.filter(x=>x.asset.id===assetId))await request(`/api/subscriptions/${s.id}`,{method:"DELETE"});
      state.subOpen.delete(assetId);
    },["subs"]);
    return;
  }
});
content.addEventListener("change",async event=>{
  const subToggle=event.target.closest?event.target.closest("[data-sub-toggle]"):null;
  if(subToggle){
    const assetId=Number(subToggle.dataset.asset),alertType=subToggle.dataset.subToggle,on=subToggle.checked;
    const existing=state.subs.find(s=>s.asset.id===assetId&&s.alert_type===alertType);
    const config=existing?.config||(alertType==="whale_print"?{whale_min_usd:50000}:{});
    subToggle.disabled=true;
    try{
      await request("/api/subscriptions",{method:"PUT",body:{asset_id:assetId,alert_type:alertType,enabled:on,config}});
      state.subOpen.add(assetId);await load(["subs"]);render();
      const card=content.querySelector(`details.sub-card[data-asset="${assetId}"]`);if(card)card.open=true;
      toast(on?"已开启":"已关闭");
    }catch(error){toast(error.message);if(subToggle.isConnected)subToggle.checked=!on;}
    finally{if(subToggle.isConnected)subToggle.disabled=false;}
    return;
  }
  const subThreshold=event.target.closest?event.target.closest("[data-sub-threshold], [data-sub-cooldown]"):null;
  if(subThreshold){
    const isCooldown=subThreshold.dataset.subCooldown!==undefined;
    const assetId=Number(isCooldown?subThreshold.dataset.subCooldown:subThreshold.dataset.subThreshold),value=Number(subThreshold.value);
    if(!subThreshold.value||!Number.isFinite(value)||(isCooldown?(!Number.isInteger(value)||value<0||value>86400):(value<=0||value>1e12))){toast(isCooldown?"请输入 0–86400 的整数秒":"请输入大于 0 的有效阈值");return;}
    const existing=state.subs.find(s=>s.asset.id===assetId&&s.alert_type==="whale_print");
    subThreshold.disabled=true;
    try{
      await request("/api/subscriptions",{method:"PUT",body:{asset_id:assetId,alert_type:"whale_print",enabled:existing?.enabled??true,config:{...(existing?.config||{}),[isCooldown?"cooldown_seconds":"whale_min_usd"]:value}}});
      state.subOpen.add(assetId);await load(["subs"]);render();
      const card=content.querySelector(`details.sub-card[data-asset="${assetId}"]`);if(card)card.open=true;
      toast(isCooldown?"提醒间隔已保存":"阈值已保存");
    }catch(error){toast(error.message);}
    finally{if(subThreshold.isConnected)subThreshold.disabled=false;}
    return;
  }
  if(event.target.name==="operator") {
    const step=event.target.value==="step";$("#anchor-field").hidden=!step;$("[name=step_anchor]").required=step;$("#value-label").textContent=step?"价格步长":"目标价格";
  }
  if(event.target.name==="market"){state.searchSequence++;state.searchResults=[];$("#search-results").textContent="市场已切换，请重新搜索。";}
});
content.addEventListener("input",event=>{
  if(event.target.matches("[data-whale-search]")){
    const form=event.target.form,select=form.querySelector('[name="coin"]'),previous=select.value;
    const matches=matchingWhaleMarkets(state.whales?.markets||[],state.whales?.subscriptions||[],event.target.value);
    select.replaceChildren(...matches.map(m=>new Option(`${m.coin} · ${m.name}`,m.coin)));
    if(matches.some(m=>m.coin===previous))select.value=previous;
    form.querySelector('[type="submit"]').disabled=!matches.length;
    form.querySelector("[data-whale-search-count]").textContent=matches.length?`${matches.length} 个市场可添加`:"没有匹配的市场；仅显示官方已核验的合约。";
  }
  if(event.target.id==="sub-search"){
    state.subSearch=event.target.value;
    const list=$("#sub-pool-list");
    if(list)list.innerHTML=poolRows(subPool());
  }
});
content.addEventListener("submit",async event=>{
  event.preventDefault();const form=event.target, values=Object.fromEntries(new FormData(form));
  const button=form.querySelector('[type="submit"]');if(button.disabled)return;
  if(form.classList.contains("whale-subscription-form")){
    await mutate(button,async()=>{await request("/api/whales/subscriptions",{method:"PUT",body:{coin:values.coin,enabled:values.enabled==="on",min_position_usd:Number(values.min_position_usd),cooldown_seconds:Number(values.cooldown_seconds)}});toast("巨鲸订阅已保存；服务会自动发现地址。");},["whales"]);return;
  }
  if(form.id==="login-form"||form.id==="register-form") {
    button.disabled=true;
    const error=form.querySelector(".form-error");error.textContent="";
    try {
      const endpoint=form.id==="login-form"?"login":"register";
      state.session=await request(`/api/auth/${endpoint}`,{method:"POST",body:{username:values.username,password:values.password}});
      await load(Object.keys(endpoints));state.loading=false;
      store.set("welcome","seen");location.hash="home";render();connectSocket();
    } catch(failure){if(form.isConnected)error.textContent=failure.message;else toast(failure.message);}
    finally{button.disabled=false;}
    return;
  }
  if(form.id==="telegram-request-form"){
    button.disabled=true;const error=form.querySelector(".form-error");error.textContent="";
    try{
      await request("/api/client-profile/telegram/challenge",{method:"POST",body:{chat_id:values.chat_id.trim()}});
      state.telegramChallengeSent=true;render();toast("验证码已发送到 Telegram，请在下方输入。");
    }catch(failure){if(form.isConnected)error.textContent=failure.message;else toast(failure.message);}
    finally{button.disabled=false;}
    return;
  }
  if(form.id==="telegram-confirm-form"){
    button.disabled=true;const error=form.querySelector(".form-error");error.textContent="";
    try{
      await request("/api/client-profile/telegram/confirm",{method:"POST",body:{code:values.code.trim()}});
      state.telegramChallengeSent=false;await load(["profile"]);render();toast("Telegram 已绑定，后续提醒将发送到这个会话。");
    }catch(failure){if(form.isConnected)error.textContent=failure.message;else toast(failure.message);}
    finally{button.disabled=false;}
    return;
  }
  if(form.id==="settings-form"){state.refreshSeconds=Number(values.refresh);store.set("refresh",values.refresh);scheduleRefresh();toast("刷新设置已保存");return;}
  if(form.id==="alert-form") {
    button.disabled=true;$("#form-error").textContent="";
    try {await request("/api/alert-rules",{method:"POST",body:alertPayload(values)});await load(["alerts"]);toast("价格提醒已创建");location.hash="alerts";}
    catch(error){if(form.isConnected)$("#form-error").textContent=error.message;else toast(error.message);}
    finally{button.disabled=false;}return;
  }
  if(form.id==="search-form") {
    const sequence=++state.searchSequence;button.disabled=true;$("#search-results").innerHTML=empty("正在搜索真实资产目录…");
    try {
      const local=state.assets.filter(a=>marketMatches(a,values.market==="CRYPTO"?"crypto":values.market)&&`${a.symbol} ${a.name}`.toLowerCase().includes(values.query.trim().toLowerCase()));
      const result=values.market==="KRX"?{data:local}:await request(`/api/assets/search?${new URLSearchParams({q:values.query.trim(),market:values.market})}`);
      if(sequence!==state.searchSequence||!form.isConnected)return;
      state.searchResults=result.data.map(a=>({...a,market:values.market}));
      $("#search-results").innerHTML=state.searchResults.length?state.searchResults.map((item,index)=>`<div class="asset-row"><div class="asset-info"><strong>${e(item.symbol)}</strong><small>${e(item.name)} · ${e(item.venue)} · ${kind(item)}</small></div><button data-action="add-result" data-index="${index}" aria-label="添加 ${e(item.symbol)} ${kind(item)}">＋ 关注</button></div>`).join(""):empty("未找到匹配资产",values.market==="KRX"?"韩股当前只支持库内已有资产。":"尝试完整代码或其他市场。");
    }catch(error){if(sequence===state.searchSequence&&form.isConnected)$("#search-results").innerHTML=`<div class="notice error">${e(error.message)}</div>`;}
    finally{button.disabled=false;}
  }
});
let reconnectTimer, reconnectDelay=1000;
function connectSocket() {
  if(!state.session||!navigator.onLine||document.hidden)return;
  if(state.socket&&[WebSocket.CONNECTING,WebSocket.OPEN].includes(state.socket.readyState))return;
  const socket=new WebSocket(`${location.protocol==="https:"?"wss:":"ws:"}//${location.host}/ws/market`);state.socket=socket;
  socket.onopen=()=>{state.socketUp=true;reconnectDelay=1000;updateConnection();};
  socket.onmessage=event=>{
    try {
      const payload=JSON.parse(event.data);const rows=payload.type==="market_snapshot"?payload.data:Array.isArray(payload)?payload:[payload];
      for(const row of rows){if(!row.asset_id)continue;const i=state.quotes.findIndex(q=>q.asset_id===row.asset_id);if(i<0)state.quotes.push(row);else state.quotes[i]={...state.quotes[i],...row};}
      updateConnection();
      paintQuotes();
    }catch{/* A malformed frame must not prevent HTTP refresh. */}
  };
  socket.onerror=()=>socket.close();
  socket.onclose=()=>{state.socketUp=false;updateConnection();clearTimeout(reconnectTimer);reconnectTimer=setTimeout(connectSocket,reconnectDelay);reconnectDelay=Math.min(reconnectDelay*2,30000);};
}
const appUpdater=createAppUpdater({version:APP_VERSION,location,storage:()=>window.sessionStorage,
  online:()=>navigator.onLine&&!document.hidden,blocked:interacting,
  reload:url=>location.replace(url),
  waiting:()=>toast("新版已就绪，完成当前操作后会自动更新。"),
  stalled:()=>toast("更新暂未完成，已停止重复刷新；当前页面可继续使用。")});
let versionCheck=null;
async function checkAppVersion(){
  if(!navigator.onLine||document.hidden)return;
  if(versionCheck)return versionCheck;
  versionCheck=(async()=>{
    try{
      const response=await fetch("/api/client-version",{cache:"no-store",credentials:"same-origin"});
      if(response.ok)appUpdater.offer((await response.json()).version);
    }catch{/* A failed version check must not interrupt market data. */}
  })();
  try{await versionCheck;}finally{versionCheck=null;}
}
function applyAppUpdate() {
  return appUpdater.apply();
}
window.addEventListener("hashchange",route);
window.addEventListener("online",()=>{updateConnection();refresh();connectSocket();checkAppVersion();});
window.addEventListener("offline",updateConnection);
document.addEventListener("visibilitychange",()=>{if(!document.hidden){applyAppUpdate();refresh();connectSocket();checkAppVersion();}else{clearTimeout(reconnectTimer);state.socket?.close();}});
content.addEventListener("focusout",()=>setTimeout(applyAppUpdate,0));
window.addEventListener("beforeinstallprompt",event=>{event.preventDefault();installPrompt=event;if(current().page==="settings")render();});
try {state.session=await request("/api/auth/session");} catch {state.session=null;}
if(!location.hash)history.replaceState(null,"",state.session?"#home":"#login");
if(current().page==="account")history.replaceState(null,"","#login");
if(state.session&&["login","register"].includes(current().page))history.replaceState(null,"","#home");
if(!state.session&&!(["login","register","welcome"].includes(current().page)))history.replaceState(null,"","#login");
if(state.session)await load(Object.keys(endpoints));
state.loading=false;
await route();scheduleRefresh();connectSocket();checkAppVersion();
window.addEventListener("pageshow",()=>{refresh();connectSocket();checkAppVersion();});
setInterval(checkAppVersion,2*60*1000);
if("serviceWorker" in navigator&&window.isSecureContext) {
  navigator.serviceWorker.addEventListener("controllerchange",()=>{
    // First installation or a changed worker alone does not require a page reload.
    checkAppVersion();
  });
  navigator.serviceWorker.register(`/sw.js?v=${APP_VERSION}`,{updateViaCache:"none"}).then(registration=>{
    const check=()=>{if(navigator.onLine&&!document.hidden)registration.update().catch(()=>{});};
    check();
    window.addEventListener("pageshow",check);
    document.addEventListener("visibilitychange",check);
    setInterval(check,10*60*1000);
  }).catch(()=>{if(current().page==="settings")toast("离线支持未启用；仍可正常在线使用。");});
}

document.addEventListener("keydown",event=>{
  if(!state.subSheet)return;
  if(event.key==="Escape"){state.subSheet=false;state.subSearch="";render();return;}
  if(event.key==="Tab"){
    const controls=[...content.querySelectorAll('.sheet button:not(:disabled),.sheet input:not(:disabled)')];
    const first=controls[0],last=controls.at(-1);
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
});
