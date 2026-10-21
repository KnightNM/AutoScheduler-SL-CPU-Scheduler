// Optional development proof. Playwright is NOT a dashboard runtime dependency.
// Set PLAYWRIGHT_MODULE and CHROME if using an existing installation.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.CHROME?{executablePath:process.env.CHROME}:{}), args:['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[],external=[],requests=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error') errors.push(message.text());});
    await page.route('**/*',route=>{const url=route.request().url();requests.push(url);if(!url.startsWith('http://127.0.0.1:8000')&&!url.startsWith('data:')){external.push(url);return route.abort();}return route.continue();});
    await page.goto(process.env.DEMO_URL || 'http://127.0.0.1:8000');
    await page.getByRole('heading',{name:/One CPU/}).waitFor();
    await page.screenshot({path:'/tmp/autoscheduler-dashboard-overview.png',fullPage:true});
    await page.getByRole('button',{name:/02 Scheduling lab/}).click();
    await page.getByRole('heading',{name:'CPU execution timeline'}).waitFor();
    assert.equal(await page.locator('.final-metrics .metric').filter({hasText:'CPU utilization'}).locator('strong').textContent(),'100%');
    await page.getByRole('button',{name:'Step +1'}).click();
    assert.equal(await page.locator('.live-metrics .metric').first().locator('strong').innerText(),'1/ 21');
    await page.getByRole('button',{name:/Resume/}).click();
    const simulationRequests=requests.filter(url=>url.includes('/api/simulation')).length;
    await page.waitForTimeout(650);
    await page.getByRole('button',{name:/Pause/}).click();
    const frozen=await page.locator('.live-metrics .metric').first().innerText();
    await page.waitForTimeout(650);
    assert.equal(await page.locator('.live-metrics .metric').first().innerText(),frozen,'Pause must freeze tick');
    assert.equal(requests.filter(url=>url.includes('/api/simulation')).length,simulationRequests,'Playback must not re-run Python');
    await page.getByLabel('Playback speed').selectOption('4');
    await page.getByRole('button',{name:/Reset/}).click();
    assert.match(await page.locator('.live-metrics .metric').first().innerText(),/\n0/);
    await page.getByLabel('Demo workload').selectOption('mixed_io');
    await page.getByRole('heading',{name:'CPU execution timeline'}).waitFor();
    await page.getByRole('button',{name:'Step +1'}).click();
    await page.screenshot({path:'/tmp/autoscheduler-dashboard-simulation.png',fullPage:true});
    for(const workload of ['short_jobs','mixed_io','bursty']){
      await page.getByLabel('Demo workload').selectOption(workload);
      await page.getByRole('heading',{name:'CPU execution timeline'}).waitFor();
      for(const algorithm of ['FCFS','SJF','SRTF','Round Robin','Priority','Priority RR','MLFQ','Tuned MLFQ']){
        await page.getByLabel('Scheduling algorithm').selectOption(algorithm);
        await page.getByRole('heading',{name:'CPU execution timeline'}).waitFor();
        assert.equal(await page.locator('tbody tr').count(),workload==='bursty'?8:6);
      }
    }
    const max=await page.locator('.live-metrics .metric').first().locator('small').innerText();
    const total=Number(max.replace('/','').trim());
    for(let i=0;i<total;i++) await page.getByRole('button',{name:'Step +1'}).click();
    assert.equal(await page.getByRole('button',{name:'Step +1'}).isDisabled(),true);
    assert.match(await page.locator('.live-metrics .metric').nth(2).innerText(),/8/);
    await page.getByRole('button',{name:/03 ML intelligence/}).click();
    await page.getByRole('heading',{name:'Verified Dynamic ML scheduling metrics'}).waitFor();
    await page.locator('summary').filter({hasText:'Historical Experiments'}).click();
    assert.match(await page.locator('body').innerText(),/76.8%/);
    assert.match(await page.locator('body').innerText(),/73.07%/);
    for(const option of await page.getByLabel('Saved evaluation cohort').locator('option').evaluateAll(options=>options.map(o=>o.value))) {
      await page.getByLabel('Saved evaluation cohort').selectOption(option);
      await page.getByText(option,{exact:true}).waitFor();
    }
    await page.screenshot({path:'/tmp/autoscheduler-dashboard-intelligence.png',fullPage:true});
    await page.getByRole('button',{name:/04 Research & review/}).click();
    await page.locator('.faculty summary').filter({hasText:"Why wasn't v6 promoted?"}).click();
    assert.equal(await page.locator('.faculty details[open]').count(),1);
    await page.screenshot({path:'/tmp/autoscheduler-dashboard-review.png',fullPage:true});
    for(const width of [1440,1024,768,320]){
      await page.setViewportSize({width,height:900});
      for(const label of [/Overview/,/Scheduling lab/,/ML intelligence/,/Research & review/]){
        await page.getByRole('button',{name:label}).click();
        await page.waitForTimeout(120);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`Body overflows at ${width}`);
      }
    }
    assert.deepEqual(errors,[],'Browser console/page errors');
    assert.deepEqual(external,[],'Demo must not require external requests');
    console.log(JSON.stringify({status:'PASS',workloadAlgorithmPairs:24,pages:4,viewports:[1440,1024,768,320],playback:'start/pause/resume/step/reset/completion',consoleErrors:errors,externalRequests:external},null,2));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
