import {escapeHTML as e,number as n,supportsSubscriptions,timestamp} from "./mobile-core.js?v=2026.10.17.1";

const names={rsi:"RSI 14",macd:"MACD 12/26/9",ma:"MA / EMA 金叉与死叉",kdj:"KDJ 9/3/3",volume:"成交额异动",fibonacci:"斐波那契回撤",divergence:"RSI 顶 / 底背离"};
const defaults={timeframe:"1h",indicators:["rsi","macd","ma","kdj","volume"],rsi_low:30,rsi_high:70,ma_type:"EMA",ma_fast:9,ma_slow:21,volume_multiple:2,fib_low:null,fib_high:null,fib_trend:"up",fib_tolerance_pct:0.3,cooldown_seconds:3600,ai_enabled:true};
const options=(items,value)=>items.map(([v,label])=>`<option value="${e(v)}"${String(value)===v?" selected":""}>${e(label)}</option>`).join("");

export function budgetCard(data){
  const g=data?.gemini;
  if(!g)return '<div class="notice">正在读取 Gemini 配置…</div>';
  const u=g.usage;
  return `<section class="card form-card"><div class="section-title"><h2>Gemini 指标解读</h2><span class="tag">${g.configured?"已启用":"等待服务器配置"}</span></div><p>${e(g.model)} · ${e(g.provider)}</p><p class="muted">信号触发后才分析，同根 K 线的多个信号合并处理。未配置或请求失败时，技术信号仍可发送。</p>${g.budget_owner&&u?`<div class="stats"><div><strong>$${n(u.estimated_usd,4)}</strong><small>${e(u.month)} 本项目估算费用</small></div><div><strong>$${n(g.threshold_usd,2)}</strong><small>Telegram 提醒线</small></div><div><strong>${n(u.calls,0)}</strong><small>请求次数</small></div></div><p class="quote-caption">含输入、输出和思考 Token；按 Google 账单月份（美国太平洋时间）统计。达到提醒线后继续运行。</p>${u.unverified_calls?`<p class="notice error">${n(u.unverified_calls,0)} 次请求费用尚未核实，未计入上方估算，请同时核对 Google 账单。</p>`:""}<p class="quote-caption">${g.billing_connected?"已配置 Cloud Budget 账单监听，账单金额会另行通知。":"当前为本项目 Token 估算；Google 实际账单提醒需配置 Cloud Budget 连接。"}</p>`:""}</section>`;
}

function form(assets,sub){
  const c={...defaults,...sub?.config};
  const fibonacci=c.indicators.includes("fibonacci");
  const field=(name,label,min,max,step="1")=>`<label>${label}<input name="${name}" type="number" inputmode="decimal" min="${min}" max="${max}" step="${step}" value="${e(c[name]??"")}"${name.startsWith("fib_")&&!fibonacci?" disabled":" required"}></label>`;
  return `<form data-technical-form class="technical-form">${sub?`<input type="hidden" name="asset_id" value="${sub.asset.id}">`:`<label>Binance USDT 合约<select name="asset_id" required><option value="">选择合约</option>${assets.map(a=>`<option value="${a.id}">${e(a.symbol)} · ${e(a.name)}</option>`).join("")}</select></label>`}<div class="grid-two"><label>K 线周期<select name="timeframe">${options([["15m","15 分钟"],["1h","1 小时"],["4h","4 小时"],["1d","日线"]],c.timeframe)}</select></label>${field("cooldown_seconds","提醒间隔（秒）",0,86400)}</div><fieldset><legend>触发指标</legend><div class="signal-checks">${Object.entries(names).map(([key,label])=>`<label><input type="checkbox" name="indicators" value="${key}"${c.indicators.includes(key)?" checked":""}> ${label}</label>`).join("")}</div></fieldset><div class="grid-two">${field("rsi_low","RSI 下限",1,99,"any")}${field("rsi_high","RSI 上限",1,99,"any")}<label>均线算法<select name="ma_type">${options([["EMA","EMA 指数均线"],["MA","MA 简单均线"]],c.ma_type)}</select></label>${field("ma_fast","短均线周期",2,99)}${field("ma_slow","长均线周期",3,100)}${field("volume_multiple","成交额 / 前 20 根均值",1.1,100,"any")}</div><details data-fibonacci-settings${fibonacci?" open":" hidden"}><summary>斐波那契锚点（必填）</summary><p class="muted">请选择一个波段，填写它的真实低点和高点价格，用于计算回撤位；低点须小于高点。</p><div class="grid-two">${field("fib_low","低点价格",0.00000001,1e12,"any")}${field("fib_high","高点价格",0.00000001,1e12,"any")}<label>波段方向<select name="fib_trend">${options([["up","上涨波段回撤"],["down","下跌波段反弹"]],c.fib_trend)}</select></label>${field("fib_tolerance_pct","接近价位的容差（%）",0.01,5,"any")}</div></details><div class="signal-checks"><label><input type="checkbox" name="enabled"${!sub||sub.enabled?" checked":""}> 开启监控</label><label><input type="checkbox" name="ai_enabled"${c.ai_enabled?" checked":""}> 触发后由 Gemini 解读</label></div><p class="form-error down" role="alert"></p><button type="submit" class="primary full">${sub?"保存信号设置":"添加技术信号订阅"}</button></form>`;
}

