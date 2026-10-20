/* Real installed Chrome, real Plotly/vis, actual input events and downloads.
 * No package install, external site, existing profile or product-code mocks.
 */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.IDEA_FLOW_PLAYWRIGHT||'playwright');
const input=path.resolve(process.argv[2]||''),run=path.resolve(process.argv[3]||''),repo=path.resolve(__dirname,'..');
if(!process.argv[2]||!process.argv[3]||run===repo||run.startsWith(repo+path.sep)||fs.existsSync(run))throw new Error('Explicit input and NEW external evidence dir required');
fs.mkdirSync(run,{recursive:true});for(const name of ['screenshots','downloads'])fs.mkdirSync(path.join(run,name));
const html=fs.readFileSync(input,'utf8');
const crypto=require('node:crypto'),sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const fixtures=JSON.parse(fs.readFileSync(path.join(path.dirname(input),'fixtures/manifest.json'),'utf8'));
assert.equal(fixtures.source_sha256,sha(fs.readFileSync(input)));
for(const [name,expected] of Object.entries(fixtures.labelled_fixtures))assert.equal(sha(fs.readFileSync(path.join(path.dirname(input),'fixtures',name))),expected);
const payload=Object.fromEntries(['DATA_ALL','DATA_NF'].map(name=>[name,JSON.parse(html.match(new RegExp('^const '+name+' = (.*);[^\\r\\n]*$','m'))[1])]));
const report={input,html_sha256:sha(fs.readFileSync(input)),started:new Date().toISOString(),mode:'real Chrome headless via existing Playwright',viewport:{width:1600,height:1100},checks:[],screenshots:[],downloads:[],console:[],pageErrors:[],failedRequests:[],responses:[],blockedExternalRequests:[]};
const fmt=x=>Number(x).toLocaleString('en-IN',{maximumFractionDigits:0,minimumFractionDigits:0});
const pct=x=>(100*x).toFixed(1)+'%';
let browser,context,page,origin,navigation=0;
const write=()=>fs.writeFileSync(path.join(run,'browser-report.json'),JSON.stringify(report,null,2));
const keepalive=setInterval(()=>{},1000);
const deadline=setTimeout(()=>{report.fatal='Overall browser verification timeout';write();process.exit(2);},540000);
const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1');
  if(url.pathname==='/favicon.ico'){res.writeHead(204);res.end();return;}
  const names={'/index.html':input,'/fixtures/missing-filtered-payload.html':path.join(path.dirname(input),'fixtures/missing-filtered-payload.html'),'/fixtures/missing-filtered-resilience.html':path.join(path.dirname(input),'fixtures/missing-filtered-resilience.html'),'/fixtures/synthetic-15-fragments.html':path.join(path.dirname(input),'fixtures/synthetic-15-fragments.html')};
  const file=names[url.pathname];
  if(!file){res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});fs.createReadStream(file).pipe(res);
});
async function shot(name,selector){
  const file='screenshots/'+name+'.png';
  if(selector)await page.locator(selector).screenshot({path:path.join(run,file)});
  else await page.screenshot({path:path.join(run,file),fullPage:true});
  report.screenshots.push({file,url:page.url()});write();return file;
}
async function check(name,kind,fn){
  const entry={name,kind,started:new Date().toISOString()};
  try{entry.details=await fn();entry.status='passed';console.log('PASS',name);}
  catch(error){entry.status='failed';entry.error=error.stack||String(error);console.log('FAIL',name,error.message);try{entry.screenshot=await shot('failure-'+name);}catch{}}
  entry.finished=new Date().toISOString();report.checks.push(entry);write();
}
async function open(flag='in',fixture=null){
  await page.goto(origin+(fixture?'/fixtures/'+fixture+'.html':'/index.html')+'?verification_navigation='+(++navigation)+'#tab=Network%20Resilience&inst=All&flag='+flag,{waitUntil:'load'});
  await page.locator('[data-tab="Network Resilience"].on').waitFor();
}
async function chartMouseClick(locator){
  await locator.evaluate(el=>el.scrollIntoView({block:'center',inline:'center'}));
  const box=await locator.boundingBox();assert.ok(box&&box.width>0&&box.height>0);
  await page.mouse.click(box.x+box.width/2,box.y+box.height/2);
}
async function settleCharts(){
  await page.waitForFunction(()=>document.querySelectorAll('#rsImpact .barlayer .point path').length>0 && document.querySelectorAll('#rsScatter .scatterlayer .point').length>0);
  await page.evaluate(()=>document.fonts.ready);
}
async function selectedRow(expected){
  assert.equal(await page.locator('#rsPerson').inputValue(),expected.person);
  const text=await page.locator('#rsDetail').innerText();
  assert.ok(text.includes(expected.person));
  assert.ok(text.includes(fmt(expected.lost_connected_pairs)+' ('+pct(expected.lost_pair_fraction)+')'));
  assert.ok(text.includes('/ '+fmt(expected.component_survivor_pairs_before)+' previously connected surviving pairs'));
  if(expected.local_pair_loss_fraction==null)assert.ok(text.includes('unavailable (no surviving pair)'));
  else assert.ok(text.includes(pct(expected.local_pair_loss_fraction)));
  await page.waitForFunction(sizes=>JSON.stringify(document.getElementById('rsFragments').data?.[0]?.y)===JSON.stringify(sizes),expected.fragment_sizes.slice(0,12));
  const actual=await page.evaluate(()=>({person:document.getElementById('rsPerson').value,fragments:document.getElementById('rsFragments').data[0].y,canvas:!!document.querySelector('#rsNet canvas'),hint:document.getElementById('rsFragmentHint').textContent}));
  assert.ok(actual.canvas || expected.original_component_size===1);
  return actual;
}
async function download(name,expected){
  const pending=page.waitForEvent('download');await page.locator('#rsDownload').click();
  const dl=await pending;const file='downloads/'+name+'--'+dl.suggestedFilename();
  await dl.saveAs(path.join(run,file));assert.equal(await dl.failure(),null);
  const item={file,suggestedFilename:dl.suggestedFilename(),url:page.url(),expected_ids:expected.map(r=>r.person),variant:await page.evaluate(()=>state.flag),institution:await page.evaluate(()=>state.inst),search:await page.locator('#rsSearch').inputValue(),role:await page.locator('#rsRole').inputValue(),bytes:fs.statSync(path.join(run,file)).size};
  report.downloads.push(item);write();return item;
}
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin='http://127.0.0.1:'+server.address().port;report.origin=origin;
  write();
  browser=await chromium.launch({executablePath:process.env.IDEA_FLOW_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run','--no-default-browser-check']});
  report.browser=browser.version();report.playwright=require('C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json').version;
  context=await browser.newContext({viewport:report.viewport,acceptDownloads:true,deviceScaleFactor:1,colorScheme:'light'});
  await context.route('**/*',route=>{const u=route.request().url();if(u.startsWith(origin+'/')||u.startsWith('blob:')||u.startsWith('data:'))return route.continue();report.blockedExternalRequests.push(u);return route.abort();});
  page=await context.newPage();page.setDefaultTimeout(15000);
  page.on('console',message=>report.console.push({type:message.type(),text:message.text(),url:page.url()}));
  page.on('pageerror',error=>report.pageErrors.push({message:error.message,stack:error.stack,url:page.url()}));
  page.on('requestfailed',request=>report.failedRequests.push({url:request.url(),failure:request.failure()}));
  page.on('response',response=>report.responses.push({url:response.url(),status:response.status()}));

  await check('initial-tab-load','real',async()=>{
    await page.goto(origin+'/index.html#tab=Overview&inst=All&flag=in',{waitUntil:'load'});
    await page.locator('#nav button[data-t="Network Resilience"]').click();await settleCharts();
    assert.ok(await page.locator('[data-tab="Network Resilience"]').isVisible());
    await shot('01-initial-resilience');return {title:await page.title(),navCount:await page.locator('#nav button').count()};
  });
  for(const flag of ['in','out']){
    const data=(flag==='in'?payload.DATA_ALL:payload.DATA_NF).resilience;
    await check(flag+'-summary-and-rendered-charts','real',async()=>{
      await open(flag);await settleCharts();
      const tiles=await page.locator('#rsTiles .tile').evaluateAll(els=>els.map(el=>({label:el.querySelector('.l').textContent,value:el.querySelector('.v').textContent,detail:el.querySelector('.d')?.textContent})));
      assert.equal(tiles[0].value,fmt(data.baseline.nodes)+' / '+fmt(data.baseline.edges));
      assert.equal(tiles[3].value,fmt(data.summary.articulation_researchers));
      assert.ok(tiles[3].detail.includes(fmt(data.summary.high_impact_articulations)+' high-impact'));
      assert.equal(tiles[5].value,pct(data.summary.max_lost_pair_fraction));
      assert.equal(await page.locator('#rsPerson option').count(),data.researchers.length);
      const drawn=await page.evaluate(()=>({bars:document.querySelectorAll('#rsImpact .barlayer .point path').length,points:document.querySelectorAll('#rsScatter .scatterlayer .point').length,fragmentBars:document.querySelectorAll('#rsFragments .barlayer .point path').length,canvas:[...document.querySelectorAll('#rsNet canvas')].map(c=>({width:c.width,height:c.height})),impactValues:document.getElementById('rsImpact').data[0].x,scatterValues:document.getElementById('rsScatter').data[0].y}));
      assert.equal(drawn.bars,Math.min(15,data.researchers.length));assert.equal(drawn.points,data.researchers.length);assert.ok(drawn.canvas[0]?.width>0&&drawn.canvas[0]?.height>0);
      assert.deepEqual(drawn.impactValues,data.researchers.slice(0,15).reverse().map(r=>r.lost_pair_fraction));
      assert.deepEqual(drawn.scatterValues,data.researchers.map(r=>r.lost_pair_fraction));
      await selectedRow(data.researchers[0]);await shot(flag==='in'?'02-all-papers':'03-excluded-papers');
      const saved=await download(flag+'-all-rows',data.researchers);
      return {tiles,drawn,download:saved.file,scope:await page.locator('#rsScope').innerText()};
    });
    await check(flag+'-researcher-selection-and-chart-clicks','real',async()=>{
      await open(flag);await settleCharts();
      const target=data.researchers[2];await page.locator('#rsPerson').selectOption(target.person);await selectedRow(target);
      await shot('04-'+flag+'-researcher-selection','#rsDetail');
      await page.locator('#rsGhost').check();assert.ok(await page.evaluate(()=>rsNet.body.data.nodes.get().some(n=>n.id===document.getElementById('rsPerson').value)));
      await shot('05-'+flag+'-fragments','.card:has(#rsFragments)');
      await shot('05-'+flag+'-network','.card:has(#rsNet)');
      await chartMouseClick(page.locator('#rsImpact .barlayer .point path').last());await selectedRow(data.researchers[0]);
      await page.locator('#rsPerson').selectOption(target.person);
      await chartMouseClick(page.locator('#rsScatter .scatterlayer .point').first());await selectedRow(data.researchers[0]);
      return {selected:target.person,barAndScatterSelected:data.researchers[0].person,ghostNode:true};
    });
  }
  await check('variant-switch-preserves-person-replaces-data','real',async()=>{
    await open('in');const nf=new Map(payload.DATA_NF.resilience.researchers.map(r=>[r.person,r]));
    const target=payload.DATA_ALL.resilience.researchers.find(r=>nf.has(r.person)&&r.lost_connected_pairs!==nf.get(r.person).lost_connected_pairs);
    await page.locator('#rsPerson').selectOption(target.person);await selectedRow(target);
    await page.locator('#flagSeg [data-f="out"]').click();const after=await selectedRow(nf.get(target.person));
    assert.equal(await page.evaluate(()=>DATA.resilience.baseline.nodes),payload.DATA_NF.resilience.baseline.nodes);
    await shot('06-switch-same-person');return {person:target.person,before:target.lost_pair_fraction,after:nf.get(target.person).lost_pair_fraction,view:after};
  });
  await check('hash-and-reload-follow-controls','real',async()=>{
    await open('in');await page.locator('#flagSeg [data-f="out"]').click();
    const beforeReload={url:page.url(),flag:await page.evaluate(()=>state.flag)};
    await page.reload({waitUntil:'load'});const afterReload={url:page.url(),flag:await page.evaluate(()=>state.flag)};
    report.hashObservation={beforeReload,afterReload};
    assert.equal(new URL(beforeReload.url).hash.includes('flag=out'),true,'URL does not reflect excluded variant');
    assert.equal(afterReload.flag,'out','Reload reverts variant because stale hash overrides saved selection');return report.hashObservation;
  });
  await check('search-role-institution-sort-and-download','real',async()=>{
    await open('out');const rows=payload.DATA_NF.resilience.researchers;
    await page.locator('#rsRole').selectOption('High-impact articulation point');
    const high=rows.filter(r=>r.is_high_impact_articulation);assert.equal(await page.locator('#rsTable tbody tr').count(),high.length);
    await shot('07-role-filter');await download('out-high-impact',high);
    await page.locator('#rsRole').selectOption('');await page.locator('#instSeg [data-i="TIFR"]').click();
    assert.equal(await page.locator('#rsPerson option').count(),rows.filter(r=>r.inst==='TIFR').length);
    assert.ok((await page.locator('#rsTiles').innerText()).includes(fmt(payload.DATA_NF.resilience.baseline.nodes)));
    await page.locator('#instSeg [data-i="All"]').click();
    await page.locator('#rsSearch').fill(rows[0].person);await selectedRow(rows[0]);assert.equal(await page.locator('#rsTable tbody tr').count(),1);
    await download('out-one-researcher',[rows[0]]);await shot('08-search-and-download');
    await page.locator('#rsSearch').fill('');
    const sorts=[];
    for(const key of ['degree','lost_pair_fraction','local_pair_loss_fraction','cross_community_fraction']){
      for(let i=0;i<2;i++){
        await page.locator('#rsTable th[data-k="'+key+'"]').click();
        const ids=await page.locator('#rsTable tbody tr td:first-child').allTextContents();
        const byId=new Map(rows.map(r=>[r.person,r]));const values=ids.map(id=>byId.get(id)[key]);
        const ascending=(await page.locator('#rsTable th[data-k="'+key+'"]').innerText()).includes('\u25b2');
        const numeric=values.filter(v=>v!=null);
        for(let j=1;j<numeric.length;j++)assert.ok(ascending?numeric[j]>=numeric[j-1]:numeric[j]<=numeric[j-1]);
        const absent=values.findIndex(v=>v==null);if(absent>=0)assert.ok(values.slice(absent).every(v=>v==null));
        sorts.push({key,ascending,rows:values.length});
      }
    }
    await page.locator('#rsTable th[data-k="lost_pair_fraction"]').scrollIntoViewIfNeeded();await shot('09-percentage-columns','#rsTable');
    const title=await page.locator('#rsTable th[data-k="local_pair_loss_fraction"]').getAttribute('title');assert.ok(title.includes('original component'));
    await page.locator('#rsSearch').fill('NO_RESEARCHER_MATCHES_THIS_STRING');
    assert.equal(await page.locator('#rsPerson option').count(),0);assert.ok((await page.locator('#rsDetail').innerText()).includes('No researchers match'));
    await page.waitForFunction(()=>document.querySelectorAll('#rsFragments .barlayer .point').length===0);
    assert.equal(await page.locator('#rsNet canvas').count(),0);await shot('10-empty-search');await download('out-empty',[]);
    return {roleRows:high.length,sorts,localHeaderTitle:title,emptyState:true};
  });
  await check('local-unavailable-and-small-component','real',async()=>{
    await open('in');const rows=payload.DATA_ALL.resilience.researchers;
    const small=rows.find(r=>r.original_component_size===3&&r.local_pair_loss_fraction===1);
    await page.locator('#rsPerson').selectOption(small.person);await selectedRow(small);await shot('11-small-component-local-loss','#rsDetail');
    const isolate=rows.find(r=>r.original_component_size===1);await page.locator('#rsPerson').selectOption(isolate.person);await selectedRow(isolate);
    await page.locator('#rsSearch').fill(isolate.person);await download('in-isolate',[isolate]);await shot('12-local-unavailable','#rsDetail');return {small:small.person,smallGlobal:small.lost_pair_fraction,smallLocal:small.local_pair_loss_fraction,isolate:isolate.person};
  });
  await check('other-tabs-after-resilience','real',async()=>{
    await open('out');const tabs=await page.locator('#nav button').allTextContents(),checked=[];
    for(const tab of tabs){
      await page.locator('#nav').getByRole('button',{name:tab,exact:true}).click();
      const active=await page.locator('.tab.on').getAttribute('data-tab');assert.equal(active,tab);
      assert.ok((await page.locator('.tab.on').innerText()).length>20);checked.push({tab,visible:true});
    }
    await page.locator('#nav button[data-t="Overview"]').click();await shot('13-overview-after-resilience');
    await page.locator('#nav button[data-t="Co-authorship network"]').click();await page.locator('#auNet canvas').waitFor();await shot('14-coauthorship-after-resilience');
    await page.locator('#nav button[data-t="Network Resilience"]').click();await settleCharts();return checked;
  });
  await check('fragment-omissions-in-real-browser','synthetic-labelled-fixture',async()=>{
    await open('in','synthetic-15-fragments');await page.locator('#rsPerson').selectOption('star0');
    await page.waitForFunction(()=>document.querySelectorAll('#rsFragments .barlayer .point path').length===12);
    const hint=await page.locator('#rsFragmentHint').innerText();assert.ok(hint.includes('12 of 15'));assert.ok(hint.includes('3 smaller fragments (3 survivors) omitted'));
    await shot('15-SYNTHETIC-15-fragments');return {hint,drawnBars:12,fixture:true};
  });
  for(const fixture of ['missing-filtered-payload','missing-filtered-resilience'])await check(fixture+'-clears-results','negative-payload-fixture',async()=>{
    await open(fixture==='missing-filtered-payload'?'out':'in',fixture);
    if(fixture==='missing-filtered-resilience')await page.locator('#flagSeg [data-f="out"]').click();
    assert.ok((await page.locator('#rsScope').innerText()).includes('unavailable for this paper variant'));
    assert.equal(await page.locator('[data-tab="Network Resilience"] .grid').isVisible(),false);
    assert.equal(await page.locator('#rsTiles').isVisible(),false);
    await shot('16-'+fixture);return {unavailable:true,oldResultsHidden:true};
  });
  await check('console-and-assets','real-and-labelled-fixtures',async()=>{
    assert.equal(sha(fs.readFileSync(input)),report.html_sha256);assert.deepEqual(report.pageErrors,[]);assert.deepEqual(report.failedRequests,[]);assert.deepEqual(report.blockedExternalRequests,[]);
    const bad=report.responses.filter(r=>r.status>=400);assert.deepEqual(bad,[]);
    const errors=report.console.filter(m=>m.type==='error');assert.deepEqual(errors,[]);
    return {pageErrors:0,failedRequests:0,failedHTTP:0,consoleErrors:0,externalRequests:0};
  });
})().catch(error=>{report.fatal=error.stack;console.error(error);process.exitCode=1;}).finally(async()=>{
  report.finished=new Date().toISOString();report.passed=report.checks.filter(c=>c.status==='passed').length;report.failed=report.checks.filter(c=>c.status==='failed').length;write();
  fs.writeFileSync(path.join(run,'browser-console.json'),JSON.stringify({console:report.console,pageErrors:report.pageErrors,failedRequests:report.failedRequests,responses:report.responses,blockedExternalRequests:report.blockedExternalRequests},null,2));
  if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));clearInterval(keepalive);clearTimeout(deadline);
  console.log(JSON.stringify({run,passed:report.passed,failed:report.failed,fatal:report.fatal||null}));if(report.failed||report.fatal)process.exitCode=1;
});
