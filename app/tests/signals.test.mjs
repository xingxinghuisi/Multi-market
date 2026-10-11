import test from "node:test";
import assert from "node:assert/strict";
import {technicalPayload} from "../web/static/signals.js";
import {apiErrorDetail} from "../web/static/mobile-core.js";

function form(indicators=["rsi","macd"]){
  const data=new FormData();
  for(const [key,value] of Object.entries({asset_id:2,timeframe:"1h",rsi_low:30,rsi_high:70,
    ma_type:"EMA",ma_fast:9,ma_slow:21,volume_multiple:2,fib_low:"",fib_high:"",
    fib_trend:"up",fib_tolerance_pct:0.3,cooldown_seconds:3600,enabled:"on",ai_enabled:"on"}))data.set(key,value);
  for(const indicator of indicators)data.append("indicators",indicator);
  return data;
}

test("Fibonacci selection requires both explicit anchors before a request is made",()=>{
  const data=form(["fibonacci"]);
  assert.throws(()=>technicalPayload(data),error=>error.field==="fib_low"&&/低点价格/.test(error.message));
  data.set("fib_low","90");
  assert.throws(()=>technicalPayload(data),error=>error.field==="fib_high"&&/高点价格/.test(error.message));
  data.set("fib_high","80");
  assert.throws(()=>technicalPayload(data),/低点价格须小于高点价格/);
  data.set("fib_high","110");
  const payload=technicalPayload(data);
  assert.equal(payload.config.fib_low,90);assert.equal(payload.config.fib_high,110);
  assert.equal(payload.config.ai_enabled,true);assert.equal(payload.alert_type,"technical_signal");
});

test("deselecting Fibonacci submits the other indicators without stale anchors",()=>{
  const data=form();data.set("fib_low","99");data.set("fib_high","0");data.set("fib_tolerance_pct","");
  const payload=technicalPayload(data);
  assert.deepEqual(payload.config.indicators,["rsi","macd"]);
  assert.equal(payload.config.fib_low,null);assert.equal(payload.config.fib_high,null);
  assert.equal(payload.config.fib_tolerance_pct,0.3);
});

test("RSI and moving-average relationships produce specific local feedback",()=>{
  const data=form();data.set("rsi_low","80");
  assert.throws(()=>technicalPayload(data),/RSI 下限须小于上限/);
  data.set("rsi_low","30");data.set("ma_fast","30");
  assert.throws(()=>technicalPayload(data),/均线短周期须小于长周期/);
});

test("422 details expose validation messages without echoing submitted values",()=>{
  const message="斐波那契需要明确的高低锚点，且低点小于高点";
  const detail=[{loc:["body"],msg:`Value error, ${message}`,input:{password:"must-never-show"}}];
  assert.equal(apiErrorDetail({detail}),message);
  assert.equal(apiErrorDetail({detail:"服务暂时不可用"}),"服务暂时不可用");
  assert.equal(apiErrorDetail({detail:[{input:"must-never-show"}]}),"请稍后重试");
  assert.equal(apiErrorDetail(null),"请稍后重试");
});