export function technicalPayload(formData){
  const config={...defaults};
  for(const key of ["timeframe","ma_type","fib_trend"])config[key]=formData.get(key);
  for(const key of ["rsi_low","rsi_high","ma_fast","ma_slow","volume_multiple","fib_tolerance_pct","cooldown_seconds"])config[key]=Number(formData.get(key));
  for(const key of ["fib_low","fib_high"])config[key]=formData.get(key)?Number(formData.get(key)):null;
  config.indicators=formData.getAll("indicators");config.ai_enabled=formData.has("ai_enabled");
  if(!config.indicators.length)throw new Error("请至少选择一个触发指标。");
  const fail=(message,field)=>{throw Object.assign(new Error(message),{field});};
  const assetId=Number(formData.get("asset_id"));
  if(!Number.isInteger(assetId)||assetId<=0)fail("请选择 Binance USDT 合约。","asset_id");
  if(config.rsi_low>=config.rsi_high)fail("RSI 下限须小于上限。","rsi_low");
  if(config.ma_fast>=config.ma_slow)fail("均线短周期须小于长周期。","ma_fast");
  if(config.indicators.includes("fibonacci")){
    for(const [key,label] of [["fib_low","低点"],["fib_high","高点"]]){
      if(!Number.isFinite(config[key])||config[key]<=0||config[key]>1e12)fail(`已选择斐波那契回撤，请填写有效的${label}价格。`,key);
    }
    if(config.fib_low>=config.fib_high)fail("斐波那契低点价格须小于高点价格。","fib_low");
  }else{config.fib_low=null;config.fib_high=null;config.fib_tolerance_pct=defaults.fib_tolerance_pct;config.fib_trend=defaults.fib_trend;}
  return {asset_id:assetId,alert_type:"technical_signal",enabled:formData.has("enabled"),config};
}

export function syncTechnicalForm(form){
  const enabled=form.querySelector('[name="indicators"][value="fibonacci"]').checked;
  const settings=form.querySelector("[data-fibonacci-settings]");
  settings.hidden=!enabled;settings.open=enabled;
  for(const input of settings.querySelectorAll("input,select")){
    if(input.tagName==="INPUT")input.required=enabled;
    input.disabled=!enabled;
  }
  form.querySelector(".form-error").textContent="";
}

export function signalsPage(state){
  const subs=state.subs.filter(s=>s.alert_type==="technical_signal");
  const used=new Set(subs.map(s=>s.asset.id));
  const assets=state.assets.filter(a=>a.enabled!==false&&supportsSubscriptions(a)&&!used.has(a.id)&&!state.hiddenAssets.includes(a.id));
  const states=state.signals?.states||[];
  return `<a class="back" href="#alerts">← 返回提醒中心</a><div class="page-heading"><div><p class="eyebrow">TECHNICAL SIGNALS</p><h1>技术信号与 AI</h1></div></div>${budgetCard(state.signals)}<div class="notice">只检测已收盘 K 线。开启或更改参数后先建立基线，从下一根收盘开始提醒。背离需右侧 3 根收盘确认；永续合约使用成交额指标，不显示股票换手率。</div>${!state.profile?.telegram_configured?'<p class="notice">尚未绑定 Telegram，信号会保存在通知中心。<a href="#settings">前往绑定 →</a></p>':""}<div class="sub-grid">${subs.map(sub=>{const status=states.find(r=>r.subscription_id===sub.id),s=status?.snapshot;return `<section class="card form-card"><div class="section-title"><h2>${e(sub.asset.symbol)}</h2><span class="tag">${sub.enabled?"监控中":"已暂停"}</span></div>${s?`<p class="quote-caption">最近核验：${e(timestamp(status.updated_at)?.toLocaleString("zh-CN")??"未提供")} · 收盘 $${n(s.close,6)} · ${e(s.timeframe)}</p><div class="signal-values">RSI ${n(s.indicators.rsi,2)} · DIF ${n(s.indicators.dif,4)} / DEA ${n(s.indicators.dea,4)} · K/D/J ${n(s.indicators.k,2)} / ${n(s.indicators.d,2)} / ${n(s.indicators.j,2)}</div>${s.message?`<p class="signal-message">${e(s.message)}</p>`:`<p class="muted">${s.baseline?"已建立基线，等待下一根收盘。":s.skip_reason==="cooldown"?"本次触发处于提醒间隔内。":"本周期没有新的触发信号。"}</p>`}`:'<p class="muted">等待信号服务核验；服务每分钟检查一次。</p>'}${form([],sub)}<button class="danger full" data-action="delete-technical" data-id="${sub.id}">删除此技术信号订阅</button></section>`;}).join("")}</div><details class="card form-card"${subs.length?"":" open"}><summary>＋ 添加技术信号订阅</summary>${assets.length?form(assets,null):'<p class="muted">请先在资产目录添加 Binance USDT 合约；每个合约可配置一组信号。</p>'}</details>`;
}
