/* Real installed browser acceptance. No package installation or remote pages.
 * node tests/test_idea_flow_browser.cjs <external index.html> <new evidence dir>
 * IDEA_FLOW_PLAYWRIGHT and IDEA_FLOW_CHROME select existing local runtimes.
 */
'use strict';
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const htmlPath=path.resolve(process.argv[2]||''),out=path.resolve(process.argv[3]||'');
if(!process.argv[2]||!process.argv[3])throw new Error('Explicit HTML and new external evidence paths required');
const repo=path.resolve(__dirname,'..');
if(out===repo||out.startsWith(repo+path.sep))throw new Error('Evidence must be outside the repository');
if(fs.existsSync(out)&&fs.readdirSync(out).length)throw new Error('Preserving existing evidence directory');
fs.mkdirSync(out,{recursive:true});
const {chromium}=require(process.env.IDEA_FLOW_PLAYWRIGHT||'playwright');
const html=fs.readFileSync(htmlPath,'utf8');
const report={started:new Date().toISOString(),mode:'real browser; standalone explorer; no remote page requests',checks:[],pageErrors:[],consoleErrors:[],blockedExternal:[],downloads:[]};
const save=()=>fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));
const keepalive=setInterval(()=>{},1000);
const deadline=setTimeout(()=>{report.timeout=true;save();process.exit(2);},240000);
const server=http.createServer((req,res)=>{
 if(req.url==='/favicon.ico'){res.writeHead(204);res.end();return;}
 if(req.url!=='/index.html'){res.writeHead(404);res.end();return;}
 res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});res.end(html);
});
function parseCSV(text){
 text=text.replace(/^\ufeff/,'');const rows=[];let row=[],cell='',quoted=false;
 for(let i=0;i<text.length;i++){
  const c=text[i];
  if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
  else if(c===','&&!quoted){row.push(cell);cell='';}
  else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);rows.push(row);row=[];cell='';}
  else cell+=c;
 }
 if(cell||row.length){row.push(cell);rows.push(row);}return rows;
}
async function main(){
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,...(process.env.IDEA_FLOW_CHROME?{executablePath:process.env.IDEA_FLOW_CHROME}:{}),args:['--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run']});
 report.browser=browser.version();
 try{
  const context=await browser.newContext({viewport:{width:1600,height:1100},acceptDownloads:true});
  await context.route('**/*',route=>{
   if(route.request().url().startsWith(origin+'/'))return route.continue();
   report.blockedExternal.push(route.request().url());return route.abort();
  });
  const page=await context.newPage();
  page.on('pageerror',e=>report.pageErrors.push(String(e)));
  page.on('console',m=>{if(m.type()==='error')report.consoleErrors.push(m.text());});
  async function check(name,fn){
   try{const details=await fn();report.checks.push({name,status:'passed',details});console.log('PASS',name);}
   catch(e){report.checks.push({name,status:'failed',error:String(e.stack||e)});console.log('FAIL',name,e.message);}
   save();
  }
  await page.goto(origin+'/index.html',{waitUntil:'load'});
  await page.waitForFunction(()=>window.ideaFlow?.data.seeds.length>0);
  const data=await page.evaluate(()=>({seeds:ideaFlow.data.seeds,summary:ideaFlow.data.summary}));
  await check('Real payload renders with bounded table and explicit direction',async()=>{
   assert.match(await page.locator('h1').innerText(),/Where does research/);
   assert.ok(await page.locator('#seedRows tr').count()<=30);
   assert.match(await page.locator('#paths').innerText(),/is cited by/);
   assert.equal(await page.evaluate(()=>ideaFlow.data.seeds.length),data.seeds.length);
   await page.screenshot({path:path.join(out,'01-overview.png'),fullPage:false});
   return {originalSeedRows:data.seeds.length,renderedRows:await page.locator('#seedRows tr').count()};
  });
  await check('Pilot filter retains actual deterministic cohort',async()=>{
   await page.locator('#pilotOnly').check();
   assert.equal(await page.evaluate(()=>ideaFlow.filtered().length),data.seeds.filter(r=>r.pilot).length);
   assert.equal(data.seeds.filter(r=>r.pilot).length,24);
  });
  await check('Institution and search controls act on original work rows',async()=>{
   await page.locator('#institution').selectOption('TIFR');
   const expected=data.seeds.filter(r=>r.pilot&&r.homes.includes('TIFR'));
   assert.equal(await page.evaluate(()=>ideaFlow.filtered().length),expected.length);
   await page.locator('#search').fill(expected[0].original_id);
   assert.ok((await page.locator('#seedRows').innerText()).includes(expected[0].original_id));
   await page.locator('#search').fill('');await page.locator('#institution').selectOption('All');
  });
  await check('Actual CSV download matches selected scope and unrounded values',async()=>{
   const expected=data.seeds.filter(r=>r.pilot).sort((a,b)=>a.original_id.localeCompare(b.original_id));
   const pending=page.waitForEvent('download');await page.locator('#downloadSeeds').click();
   const dl=await pending,file=path.join(out,'pilot-seeds.csv');await dl.saveAs(file);
   const csv=parseCSV(fs.readFileSync(file,'utf8')),headers=csv.shift();
   assert.deepEqual(headers,await page.evaluate(()=>ideaFlow.columns));assert.equal(csv.length,expected.length);
   for(let i=0;i<csv.length;i++){
    assert.equal(csv[i].length,headers.length);
    for(let j=0;j<headers.length;j++){
     const v=expected[i][headers[j]];
     assert.equal(csv[i][j],v==null?'':Array.isArray(v)?v.join(';'):String(v),`row ${i}, ${headers[j]}`);
    }
   }
   report.downloads.push({file:path.basename(file),rows:csv.length,columns:headers.length});
  });
  await check('Selected seed composition and known-field denominator agree',async()=>{
   const s=data.seeds.find(r=>r.pilot&&r.query_complete&&r.observed_citers>0);
   if(!s)throw new Error('No acquired nonempty pilot seed available');
   await page.locator(`[data-seed="${s.original_id}"]`).click();
   const text=await page.locator('#seedDetail').innerText();
   assert.ok(text.includes(s.title));assert.ok(text.includes('n='+s.known_field_citers+' known'));
   assert.equal(Object.values(s.field_counts).reduce((a,n)=>a+n,0),s.known_field_citers);
   assert.equal(s.known_field_citers+s.unknown_field_citers,s.observed_citers);
   if(s.cross_field_share!=null)assert.equal(s.cross_field_share,s.cross_field_citers/s.known_field_citers);
   assert.ok(await page.locator('.bar-fill').count()>0);
   await page.locator('#paths').screenshot({path:path.join(out,'02-selected-path.png')});
  });
  await check('Displayed paths expose bibliographic evidence and excerpt limits',async()=>{
   assert.match(await page.locator('#pathScope').innerText(),/direct links shown/);
   const expected=await page.evaluate(()=>ideaFlow.pathExport());
   assert.ok(expected.length>0);
   assert.ok(expected.every(r=>r.generation===1||r.generation===2));
   const pending=page.waitForEvent('download');await page.locator('#downloadPaths').click();
   const dl=await pending,file=path.join(out,'path-excerpt.csv');await dl.saveAs(file);
   const csv=parseCSV(fs.readFileSync(file,'utf8'));assert.equal(csv.length-1,expected.length);
   assert.deepEqual(csv[0],await page.evaluate(()=>ideaFlow.pathColumns));
   report.downloads.push({file:path.basename(file),rows:expected.length});
  });
  await check('Age-window and sampled-G2 composition are labelled separately',async()=>{
   await page.locator('#compositionWindow').selectOption('age');
   assert.match(await page.locator('#composition').innerText(),/Equal-age|No classified/);
   await page.locator('#compositionWindow').selectOption('g2');
   assert.match(await page.locator('#composition').innerText(),/sampled|G2|global G2/);
   await page.locator('#compositionWindow').selectOption('cutoff');
  });
  await check('Acquired sampled paths retain both edge proofs or explicit unavailable state',async()=>{
   const sample=await page.evaluate(()=>ideaFlow.data.g2_results.seeds.find(s=>s.observed_new_g2_distinct>0));
   if(!sample)return {scope:'No acquired new G2; unavailable state tested above'};
   await page.evaluate(seed=>{
    ideaFlow.state.selected=ideaFlow.data.seeds.find(r=>r.canonical_id===seed).original_id;ideaFlow.renderDetail();
   },sample.seed);
   const paths=await page.evaluate(()=>ideaFlow.pathExport().filter(r=>r.generation===2));
   assert.ok(paths.length>0);assert.ok(paths.every(p=>p.snapshot&&p.parent_snapshot&&p.cited&&p.citing));
   assert.match(await page.locator('#pathRows').innerText(),/sampled branch/);
   await page.locator('#compositionWindow').selectOption('g2');
   assert.match(await page.locator('#composition').innerText(),/not a global G2 estimate/);
   await page.locator('#compositionWindow').selectOption('cutoff');
   return {seed:sample.seed,displayedTwoEdgePaths:paths.length};
  });
  await check('Source-inspected stories expose identities and reviewer limits',async()=>{
   const cases=await page.evaluate(()=>ideaFlow.data.reviewed_cases||[]);
   assert.equal(await page.locator('#reviewedCases .case').count(),cases.length);
   for(let i=0;i<cases.length;i++){
    const card=page.locator('#reviewedCases .case').nth(i);
    assert.ok((await card.innerText()).includes(cases[i].seed));
    assert.ok((await card.innerText()).includes(cases[i].citing));
    await card.locator('summary').click();
    assert.ok((await card.innerText()).includes('Independent human review: '+(cases[i].independent_human_review?'yes':'no')));
    assert.ok((await card.innerText()).includes(cases[i].api_edge_evidence.page));
   }
   return {sourceInspections:cases.length,independentHumanReviews:cases.filter(c=>c.independent_human_review).length};
  });
  await check('Empty search keeps complete CSV schema',async()=>{
   await page.locator('#search').fill('NO_MATCH_6b462089');
   assert.match(await page.locator('#seedRows').innerText(),/No papers match/);
   const pending=page.waitForEvent('download');await page.locator('#downloadSeeds').click();
   const dl=await pending,file=path.join(out,'empty-seeds.csv');await dl.saveAs(file);
   const csv=parseCSV(fs.readFileSync(file,'utf8'));assert.equal(csv.length,1);assert.deepEqual(csv[0],await page.evaluate(()=>ideaFlow.columns));
   await page.locator('#search').fill('');
  });
  await check('Numeric sorting keeps unknown ratios last',async()=>{
   await page.locator('#sort').selectOption('share');
   const shares=await page.evaluate(()=>ideaFlow.filtered().map(r=>r.cross_field_share));
   const known=shares.filter(x=>x!=null);assert.deepEqual(known,[...known].sort((a,b)=>b-a));
   const firstUnknown=shares.indexOf(null);if(firstUnknown>=0)assert.ok(shares.slice(firstUnknown).every(x=>x==null));
  });
  await check('Synthetic negative state: partial and unknown remain explicit',async()=>{
   await page.evaluate(()=>{
    const r=ideaFlow.data.seeds[0];Object.assign(r,{query_status:'partial',query_complete:false,observed_citers:3,known_field_citers:0,unknown_field_citers:3,cross_field_share:null,field_counts:{}});
    ideaFlow.state.selected=r.original_id;ideaFlow.renderDetail();
   });
   assert.match(await page.locator('#seedDetail').innerText(),/Partial observation/);
   assert.match(await page.locator('#composition').innerText(),/does not establish/);
   await page.reload();await page.waitForFunction(()=>window.ideaFlow?.data.seeds.length>0);
  });
  await check('Offline self-contained load and mobile layout',async()=>{
   const offline=await browser.newContext({offline:true,viewport:{width:390,height:844}});
   const p=await offline.newPage();await p.goto('file:///'+htmlPath.replaceAll('\\','/'),{waitUntil:'load'});
   assert.match(await p.locator('h1').innerText(),/research/);
   await p.screenshot({path:path.join(out,'03-mobile-offline.png'),fullPage:false});await offline.close();
  });
  await check('No runtime errors or external page requests',async()=>{
   assert.deepEqual(report.pageErrors,[]);assert.deepEqual(report.consoleErrors,[]);assert.deepEqual(report.blockedExternal,[]);
  });
 }finally{await browser.close();server.close();clearInterval(keepalive);clearTimeout(deadline);}
 report.finished=new Date().toISOString();report.passed=report.checks.filter(x=>x.status==='passed').length;report.failed=report.checks.length-report.passed;save();
 console.log(JSON.stringify({passed:report.passed,failed:report.failed,evidence:out}));if(report.failed)process.exitCode=1;
}
main().catch(e=>{report.fatal=String(e.stack||e);save();console.error(report.fatal);server.close();clearInterval(keepalive);clearTimeout(deadline);process.exitCode=1;});
