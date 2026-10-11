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
    const saving=page.waitForResponse(r=>r.url().endsWith("/api/subscriptions")&&r.request().method()==="PUT");
    await form.getByRole("button",{name:"添加技术信号订阅"}).click();
    assert.equal((await saving).status(),200);
    const edit=page.locator('[data-technical-form]').filter({has:page.locator('[name="asset_id"][type="hidden"]')});
    await edit.getByRole("button",{name:"保存信号设置"}).waitFor();
    assert.equal(await edit.locator('[name="timeframe"]').inputValue(),"4h");
    assert.equal(await edit.locator('[name="rsi_high"]').inputValue(),"75");
    assert.equal(await edit.locator('[name="ai_enabled"]').isChecked(),false);
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
    console.log("PASS: signal creation, settings persistence, AI toggle, deletion, light/dark, 320/390/1440px, no JavaScript errors.");
  }catch(error){await page.screenshot({path:path.resolve("test-results/signals-failure.png"),fullPage:true});console.error(errors);throw error;}
  finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
