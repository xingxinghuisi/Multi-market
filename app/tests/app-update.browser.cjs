const {chromium}=require(process.env.PLAYWRIGHT_MODULE||"playwright");
const assert=require("node:assert/strict");
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{})});
  const base=process.env.RADAR_TEST_BASE_URL;
  try{
    for(const blockedStorage of [false,true]){
      const context=await browser.newContext();
      if(blockedStorage)await context.addInitScript(()=>Object.defineProperty(window,"sessionStorage",{get(){throw new Error("Storage disabled for regression");}}));
      const page=await context.newPage(),errors=[];let navigations=0;
      page.on("pageerror",error=>errors.push(String(error)));
      page.on("framenavigated",frame=>{if(frame===page.mainFrame())navigations++;});
      await page.goto(base+"/#login");
      await page.getByRole("heading",{name:"登录",exact:true}).waitFor();
      await page.evaluate(()=>navigator.serviceWorker.ready);
      await page.waitForTimeout(400);
      assert.equal(navigations,1,"First service worker installation reloaded an unchanged app");
      await page.route("**/api/client-version",route=>route.fulfill({json:{version:"2026.10.11.99"}}));
      const navigation=page.waitForEvent("framenavigated",{predicate:frame=>frame===page.mainFrame()});
      await page.evaluate(()=>window.dispatchEvent(new Event("online")));
      await navigation;
      await page.getByRole("heading",{name:"登录",exact:true}).waitFor();
      await page.getByText("更新暂未完成，已停止重复刷新；当前页面可继续使用。",{exact:true}).waitFor();
      for(let i=0;i<5;i++)await page.evaluate(()=>{
        window.dispatchEvent(new Event("online"));
        navigator.serviceWorker.dispatchEvent(new Event("controllerchange"));
      });
      await page.waitForTimeout(600);
      assert.equal(navigations,2,"Stale app / newer API produced a reload loop");
      await page.getByLabel("用户名",{exact:true}).fill("still_usable");
      assert.equal(await page.getByLabel("用户名",{exact:true}).inputValue(),"still_usable");
      assert.deepEqual(errors,[]);
      await context.close();
    }
    console.log("PWA_UPDATE_BROWSER_OK: initial install stable; stale shell/new API bounded with storage available or blocked; login remains usable");
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
