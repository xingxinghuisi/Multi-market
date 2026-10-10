const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
const path = require("node:path");
(async()=>{
  const browser = await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{})});
  const context = await browser.newContext({viewport:{width:390,height:844}});
  const page = await context.newPage();
  const errors=[];
  page.on("pageerror",error=>errors.push(String(error)));
  const base=process.env.RADAR_TEST_BASE_URL || "http://127.0.0.1:60439";
  try{
    await page.goto(base+"/#register");
    await page.locator('#register-form [name="username"]').fill("ui_"+Date.now());
    await page.locator('#register-form [name="password"]').fill("synthetic-test-password");
    const registration=page.waitForResponse(r=>r.url().endsWith("/api/auth/register"));
    await page.getByRole("button",{name:"注册并进入"}).click();
    assert.equal((await registration).status(),201);
    await page.getByRole("heading",{name:"市场，尽在掌握"}).waitFor(); await page.evaluate(()=>navigator.serviceWorker.ready); await page.waitForFunction(()=>!!navigator.serviceWorker.controller);
    await page.goto(base+"/#alerts");
    await page.getByRole("tab",{name:"推送订阅",exact:true}).click();
    await page.getByRole("button",{name:"＋ 添加币种",exact:true}).click();
    await page.getByRole("dialog",{name:"添加币种"}).waitFor();
    await page.getByRole("button",{name:"添加 BTCUSDT",exact:true}).click();
    await page.locator('.sub-card[open]').waitFor();
    const threshold=page.getByLabel("大额成交阈值（USDT）",{exact:true});
    await threshold.fill("8000");
    await threshold.press("Tab");
    await page.getByText("阈值已保存",{exact:true}).waitFor();
    const cooldown=page.getByLabel("提醒间隔（秒）",{exact:false});
    await cooldown.fill("60");
    await cooldown.press("Tab");
    await page.getByText("提醒间隔已保存",{exact:true}).waitFor();
    await page.locator(".switch").filter({has:page.locator('[data-sub-toggle="longshort_digest"]')}).click();
    await page.waitForFunction(()=>document.querySelector('[data-sub-toggle="longshort_digest"]').checked);
    await page.getByText("已开启",{exact:true}).waitFor();
    const rows=await (await page.request.get(base+"/api/subscriptions")).json();
    assert.equal(rows.length,2);
    assert.equal(rows.find(s=>s.alert_type==="whale_print").config.whale_min_usd,8000);
    assert.equal(rows.find(s=>s.alert_type==="whale_print").config.cooldown_seconds,60);
    assert.equal(rows.find(s=>s.alert_type==="longshort_digest").enabled,true);
    await page.reload();
    await page.locator('.sub-card').waitFor();
    await page.locator('summary.sub-head').click();
    assert.equal(await threshold.inputValue(),"8000");
    await page.waitForFunction(()=>!document.querySelector("#content").classList.contains("screen-animated"));
    await page.screenshot({path:path.resolve("test-results/subscriptions-mobile-light.png"),fullPage:true});
    await page.getByRole("button",{name:"＋ 添加币种",exact:true}).click();
    await page.getByRole("dialog").waitFor();
    await page.keyboard.press("Escape");
    assert.equal(await page.getByRole("dialog").count(),0);
    await page.goto(base+"/#settings");
    await page.getByRole("button",{name:"夜间",exact:true}).click();
    await page.goto(base+"/#alerts");
    await page.locator('.sub-card').waitFor();
    assert.equal(await page.locator("html").getAttribute("data-theme"),"dark");
    await page.waitForFunction(()=>!document.querySelector("#content").classList.contains("screen-animated"));
    await page.screenshot({path:path.resolve("test-results/subscriptions-mobile-dark.png"),fullPage:true});
    for(const width of [320,390,1440]){
      await page.setViewportSize({width,height:900});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth), "overflow at "+width);
    }
    await page.waitForFunction(()=>!document.querySelector("#content").classList.contains("screen-animated"));
    await page.screenshot({path:path.resolve("test-results/subscriptions-desktop-dark.png"),fullPage:true});
    // Simulate an update after disabling a focused control during a slow write.
    if(!await page.locator(".sub-card").evaluate(el=>el.open))await page.locator("summary.sub-head").click();
    let arrived,release;
    const pending=new Promise(resolve=>{arrived=resolve;});
    const gate=new Promise(resolve=>{release=resolve;});
    await page.route("**/api/subscriptions",async route=>{
      if(route.request().method()==="PUT"){arrived();await gate;}
      await route.continue();
    });
    await page.route("**/api/client-version",route=>route.fulfill({json:{version:"2026.10.11.99"}}));
    await page.locator(".switch").filter({has:page.locator('[data-sub-toggle="longshort_digest"]')}).click();
    await pending;
    let navigations=0;
    const track=frame=>{if(frame===page.mainFrame())navigations++;};
    page.on("framenavigated",track);
    await page.evaluate(()=>{
      document.querySelector("summary.sub-head").click();
      document.activeElement.blur();
      navigator.serviceWorker.dispatchEvent(new Event("controllerchange"));
    });
    await page.waitForTimeout(100);
    assert.equal(navigations,0,"An app update interrupted a pending subscription write");
    const saved=page.waitForResponse(r=>r.url().endsWith("/api/subscriptions")&&r.request().method()==="PUT");
    const reloaded=page.waitForEvent("framenavigated",{predicate:frame=>frame===page.mainFrame()});
    release();await saved;await reloaded;
    await page.waitForLoadState("domcontentloaded");
    await page.unroute("**/api/subscriptions");
    await page.unroute("**/api/client-version");
    await page.getByRole("heading",{name:"推送订阅",exact:true}).waitFor();
    page.off("framenavigated",track);
    const afterUpdate=await (await page.request.get(base+"/api/subscriptions")).json();
    assert.equal(afterUpdate.find(s=>s.alert_type==="longshort_digest").enabled,false);
    const cached=await page.evaluate(async()=>{
      const keys=await caches.keys();
      return (await Promise.all(keys.map(async key=>(await (await caches.open(key)).keys()).map(r=>new URL(r.url).pathname)))).flat();
    });
    assert.ok(cached.includes("/")&&!cached.some(url=>url.startsWith("/api/")));
    const assetId=rows[0].asset.id;
    await page.goto(base+"/#asset/"+assetId);
    await page.getByRole("heading",{name:"1H 多空数据",exact:true}).waitFor();
    await page.getByRole("link",{name:"管理订阅 →",exact:true}).click();
    await page.getByRole("heading",{name:"推送订阅",exact:true}).waitFor();
    page.once("dialog",dialog=>dialog.accept());
    await page.getByRole("button",{name:"删除 BTCUSDT 的订阅",exact:true}).click();
    await page.getByText("还没有推送订阅",{exact:true}).waitFor();
    assert.deepEqual(await (await page.request.get(base+"/api/subscriptions")).json(),[]);
    assert.equal((await page.request.get(base+"/api/assets/"+assetId)).status(),200);
    assert.deepEqual(errors,[]);
    console.log("PASS: mobile/desktop subscriptions, threshold/cooldown persistence, digest toggle, Escape, dark mode, 320px overflow, asset detail entry, deletion preserves market asset. PWA update deferral and public-shell-only caching verified. No external data or messages.");
  }catch(error){ console.error("Page state",page.url(),errors,await page.locator(".form-error").allTextContents()); await page.screenshot({path:path.resolve("test-results/subscription-ui-failure.png"),fullPage:true}); throw error; }finally{
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1});
