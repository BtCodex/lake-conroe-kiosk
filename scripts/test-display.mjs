// Optional development checks. Production never imports this test fixture.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const base = process.env.DASHBOARD_TEST_URL || 'http://127.0.0.1:8080';
const executablePath = process.env.CHROMIUM_PATH || '/usr/bin/chromium';
const browser = await chromium.launch({executablePath, headless:true, args:process.env.CI || process.env.CODEX_CI ? ['--no-sandbox'] : []});
const root = fileURLToPath(new URL('../',import.meta.url));
const snapshot = await (await fetch(`${base}/api/dashboard`)).json();
const now = new Date().toISOString();
const success = data => ({data,status:'live',last_success_at:now,last_attempt_at:now,interval_seconds:300,error:null});
const fixture = {
  config:structuredClone(snapshot.config), generated_at:now,
  sources:{
    weather:success({source:'TEST FIXTURE ONLY',current:{temperature_f:86,apparent_temperature_f:91,relative_humidity_pct:68,wind_speed_mph:12,wind_direction_deg:157,pressure_hpa:1011,uv_index:6.5,weather_code:2,is_day:true,valid_at:now},hourly:Array.from({length:6},(_,i)=>({time:new Date(Date.now()+(i+1)*3600000).toISOString(),temperature_f:86-i,precipitation_probability_pct:i*10,weather_code:[1,2,3,61,80,95][i],is_day:true}))}),
    forecast:success({daily:Array.from({length:3},(_,i)=>({date:new Date(Date.now()+i*86400000).toISOString().slice(0,10),temperature_max_f:89-i,temperature_min_f:72-i,precipitation_probability_pct:20+i*10,weather_code:[1,61,95][i],sunrise:now,sunset:now}))}),
    lake:success({measurements:{elevation_ft:{value:200.98,datum:'NGVD29',source:'TEST FIXTURE',observed_at:now},water_temperature_f:{value:81.2,source:'TEST FIXTURE',observed_at:now},rainfall_24h_in:{value:.12,source:'TEST FIXTURE',observed_at:now},outflow_cfs:{value:1250,source:'TEST FIXTURE',observed_at:now},wind_speed_mph:{value:12,source:'TEST FIXTURE',observed_at:now},wind_direction_deg:{value:157,source:'TEST FIXTURE',observed_at:now}},conservation_pool:{value_ft:201,datum:'NGVD29'}}),
    alerts:success({alerts:[]}),camera:success({provider:'disabled',url:null,attribution:'TEST FIXTURE',status:'configured'})
  }
};

async function assertLayout(page,label) {
  const issues = await page.evaluate(()=>{
    const issues=[];
    if(document.documentElement.scrollWidth>innerWidth||document.documentElement.scrollHeight>innerHeight)issues.push('Document scrolls');
    const panels=[...document.querySelectorAll('.main-grid>.panel,.information>.panel,.footer')].filter(e=>!e.hidden);
    for(const e of panels){
      const r=e.getBoundingClientRect();
      if(r.bottom>innerHeight+1||r.right>innerWidth+1||r.left<0||r.top<0)issues.push(`${e.className}: outside viewport`);
      if(e.scrollHeight>e.clientHeight+2)issues.push(`${e.className}: vertical content overflow (${e.scrollHeight}/${e.clientHeight})`);
    }
    for(const e of document.querySelectorAll('.hour,.forecast-day,.weather-metrics>div,.lake-metric,.clock,.date')){
      if(e.scrollWidth>e.clientWidth+2)issues.push(`${e.className}: horizontal overflow (${e.scrollWidth}/${e.clientWidth})`);
    }
    const heading=document.querySelector('.weather-panel .panel-heading').getBoundingClientRect();
    const main=document.querySelector('.weather-main').getBoundingClientRect();
    if(main.top<heading.bottom-1)issues.push('Weather overlaps heading');
    return issues;
  });
  assert.deepEqual(issues,[],`${label}: ${issues.join(', ')}`);
}

