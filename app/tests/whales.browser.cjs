const {chromium}=require(process.env.PLAYWRIGHT_MODULE||"playwright");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{})});
  const context=await browser.newContext({viewport:{width:390,height:844}});
  const page=await context.newPage();
  const errors=[];page.on("pageerror",error=>errors.push(String(error)));
  const base=process.env.RADAR_TEST_BASE_URL;
  const output=path.resolve(__dirname,"../../test-results");fs.mkdirSync(output,{recursive:true});
  try{
    await page.goto(base+"/#welcome");
    const release=fs.readFileSync(path.resolve(__dirname,"../web/version.txt"),"utf8").trim();
    await page.locator(".app-version").waitFor();
    assert.equal(await page.locator(".app-version").textContent(),`当前版本 ${release}`);
    await page.goto(base+"/#register");
    await page.getByLabel("用户名",{exact:true}).fill("whale_ui_"+Date.now());
    await page.getByLabel("密码",{exact:true}).fill("synthetic-browser-password");
    await page.getByRole("button",{name:"注册并进入"}).click();
    await page.getByRole("heading",{name:"市场，尽在掌握"}).waitFor();
    await page.goto(base+"/#alerts");
    await page.locator('a[href="#whales"]').click();
    await page.getByRole("heading",{name:"链上巨鲸仓位",exact:true}).waitFor();
    const add=page.locator("form.whale-subscription-form:not([data-id])");
    await add.getByLabel("搜索可添加市场").fill("koru");
    await add.getByRole("button",{name:"开启自动发现"}).click();
    const form=page.locator("form.whale-subscription-form[data-id]");
    await form.waitFor();
    await page.getByText("数据已过期",{exact:false}).waitFor();
    await page.getByText("+$12,345.67",{exact:true}).waitFor();
    assert.equal((await page.request.post(base+"/__fixture__/whale-event")).status(),200);
    await page.getByRole("button",{name:"刷新状态"}).click();
    await page.getByRole("heading",{name:"新发现已有仓位 · 多单"}).waitFor();
    await add.getByLabel("搜索可添加市场").fill("no-such-market");
    assert.equal(await add.getByRole("button",{name:"开启自动发现"}).isDisabled(),true);
    await add.getByLabel("搜索可添加市场").fill("gold");
    assert.equal(await add.locator('select[name="coin"]').inputValue(),"xyz:GOLD");
    await add.getByRole("button",{name:"开启自动发现"}).click();
    const gold=page.locator("form.whale-subscription-form[data-id]").filter({has:page.locator('input[name="coin"][value="xyz:GOLD"]')});
    await gold.waitFor();
    assert.equal((await (await page.request.get(base+"/api/whales")).json()).subscriptions.length,2);
    page.once("dialog",dialog=>dialog.accept());
    await gold.getByRole("button",{name:"删除订阅"}).click();
    await page.waitForFunction(async()=>(await (await fetch("/api/whales")).json()).subscriptions.length===1);
    for(const theme of ["light","dark"]){
      await page.goto(base+"/#settings");
      await page.getByRole("button",{name:theme==="light"?"浅色":"夜间",exact:true}).click();
      await page.goto(base+"/#whales");
      await page.getByRole("heading",{name:"链上巨鲸仓位",exact:true}).waitFor();
      for(const width of [320,390,768,1440]){
        await page.setViewportSize({width,height:900});
        await page.waitForTimeout(150);
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`Overflow ${theme} ${width}`);
        if(width===390||width===1440)await page.screenshot({path:path.join(output,`whales-${theme}-${width}.png`),fullPage:true});
      }
    }
    await form.getByLabel("巨鲸仓位阈值（USD）").fill("3000000");
    await form.getByRole("button",{name:"保存设置"}).click();
    await page.getByText("尚无符合阈值的已核验仓位",{exact:true}).waitFor();
    await form.getByLabel("开启自动发现和提醒").uncheck();
    await form.getByRole("button",{name:"保存设置"}).click();
    await page.waitForFunction(async()=>!(await (await fetch("/api/whales")).json()).subscriptions[0].enabled);
    page.once("dialog",dialog=>dialog.accept());
    await form.getByRole("button",{name:"删除订阅"}).click();
    await page.waitForFunction(async()=>(await (await fetch("/api/whales")).json()).subscriptions.length===0);
    await page.evaluate(()=>navigator.serviceWorker.ready);
    const cached=await page.evaluate(async()=>{const keys=await caches.keys();const urls=[];for(const key of keys){const cache=await caches.open(key);for(const req of await cache.keys())urls.push(new URL(req.url).pathname);}return urls;});
    assert.ok(cached.includes("/static/whales.js"));
    assert.ok(!cached.some(url=>url.startsWith("/api/")));
    assert.deepEqual(errors,[]);
    console.log("WHALE_BROWSER_OK: About version, unrealized P&L, real auth/CRUD, catalog search, non-equity subscription, synthetic position/event, stale state, 320-1440px, light/dark, private cache exclusion");
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
