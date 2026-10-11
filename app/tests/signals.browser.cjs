/* Real isolated API and browser; no paid Gemini calls or live Telegram messages. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||"playwright");
const assert=require("node:assert/strict");
const path=require("node:path");
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{})});
  const page=await browser.newPage({viewport:{width:390,height:844}});
  const errors=[];page.on("pageerror",error=>errors.push(String(error)));
  const base=process.env.RADAR_TEST_BASE_URL||"http://127.0.0.1:60441";
  try{
    await page.goto(base+"/#register");
    await page.locator('#register-form [name="username"]').fill("signal_ui_"+Date.now());
    await page.locator('#register-form [name="password"]').fill("synthetic-browser-password");
    await page.getByRole("button",{name:"注册并进入"}).click();
    await page.getByRole("heading",{name:"市场，尽在掌握"}).waitFor();
    await page.goto(base+"/#alerts");
    await page.getByRole("link",{name:/技术信号与 Gemini 解读/}).click();
    await page.getByRole("heading",{name:"技术信号与 AI",exact:true}).waitFor();
    const form=page.locator('[data-technical-form]').first();
    const options=await form.locator('[name="asset_id"] option').evaluateAll(items=>items.map(i=>({value:i.value,text:i.textContent})));
    const asset=options.find(o=>o.text.includes("BTCUSDT"));assert.ok(asset);
    await form.locator('[name="asset_id"]').selectOption(asset.value);
    await form.locator('[name="timeframe"]').selectOption("4h");
    await form.locator('[name="rsi_high"]').fill("75");
    await form.locator('[name="volume_multiple"]').fill("3");
    await form.locator('[name="ai_enabled"]').uncheck();
    let writes=0;
    page.on("request",r=>{if(r.url().endsWith("/api/subscriptions")&&r.method()==="PUT")writes++;});
    const anchors=form.locator("[data-fibonacci-settings]");
    assert.equal(await anchors.isVisible(),false);
    await form.locator('[name="indicators"][value="fibonacci"]').check();
    assert.equal(await anchors.isVisible(),true);
    assert.equal(await anchors.getAttribute("open"),"");
    await form.getByRole("button",{name:"添加技术信号订阅"}).click();
    assert.equal(await form.locator('[name="fib_low"]').evaluate(el=>el.validity.valueMissing),true);
    assert.match(await form.locator(".form-error").innerText(),/斐波那契回撤/);
    assert.equal(writes,0);
    await form.locator('[name="fib_tolerance_pct"]').fill("");
    await form.locator('[name="indicators"][value="fibonacci"]').uncheck();
    assert.equal(await form.evaluate(el=>el.checkValidity()),true);
    await form.locator('[name="indicators"][value="fibonacci"]').check();
    await form.locator('[name="fib_tolerance_pct"]').fill("0.3");
    await form.locator('[name="fib_low"]').fill("110");
    await form.locator('[name="fib_high"]').fill("90");
    await form.getByRole("button",{name:"添加技术信号订阅"}).click();
    await form.locator(".form-error").filter({hasText:"低点价格须小于高点价格"}).waitFor();
    assert.equal(writes,0);
    await form.locator('[name="fib_low"]').fill("90");
    await form.locator('[name="fib_high"]').fill("110");
    const reject=async route=>{
      if(route.request().method()!=="PUT")return route.continue();
      await route.fulfill({status:422,contentType:"application/json",body:JSON.stringify({detail:[{
        loc:["body"],msg:"Value error, 测试：请检查斐波那契锚点",input:{private:"must-never-show"}}]})});
    };
    await page.route("**/api/subscriptions",reject);
    await form.getByRole("button",{name:"添加技术信号订阅"}).click();
    await form.locator(".form-error").filter({hasText:"测试：请检查斐波那契锚点"}).waitFor();
    assert.ok(!(await form.innerText()).includes("must-never-show"));
    await page.unroute("**/api/subscriptions",reject);
    const saving=page.waitForResponse(r=>r.url().endsWith("/api/subscriptions")&&r.request().method()==="PUT");
    await form.getByRole("button",{name:"添加技术信号订阅"}).click();
    assert.equal((await saving).status(),200);
    const edit=page.locator('[data-technical-form]').filter({has:page.locator('[name="asset_id"][type="hidden"]')});
    await edit.getByRole("button",{name:"保存信号设置"}).waitFor();
    assert.equal(await edit.locator('[name="timeframe"]').inputValue(),"4h");
    assert.equal(await edit.locator('[name="rsi_high"]').inputValue(),"75");
    assert.equal(await edit.locator('[name="ai_enabled"]').isChecked(),false);
    assert.equal(await edit.locator('[name="fib_low"]').inputValue(),"90");
    assert.equal(await edit.locator('[name="fib_high"]').inputValue(),"110");
    await page.reload();
    await edit.getByRole("button",{name:"保存信号设置"}).waitFor();
    for(const width of [320,390,1440]){
      await page.setViewportSize({width,height:900});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"Overflow at "+width);
    }
    await page.setViewportSize({width:390,height:844});
    await page.waitForFunction(()=>!document.querySelector("#content").classList.contains("screen-animated"));
    await page.screenshot({path:path.resolve("test-results/signals-mobile-light.png"),fullPage:true});
    await page.goto(base+"/#settings");await page.getByRole("button",{name:"夜间",exact:true}).click();
    await page.goto(base+"/#signals");await edit.getByRole("button",{name:"保存信号设置"}).waitFor();
    await page.waitForFunction(()=>!document.querySelector("#content").classList.contains("screen-animated"));
    await page.screenshot({path:path.resolve("test-results/signals-mobile-dark.png"),fullPage:true});
    page.once("dialog",dialog=>dialog.accept());
    await page.getByRole("button",{name:"删除此技术信号订阅"}).click();
    await page.waitForFunction(()=>!document.querySelector('[data-action="delete-technical"]'));
    assert.deepEqual(errors,[]);
    console.log("PASS: Fibonacci required anchors, local range feedback, inline 422 details, real API save, persistence, AI toggle, deletion, light/dark, 320/390/1440px, no JavaScript errors.");
  }catch(error){await page.screenshot({path:path.resolve("test-results/signals-failure.png"),fullPage:true});console.error(errors);throw error;}
  finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