try {
  await mkdir(`${root}docs`,{recursive:true});
  for(const [width,height] of [[1920,1080],[1280,720]]) {
    const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base,{waitUntil:'networkidle'});
    await page.locator('#weather-badge').filter({hasText:/UPDATED|UNAVAILABLE|STALE DATA/}).waitFor();
    // Capture the ACTUAL current-instance result, including unavailable sources.
    await page.locator('#camera-status[data-state="unavailable"],#camera-status[data-state="live"],#camera-status[data-state="image"],#camera-status[data-state="embedded"]').waitFor({timeout:25000}).catch(()=>{});
    await assertLayout(page,`actual ${width}×${height}`);
    await page.screenshot({path:`${root}docs/dashboard-${width}x${height}.png`});
    assert.deepEqual(errors,[],`Unexpected browser JS errors: ${errors}`);
    await page.close();

    // Isolated fixture-only context exercises populated panels; never saved as a live screenshot.
    const context=await browser.newContext({viewport:{width,height}});
    const testPage=await context.newPage();
    let current=structuredClone(fixture);
    await testPage.route('**/api/dashboard',route=>route.fulfill({json:current}));
    await testPage.goto(base,{waitUntil:'networkidle'});
    await testPage.locator('#temperature').filter({hasText:'86'}).waitFor();
    await assertLayout(testPage,`populated fixture ${width}×${height}`);
    assert.equal(await testPage.locator('.hour').count(),6);
    assert.equal(await testPage.locator('.forecast-day').count(),3);
    assert.equal(await testPage.locator('#alert-title').innerText(),'No active weather alerts');
    assert.notEqual(await testPage.locator('#camera-status').innerText(),'LIVE');
    const before=await testPage.locator('#clock').innerText();
    await testPage.waitForTimeout(1100);
    assert.notEqual(await testPage.locator('#clock').innerText(),before,'Clock updates each second');

    current.sources.alerts.status='stale';
    await testPage.evaluate(()=>window.dispatchEvent(new Event('online')));
    await testPage.locator('#alert-title').filter({hasText:'Weather alert status unavailable'}).waitFor();
    current.sources.alerts=success({alerts:[{id:'test',event:'Severe Thunderstorm Warning',severity:'Severe',headline:'TEST FIXTURE ONLY: Montgomery County',expires:new Date(Date.now()+3600000).toISOString()}]});
    await testPage.evaluate(()=>window.dispatchEvent(new Event('online')));
    await testPage.locator('#alert-title').filter({hasText:'Severe Thunderstorm Warning'}).waitFor();
    assert.equal(await testPage.locator('#alert-bar').getAttribute('data-severity'),'severe');
    await assertLayout(testPage,`warning fixture ${width}×${height}`);
    current.config.temperature_unit='celsius';
    await testPage.evaluate(()=>window.dispatchEvent(new Event('online')));
    await testPage.locator('#temperature').filter({hasText:'30'}).waitFor();
    assert.equal(await testPage.locator('#temperature-unit').innerText(),'°C');
    // A successful source fetch can still contain yesterday's cached forecast.
    // Match provider dates instead of relabeling array position zero as today.
    const localParts=new Intl.DateTimeFormat('en-US',{timeZone:current.config.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
    const part=type=>Number(localParts.find(p=>p.type===type).value);
    const yesterday=new Date(Date.UTC(part('year'),part('month')-1,part('day')-1)).toISOString().slice(0,10);
    current.sources.forecast.data.daily=[{...current.sources.forecast.data.daily[0],date:yesterday}];
    await testPage.evaluate(()=>window.dispatchEvent(new Event('online')));
    await testPage.locator('#today-high').filter({hasText:'--°'}).waitFor();
    assert.equal(await testPage.locator('#sunrise').innerText(),'--','Yesterday’s sunrise is not today’s');
    current.config.panels={weather:false,hourly:false,forecast:false,lake:false};
    await testPage.evaluate(()=>window.dispatchEvent(new Event('online')));
    await testPage.locator('.information').waitFor({state:'hidden'});
    assert.equal(await testPage.locator('.camera-panel').isVisible(),true);
    await context.close();
    console.log(`PASS ${width}×${height}: real screenshot, layout, fixtures, alerts, units, clock, midnight cache, panel settings`);
  }
} finally {await browser.close();}
