const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const base=process.env.RADAR_TEST_BASE_URL;
  const output=path.resolve(__dirname,'../../test-results/smart-money');fs.mkdirSync(output,{recursive:true});
  try {
    for(const width of [390,1280]) {
      const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block',reducedMotion:'reduce'});
      const page=await context.newPage(), errors=[];
      page.on('pageerror',error=>errors.push(error.message));
      await page.goto(base+'/#register');
      await page.getByLabel('用户名',{exact:true}).fill('smart_'+width+'_'+Date.now());
      await page.getByLabel('密码',{exact:true}).fill('SyntheticBrowser2026');
      await page.getByRole('button',{name:'注册并进入',exact:true}).click();
      await page.getByRole('heading',{name:'市场，尽在掌握'}).waitFor();
      const before=(await(await page.request.get(base+'/__fixture__/smart-money')).json()).calls;
      await page.goto(base+'/#asset/1');
      const load=page.getByRole('button',{name:'查看聪明钱快照',exact:true});await load.waitFor();
      assert.equal((await(await page.request.get(base+'/__fixture__/smart-money')).json()).calls,before);
      await load.click();
      await page.getByText('源时间口径待核实',{exact:true}).waitFor();
      const card=page.locator('.smart-money-card');
      assert.match(await card.innerText(),/最近成功读取时间/);
      assert.match(await card.innerText(),/盈利巨鲸人数\s+0/);
      assert.match(await card.innerText(),/盈利巨鲸人数\s+未提供/);
      assert.match(await card.innerText(),/不用于实时提醒/);
      await page.request.post(base+'/__fixture__/smart-money-fail');
      await page.getByRole('button',{name:'刷新快照',exact:true}).click();
      await card.getByRole('alert').waitFor();
      assert.match(await card.innerText(),/当前服务器暂时无法访问/);
      assert.match(await card.innerText(),/总持仓名义价值/);
      assert.deepEqual(errors,[]);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await card.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'snapshot-'+width+'.png')});
      await context.close();
      console.log('PASS '+width+'px: authenticated opt-in snapshot, source-time warning, missing/zero fields and failed refresh preservation');
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
