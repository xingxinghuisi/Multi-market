/* Automatic updates are bounded even when a proxy keeps serving old assets. */
const KEY="mirao.update-attempts";
const WINDOW=10*60*1000;
export function createAppUpdater({version,location,storage,online,blocked,reload,waiting,stalled,now=Date.now}) {
  let pending=null,issued=false,notified=false;
  function apply(){
    if(!pending||issued||!online())return false;
    if(blocked()){waiting();return false;}
    const url=new URL(location.href);
    let attempts=[];
    try{attempts=JSON.parse(storage()?.getItem(KEY)||"[]");}catch{/* URL marker also survives reloads. */}
    if(!Array.isArray(attempts))attempts=[];
    attempts=attempts.filter(a=>a&&Number.isFinite(a.at)&&now()-a.at<WINDOW&&now()>=a.at);
    // Same stale target: one attempt only. Also bound oscillating backend versions.
    const markerAt=Number(url.searchParams.get("__mirao_update_at"));
    const markerActive=markerAt>0&&now()-markerAt<WINDOW&&now()>=markerAt;
    const markerCount=markerActive?Number(url.searchParams.get("__mirao_update_count")||1):0;
    if((markerActive&&(url.searchParams.get("__mirao_update")===pending||markerCount>=2))||attempts.some(a=>a.target===pending)||attempts.length>=2){
      pending=null;if(!notified){notified=true;stalled();}return false;
    }
    attempts.push({target:pending,at:now()});
    let persisted=false;
    const record=JSON.stringify(attempts);
    try{storage()?.setItem(KEY,record);persisted=storage()?.getItem(KEY)===record;}catch{/* The URL is the fallback guard. */}
    url.searchParams.set("v",pending);
    if(!persisted){
      url.searchParams.set("__mirao_update",pending);
      url.searchParams.set("__mirao_update_at",String(markerActive?markerAt:now()));
      url.searchParams.set("__mirao_update_count",String(markerCount+1));
    }
    pending=null;issued=true;
    reload(url.href);
    return true;
  }
  return {
    get pending(){return pending!==null;},
    apply,
    offer(target){
      if(typeof target!=="string"||!/^\d{4}\.\d{2}\.\d{2}\.\d+$/.test(target))return false;
      if(target===version){pending=null;return false;}
      pending=target;
      return apply();
    },
  };
}
