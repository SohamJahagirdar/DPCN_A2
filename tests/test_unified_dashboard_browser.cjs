/* Installed Chrome acceptance over an explicitly supplied staged unified file.
 * node tests/test_unified_dashboard_browser.cjs <index.html> <NEW external evidence dir>
 * No acquisition, remote pages, product-code mocks or package installation.
 */
'use strict';
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const {chromium}=require(process.env.IDEA_FLOW_PLAYWRIGHT||'playwright');
const input=path.resolve(process.argv[2]||''),out=path.resolve(process.argv[3]||''),repo=path.resolve(__dirname,'..');
if(!process.argv[2]||!process.argv[3]||out===repo||out.startsWith(repo+path.sep)||fs.existsSync(out))throw new Error('Explicit input and NEW external evidence directory required');
fs.mkdirSync(out,{recursive:true});
const bytes=fs.readFileSync(input),sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const report={started:new Date().toISOString(),input,sha256:sha(bytes),bytes:bytes.length,checks:[],pageErrors:[],consoleErrors:[],externalRequests:[],failedRequests:[],screenshots:[],downloads:[],performance:[]};
const save=()=>fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));
let browser,server;
const timeout=setTimeout(()=>{report.fatal='Browser deadline exceeded';save();process.exit(2);},600000);
function parseCSV(text){
 text=text.replace(/^\ufeff/,'');const rows=[];let row=[],cell='',quoted=false;
 for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
 else if(c===','&&!quoted){row.push(cell);cell='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);rows.push(row);row=[];cell='';}else cell+=c;}
 if(cell||row.length){row.push(cell);rows.push(row);}return rows;
}
async function main(){
 server=http.createServer((req,res)=>{if(req.url==='/favicon.ico'){res.writeHead(204);res.end();return;}if(!req.url.startsWith('/index.html')){res.writeHead(404);res.end();return;}res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});res.end(bytes);});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 browser=await chromium.launch({headless:true,executablePath:process.env.IDEA_FLOW_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run','--enable-precise-memory-info']});
 report.browser=browser.version();
 const context=await browser.newContext({viewport:{width:1600,height:1100},acceptDownloads:true,colorScheme:'light'});
 function observe(p){p.on('pageerror',e=>report.pageErrors.push(String(e.stack||e)));p.on('console',m=>{if(m.type()==='error')report.consoleErrors.push(m.text());});p.on('requestfailed',r=>report.failedRequests.push(r.url()));}
 await context.route('**/*',r=>{const u=r.request().url();if(u.startsWith(origin+'/')||u.startsWith('blob:')||u.startsWith('data:'))return r.continue();report.externalRequests.push(u);return r.abort();});
 const page=await context.newPage();observe(page);page.setDefaultTimeout(20000);
 async function check(name,fn){const started=Date.now();try{const details=await fn();report.checks.push({name,status:'passed',milliseconds:Date.now()-started,details});console.log('PASS',name);}catch(e){report.checks.push({name,status:'failed',milliseconds:Date.now()-started,error:String(e.stack||e)});console.log('FAIL',name,e.message);await page.screenshot({path:path.join(out,'failure-'+report.checks.length+'.png')}).catch(()=>{});}save();}
 async function shot(name,p=page){const file=name+'.png';await p.screenshot({path:path.join(out,file),fullPage:false});report.screenshots.push(file);}
 async function perf(label,p=page){report.performance.push(await p.evaluate(label=>({label,navigation:performance.getEntriesByType('navigation').map(n=>({duration:n.duration,domInteractive:n.domInteractive,domContentLoaded:n.domContentLoadedEventEnd,load:n.loadEventEnd,transferBytes:n.transferSize})),heap:performance.memory?{used:performance.memory.usedJSHeapSize,total:performance.memory.totalJSHeapSize,limit:performance.memory.jsHeapSizeLimit}:null}),label));}
 async function setHeader(inst,flag){await page.locator(`#instSeg [data-i="${inst}"]`).click();await page.locator(`#flagSeg [data-f="${flag}"]`).click();}
 async function tab(name){await page.locator('#nav').getByRole('button',{name,exact:true}).click();assert.equal(await page.locator('.tab.on').getAttribute('data-tab'),name);if(name==='Follow the Idea')await page.waitForFunction(()=>{const e=document.getElementById('if-compositionChart');return e.hidden||e.getAttribute('aria-busy')==='false';});}
 async function selectSeed(id){await page.locator('#if-pilotOnly').uncheck();for(const [sel,val] of [['field','All'],['year','All'],['coverageFilter','All']])await page.locator('#if-'+sel).selectOption(val);await page.locator('#if-search').fill(id);await page.locator('#if-seedRows [data-seed="'+id+'"]').click();await page.waitForFunction(()=>{const e=document.getElementById('if-compositionChart');return e.hidden||e.getAttribute('aria-busy')==='false';});}
 async function download(selector,file){const pending=page.waitForEvent('download');await page.locator(selector).click();const d=await pending;await d.saveAs(path.join(out,file));assert.equal(await d.failure(),null);const csv=parseCSV(fs.readFileSync(path.join(out,file),'utf8'));report.downloads.push({file,rows:csv.length-1,columns:csv[0].length});return csv;}
 const start=Date.now();await page.goto(origin+'/index.html#tab=Overview&inst=All&flag=in&theme=light',{waitUntil:'load'});report.initialLoadWallMs=Date.now()-start;await perf('initial desktop load');
 await check('single native application and vendor copies; unique DOM IDs',async()=>{
  assert.equal(await page.locator('#nav button').count(),12);assert.equal(await page.locator('iframe,.sidebar').count(),0);
  const duplicate=await page.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return ids.filter((v,i)=>ids.indexOf(v)!==i);});assert.deepEqual(duplicate,[]);
  assert.equal((bytes.toString().match(/\/\* https:\/\/cdn.jsdelivr.net\/npm\/plotly.js-dist-min@2.35.2\/plotly.min.js \*\//g)||[]).length,1);
  assert.equal((bytes.toString().match(/\/\* https:\/\/unpkg.com\/vis-network@9.1.9\/standalone\/umd\/vis-network.min.js \*\//g)||[]).length,1);
  assert.equal(await page.locator('script[src]').count(),0);return {tabs:12,duplicateIds:0,externalScripts:0};
 });
 const tabs=await page.locator('#nav button').allTextContents();
 for(const flag of ['in','out'])for(const inst of ['All','IISc','TIFR'])await check('all 12 tabs and exact explorer scope: '+inst+'/'+flag,async()=>{
  await setHeader(inst,flag);const rendered=[];
  for(const name of tabs){await tab(name);assert.ok((await page.locator('.tab.on').innerText()).length>20);rendered.push(name);}
  await tab('Follow the Idea');
  const observed=await page.evaluate(()=>{const d=unifiedIdeaFlow.data,s=state,rs=d.seeds.filter(r=>(s.inst==='All'||r.homes.includes(s.inst))&&(s.flag==='in'||r.authors_gt_12===false));return {expected:rs.length,actual:unifiedIdeaFlow.filtered().length,scope:d.scopes[s.flag][s.inst],selected:unifiedIdeaFlow.state.selected,eligible:rs.some(r=>r.original_id===unifiedIdeaFlow.state.selected)};});
  assert.equal(observed.actual,observed.expected);assert.equal(observed.scope.original_seeds,observed.expected);assert.ok(observed.eligible,JSON.stringify(observed));
  assert.ok(await page.locator('#if-seedRows tr').count()<=30);assert.ok((await page.locator('#if-tiles').innerText()).includes(observed.scope.distinct_direct_citers.toLocaleString('en-US')));
  const csv=await download('#if-downloadSeeds','seeds-'+inst+'-'+flag+'.csv');
  const expected=await page.evaluate(()=>{const columns=unifiedIdeaFlow.columns;return {columns,rows:unifiedIdeaFlow.filtered().map(r=>columns.map(k=>{const v=r[k];return v==null?'':Array.isArray(v)?v.join(';'):String(v);} ))};});assert.deepEqual(csv.shift(),expected.columns);assert.equal(csv.length,expected.rows.length);
  assert.deepEqual(csv,expected.rows);
  return {renderedTabs:rendered,scope:observed.scope,csvRows:csv.length};
 });
 await setHeader('All','in');await tab('Follow the Idea');
 await check('scope/theme rerenders do not accumulate control or resize listeners',async()=>{
  const cdp=await context.newCDPSession(page);
  async function counts(){const result={};for(const expr of ["document.getElementById('if-search')","document.getElementById('if-compositionWindow')","window"]){const obj=await cdp.send('Runtime.evaluate',{expression:expr});const listeners=await cdp.send('DOMDebugger.getEventListeners',{objectId:obj.result.objectId});result[expr]=listeners.listeners.filter(l=>expr!=='window'||l.type==='resize').length;await cdp.send('Runtime.releaseObject',{objectId:obj.result.objectId});}return result;}
  const before=await counts();for(const inst of ['TIFR','IISc','All'])for(const flag of ['out','in'])await setHeader(inst,flag);const after=await counts();assert.deepEqual(after,before);await cdp.detach();return {before,after};
 });
 await check('bounded pagination, pilot/search/field/year filters, raw sorting and selected detail',async()=>{
  const first=await page.locator('#if-seedRows tr').first().innerText();await page.locator('#if-next').click();assert.notEqual(await page.locator('#if-seedRows tr').first().innerText(),first);await page.locator('#if-previous').click();
  await page.locator('#if-pilotOnly').check();assert.equal(await page.evaluate(()=>unifiedIdeaFlow.filtered().length),24);
  const seed=await page.evaluate(()=>unifiedIdeaFlow.data.seeds.find(r=>r.pilot&&r.query_complete&&r.observed_citers>0&&r.age_window.status==='eligible'));
  await selectSeed(seed.original_id);await page.locator('#if-field').selectOption(seed.field_id);await page.locator('#if-year').selectOption(String(seed.year));assert.equal(await page.evaluate(()=>unifiedIdeaFlow.filtered().length),1);
  assert.ok((await page.locator('#if-seedDetail').innerText()).includes('n='+seed.known_field_citers.toLocaleString('en-US')+' known'));
  assert.equal(Object.values(seed.field_counts).reduce((a,n)=>a+n,0),seed.known_field_citers);
  assert.deepEqual(await page.locator('#if-compositionChart').evaluate(e=>e.data[0].x),Object.entries(seed.field_counts).sort((a,b)=>b[1]-a[1]).map(e=>e[1]));
  await page.locator('#if-compositionWindow').selectOption('age');assert.match(await page.locator('#if-composition').innerText(),/Equal-age/);await page.locator('#if-compositionWindow').selectOption('cutoff');
  const paths=await page.evaluate(()=>unifiedIdeaFlow.pathExport());const csv=await download('#if-downloadPaths','selected-paths.csv');assert.equal(csv.length-1,paths.length);assert.deepEqual(csv[0],await page.evaluate(()=>unifiedIdeaFlow.pathColumns));
  await shot('01-selected-direct-path');return {seed:seed.original_id,known:seed.known_field_citers,displayedPaths:paths.length};
 });
 await check('unknown fields, censored window, no-excerpt seed and empty exports remain explicit',async()=>{
  const ids=await page.evaluate(()=>({unknown:unifiedIdeaFlow.data.seeds.find(r=>r.canonical_id&&!r.field_id)?.original_id,censored:unifiedIdeaFlow.data.seeds.find(r=>r.age_window.status==='right_censored')?.original_id,noExcerpt:unifiedIdeaFlow.data.seeds.find(r=>r.canonical_id&&!unifiedIdeaFlow.data.paths[r.canonical_id])?.original_id}));
  await selectSeed(ids.unknown);assert.match(await page.locator('#if-seedDetail').innerText(),/unavailable|Unavailable/);
  await selectSeed(ids.censored);await page.locator('#if-compositionWindow').selectOption('age');assert.match(await page.locator('#if-composition').innerText(),/right_censored/);await page.locator('#if-compositionWindow').selectOption('cutoff');
  await selectSeed(ids.noExcerpt);assert.match(await page.locator('#if-pathScope').innerText(),/No path excerpt/);assert.equal(await page.locator('#if-downloadPaths').isDisabled(),true);
  await page.locator('#if-search').fill('NO_MATCH_6bd42');assert.equal(await page.evaluate(()=>unifiedIdeaFlow.state.selected),null);assert.match(await page.locator('#if-seedDetail').innerText(),/No selected seed/);
  const csv=await download('#if-downloadSeeds','empty-seeds.csv');assert.equal(csv.length,1);assert.equal(csv[0].length,27);
  await page.locator('#if-search').fill('');await page.locator('#if-sort').selectOption('share');
  const shares=await page.evaluate(()=>unifiedIdeaFlow.filtered().map(r=>r.cross_field_share));const known=shares.filter(v=>v!=null);assert.deepEqual(known,[...known].sort((a,b)=>b-a));assert.ok(shares.slice(known.length).every(v=>v==null));return ids;
 });
 for(const id of ['W4290949638','W2406197876'])await check('sampled G2 composition and both actual edge proofs: '+id,async()=>{
  await selectSeed(id);await page.locator('#if-compositionWindow').selectOption('g2');assert.match(await page.locator('#if-composition').innerText(),/not a global G2 estimate/);
  const data=await page.evaluate(()=>({paths:unifiedIdeaFlow.pathExport().filter(r=>r.generation===2),sample:unifiedIdeaFlow.data.g2_results.seeds.find(r=>r.seed===unifiedIdeaFlow.state.selected)}));
  assert.ok(data.paths.length>0);assert.ok(data.paths.every(p=>p.snapshot&&p.parent_snapshot&&p.cited&&p.citing));
  assert.match(await page.locator('#if-pathRows').innerText(),/sampled branch/);await shot('g2-'+id);await page.locator('#if-compositionWindow').selectOption('cutoff');return {id,displayedPaths:data.paths.length};
 });
 await check('story access/reviewer limits and flagged-seed removal clear incompatible selection',async()=>{
  await page.locator('#if-search').fill('');assert.equal(await page.locator('#if-reviewedCases .case').count(),3);
  for(const details of await page.locator('#if-reviewedCases details').all())await details.locator('summary').click();assert.match(await page.locator('#if-reviewedCases').innerText(),/Independent human review: no/);await shot('source-inspection-limits');
  const flagged=await page.evaluate(()=>unifiedIdeaFlow.data.seeds.find(r=>r.authors_gt_12).original_id);await selectSeed(flagged);await page.locator('#flagSeg [data-f="out"]').click();assert.equal(await page.evaluate(()=>unifiedIdeaFlow.filtered().length),0);assert.equal(await page.evaluate(()=>unifiedIdeaFlow.state.selected),null);
  await page.locator('#if-search').fill('');const cases=await page.evaluate(()=>unifiedIdeaFlow.data.reviewed_cases.filter(c=>unifiedIdeaFlow.data.seeds.some(r=>r.canonical_id===c.seed&&!r.authors_gt_12)).length);assert.equal(await page.locator('#if-reviewedCases .case').count(),cases);return {flagged,remainingStories:cases};
 });
 await check('tab/variant/institution URL survives reload and preserves unrelated parameters',async()=>{
  await setHeader('TIFR','out');await page.reload({waitUntil:'load'});assert.equal(await page.locator('.tab.on').getAttribute('data-tab'),'Follow the Idea');assert.equal(await page.evaluate(()=>state.inst),'TIFR');assert.equal(await page.evaluate(()=>state.flag),'out');
  const hash=new URL(page.url()).hash;assert.ok(hash.includes('inst=TIFR')&&hash.includes('flag=out'));return {hash};
 });
 await check('existing visual language, light/dark/system themes and chart recoloring',async()=>{
  await setHeader('All','in');await selectSeed('W4290949638');
  assert.equal(await page.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(249, 249, 247)');
  const light=await page.locator('#if-compositionChart').evaluate(e=>e._fullLayout.font.color);await shot('02-unified-light');
  await page.locator('#themeBtn').click();assert.equal(await page.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(13, 13, 13)');await page.waitForFunction(light=>document.querySelector('#if-compositionChart')._fullLayout.font.color!==light,light);const dark=await page.locator('#if-compositionChart').evaluate(e=>e._fullLayout.font.color);assert.notEqual(light,dark);await shot('03-unified-dark');
  await page.locator('#themeBtn').click();assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme||'system'),'system');await page.emulateMedia({colorScheme:'dark'});await page.waitForFunction(()=>getComputedStyle(document.body).backgroundColor==='rgb(13, 13, 13)');
  await page.emulateMedia({colorScheme:'light'});await page.waitForFunction(()=>getComputedStyle(document.body).backgroundColor==='rgb(249, 249, 247)');return {light,dark,system:true};
 });
 await check('mobile/tablet layout, offline file load and native tab controls',async()=>{
  for(const width of [768,390]){await page.setViewportSize({width,height:844});await tab('Follow the Idea');assert.ok(await page.locator('#if-seedRows tr').count()<=30);assert.ok(await page.locator('#nav').evaluate(e=>e.scrollWidth>=e.clientWidth));await shot('mobile-'+width);}
  const offline=await browser.newContext({offline:true,viewport:{width:390,height:844},colorScheme:'dark'});const p=await offline.newPage();observe(p);const start=Date.now();await p.goto('file:///'+input.replaceAll('\\','/')+'#tab=Follow+the+Idea&inst=TIFR&flag=out&theme=system',{waitUntil:'load'});assert.equal(await p.locator('.tab.on').getAttribute('data-tab'),'Follow the Idea');await p.waitForFunction(()=>window.unifiedIdeaFlow?.filtered().length>0);await perf('offline mobile load',p);report.offlineMobileWallMs=Date.now()-start;await shot('04-offline-mobile-dark',p);await offline.close();
 });
 await perf('after scope/tab/filter/theme matrix');
 await check('no runtime/console/network errors; exact tested bytes remain unchanged',async()=>{
  assert.deepEqual(report.pageErrors,[]);assert.deepEqual(report.consoleErrors,[]);assert.deepEqual(report.externalRequests,[]);assert.deepEqual(report.failedRequests,[]);assert.equal(sha(fs.readFileSync(input)),report.sha256);return {pageErrors:0,consoleErrors:0,externalRequests:0,failedRequests:0};
 });
 await context.close();
}
main().catch(e=>{report.fatal=String(e.stack||e);console.error(e);process.exitCode=1;}).finally(async()=>{
 if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));clearTimeout(timeout);report.finished=new Date().toISOString();report.passed=report.checks.filter(c=>c.status==='passed').length;report.failed=report.checks.filter(c=>c.status==='failed').length;save();console.log(JSON.stringify({passed:report.passed,failed:report.failed,fatal:report.fatal||null,out}));if(report.failed)process.exitCode=1;
});
