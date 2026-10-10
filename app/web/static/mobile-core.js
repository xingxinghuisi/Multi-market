export const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
export function number(value, digits = 2) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString("zh-CN", {maximumFractionDigits: digits});
}
export function percent(value) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return `${Number(value) > 0 ? "+" : ""}${number(value)}%`;
}
export function timestamp(value) {
  if (!value) return null;
  // SQLite's naive timestamps in this project are UTC.
  const date = new Date(/(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}
export function safeURL(value) {
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}
export function kind(asset) {
  if (asset.asset_type !== "crypto") return "股票";
  return /FUTURE|PERPETUAL/i.test(asset.segment) || ["USD_M","USD-M","CONTRACT","SWAP"].includes(asset.segment) ? "合约" : "Spot";
}
export function supportsSubscriptions(asset) {
  return asset.asset_type==="crypto" && asset.venue==="BINANCE" && asset.currency==="USDT" && kind(asset)==="合约";
}
export function marketMatches(asset, filter) {
  return filter === "all" || (filter === "crypto" && asset.asset_type === "crypto") ||
    (filter === "KRX" && asset.venue === "KRX") ||
    (filter === "US" && asset.currency === "USD" && asset.asset_type !== "crypto") ||
    (filter === "HK" && (asset.currency === "HKD" || asset.venue === "HKEX"));
}
export function candleSeries(rows) {
  const bars = rows.filter(row => {
    const values = [row.open, row.high, row.low, row.close];
    if (!row.date || values.some(value => value === null || value === undefined || value === "" || !Number.isFinite(Number(value)))) return false;
    const [open, high, low, close] = values.map(Number);
    return low <= Math.min(open, close) && high >= Math.max(open, close) && high >= low;
  }).map(row => ({date: String(row.date), open: Number(row.open), high: Number(row.high),
    low: Number(row.low), close: Number(row.close)})).sort((a, b) => a.date.localeCompare(b.date));
  return bars;
}
export function alertPayload(form) {
  const value = Number(form.value), cooldown = Number(form.cooldown_seconds);
  if (!form.value || !Number.isFinite(value) || value <= 0) throw new Error("请输入大于 0 的价格或步长。");
  if (!Number.isInteger(cooldown) || cooldown < 0) throw new Error("冷却时间需为非负整数。");
  const payload = {asset_id: Number(form.asset_id), metric: "price", operator: form.operator,
    value, cooldown_seconds: cooldown, reset_buffer: 0, enabled: true};
  if (!Number.isInteger(payload.asset_id) || payload.asset_id <= 0) throw new Error("请选择已关注的资产。");
  if (!["crossing_up", "crossing_down", "step"].includes(form.operator)) throw new Error("请选择有效的触发条件。");
  if (form.operator === "step") {
    payload.step_anchor = Number(form.step_anchor);
    if (!Number.isFinite(payload.step_anchor) || payload.step_anchor <= 0) throw new Error("动态追踪需要大于 0 的初始锚点价格。");
  }
  return payload;
}
