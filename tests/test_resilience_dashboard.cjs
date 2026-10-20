/* No browser, npm packages or network. Execute the actual template controller
 * with DOM/chart adapters and real committed data enriched by the new analysis.
 * DPCN_TEST_PYTHON may select an existing Python interpreter.
 */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const generated = process.env.DPCN_TEST_HTML;
const template = fs.readFileSync(generated || path.join(root, 'pipeline/dashboard_template.html'), 'utf8');
const python = process.env.DPCN_TEST_PYTHON || 'python';
const payloads = generated ? Object.fromEntries(['DATA_ALL','DATA_NF'].map(name=>
  [name,JSON.parse(template.match(new RegExp('^const '+name+' = (.*);[^\\r\\n]*$', 'm'))[1])])) : JSON.parse(execFileSync(python, ['-B', '-c',
  "import json,sys;sys.path.insert(0,'tests');from test_resilience_snapshot import snapshot_result;out={};\nfor name in ['DATA_ALL','DATA_NF']:\n r,p,_=snapshot_result(name);p['resilience']=r;out[name]=p\nprint(json.dumps(out,ensure_ascii=True))"],
  {cwd:root,encoding:'utf8',maxBuffer:30*1024*1024,env:{...process.env,PYTHONIOENCODING:'utf-8'}}));

function dashboard(withFilteredData=true, hasFilteredPayload=true, resilience=null, hash='#tab=Network%20Resilience') {
  const elements = new Map(), networks = [], blobs = [];
  class Element {
    constructor(id) { this.id=id;this.value='';this.checked=false;this.textContent='';this.hidden=false;this.listeners={};this.children=[];this.classList={toggle(){}};this._html=''; }
    set innerHTML(value) {
      this._html=value;
      if(value.startsWith('<table>')) this.children=[...value.matchAll(/<th[^>]*data-k="([^"]+)"/g)].map(m=>{const th=new Element('header');th.dataset={k:m[1]};return th;});
      if(['rsPerson','rsRole'].includes(this.id)) {
        this.options=[...value.matchAll(/<option(?: value="([^"]*)")?>(.*?)<\/option>/g)].map(m=>m[1]??m[2]);
        this._value=this.options[0]||'';
      }
    }
    get innerHTML(){return this._html;}
    set value(v){this._value=v;}
    get value(){return this._value;}
    querySelectorAll(){return this.children;}
    on(name,fn){this.listeners[name]=fn;}
    removeAllListeners(name){delete this.listeners[name];}
    click(){this.clicked=true;}
  }
  const el=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
  const section=el('resilience-section');section.children=[new Element('grid'),new Element('tiles')];
  const document={getElementById:el,querySelector:()=>section,querySelectorAll:()=>[],createElement:()=>new Element('download'),documentElement:{dataset:{}}};
  const nf=hasFilteredPayload?structuredClone(payloads.DATA_NF):null;
  if(nf && !withFilteredData)delete nf.resilience;
  const all=structuredClone(payloads.DATA_ALL);
  if(resilience)all.resilience=resilience;
  // This adapter exercises legacy/resilience renderers. The native explorer's
  // actual DOM/controller is exercised separately, including in real Chrome.
  const script=template.match(/<script>\s*((?:const IDEA_DATA|const DATA_ALL)[\s\S]*?)<\/script>/)[1]
    .replace(/^const IDEA_DATA =.*$/m,'const IDEA_DATA = null;')
    .replace('/*__DATA__*/null',JSON.stringify(payloads.DATA_ALL))
    .replace('/*__DATA_NF__*/null',JSON.stringify(nf)).replace('/*__COMPARE__*/null','[]')
    .replace(/^const DATA_ALL =.*$/m,()=> 'const DATA_ALL = '+JSON.stringify(all)+';')
    .replace(/^const DATA_NF =.*$/m,()=> 'const DATA_NF = '+JSON.stringify(nf)+';');
  const location={hash};
  const context=vm.createContext({document,console,URLSearchParams,Blob,
    location,history:{replaceState:(_state,_title,url)=>{location.hash=url.slice(url.indexOf('#'));}},localStorage:{getItem:()=>null,setItem(){}},
    getComputedStyle:()=>({getPropertyValue:()=> '#335577'}),matchMedia:()=>({matches:false}),
    window:{scrollTo(){}},setTimeout:fn=>fn(),URL:{createObjectURL:b=>{blobs.push(b);return 'blob:test';},revokeObjectURL(){}},
    Plotly:{react:(id,traces,layout)=>{el(id).plot={traces,layout};}},
    vis:{Network:class {
      constructor(element,data,options){this.data=data;this.options=options;networks.push(this);}
      destroy(){this.destroyed=true;}
      once(){}
      setOptions(){}
    }}});
  new vm.Script(script,{filename:'dashboard_template.html'}).runInContext(context);
  return {context,el,section,networks,blobs,run:code=>vm.runInContext(code,context)};
}

test('actual template registers resilience and renders real baseline + all researchers',()=>{
  const d=dashboard();
  assert.equal(d.run('TABS.includes("Network Resilience")'),true);
  assert.match(d.el('rsScope').textContent,/combined IISc–TIFR/);
  assert.equal(d.el('rsPerson').options.length,payloads.DATA_ALL.resilience.baseline.nodes);
  assert.match(d.el('rsTiles').innerHTML,/High-impact|high-impact/);
  assert.match(d.el('rsTable').innerHTML,/Pairs disconnected/);
  assert.match(d.el('rsDetail').innerHTML,/lose connectivity/);
  assert.ok(d.networks.at(-1).data.nodes.length<=60);
  assert.ok(d.el('rsImpact').plot.traces[0].x.length<=15);
});

test('institution filter leaves global measures labeled and filters full researcher list',()=>{
  const d=dashboard();d.run('state.inst="TIFR";render();');
  const expected=payloads.DATA_ALL.resilience.researchers.filter(r=>r.inst==='TIFR');
  assert.equal(d.el('rsPerson').options.length,expected.length);
  assert.match(d.el('rsScope').textContent,/researcher-row filter only/);
  assert.match(d.el('rsTiles').innerHTML,new RegExp(String(payloads.DATA_ALL.resilience.baseline.nodes)));
  const shown=d.el('rsScatter').plot.traces[0].customdata;
  assert.ok(shown.every(id=>expected.some(r=>r.person===id)));
});

test('flag switch uses filtered results including its own graph and thresholds',()=>{
  const d=dashboard();d.run('state.flag="out";render();');
  assert.equal(d.el('rsPerson').options.length,payloads.DATA_NF.resilience.baseline.nodes);
  assert.match(d.el('rsScope').textContent,/at most 12 authors/);
  assert.match(d.el('rsDetail').innerHTML,new RegExp(String(payloads.DATA_NF.resilience.baseline.nodes)));
  assert.equal(d.run('DATA.resilience.baseline.edges'),payloads.DATA_NF.resilience.baseline.edges);
});

test('selected removal, original-link toggle and chart clicks preserve identity',()=>{
  const d=dashboard(), person=payloads.DATA_ALL.resilience.researchers[0].person;
  assert.deepEqual(Array.from(d.el('rsFragments').plot.traces[0].y),payloads.DATA_ALL.resilience.researchers[0].fragment_sizes.slice(0,12));
  const live=d.networks.at(-1);
  assert.ok(live.data.nodes.every(n=>n.id!==person));
  d.el('rsGhost').checked=true;d.el('rsGhost').onchange();
  assert.ok(d.networks.at(-1).data.nodes.some(n=>n.id===person));
  assert.ok(d.networks.at(-1).data.edges.some(e=>e.dashes));
  assert.ok(d.networks.at(-1).data.nodes.length<=61);
  const target=payloads.DATA_ALL.resilience.researchers[2].person;
  d.el('rsScatter').listeners.plotly_click({points:[{customdata:target}]});
  assert.equal(d.el('rsPerson').value,target);
  assert.ok(d.el('rsDetail').innerHTML.includes(target));
  assert.ok(live.destroyed);
  const selected=payloads.DATA_ALL.resilience.researchers.find(r=>r.person===target);
  assert.deepEqual(Array.from(d.el('rsFragments').plot.traces[0].y),selected.fragment_sizes.slice(0,12));
});

test('search, role filters, empty state and CSV download work',async()=>{
  const d=dashboard();
  d.el('rsRole').value='High-impact articulation point';d.el('rsRole').onchange();
  const critical=payloads.DATA_ALL.resilience.researchers.filter(r=>r.is_high_impact_articulation);
  assert.equal(d.el('rsPerson').options.length,critical.length);
  d.el('rsDownload').onclick();
  const csv=await d.blobs.at(-1).text();assert.match(csv,/person,name,inst/);assert.ok(csv.includes(critical[0].person));
  d.el('rsSearch').value='no researcher has this name';d.el('rsSearch').oninput();
  assert.equal(d.el('rsPerson').options.length,0);
  assert.match(d.el('rsTable').innerHTML,/No data available/);
  assert.match(d.el('rsDetail').textContent,/No researchers match/);
  assert.equal(d.el('rsFragments').plot.traces.length,0);
});

test('missing variant payload clears results instead of reusing the all-paper graph',()=>{
  const d=dashboard(false);d.run('state.flag="out";render();');
  assert.match(d.el('rsScope').textContent,/unavailable for this paper variant/);
  assert.ok(d.section.children.every(el=>el.hidden));
  assert.ok(d.networks.at(-1).destroyed);
});

test('absent filtered payload never labels all-paper results as without flagged',()=>{
  const d=dashboard(true,false);d.run('state.flag="out";render();');
  assert.match(d.el('rsScope').textContent,/unavailable for this paper variant/);
  assert.ok(d.section.children.every(el=>el.hidden));
  assert.ok(d.networks.at(-1).destroyed);
});

// Shared checks also run against generated HTML via DPCN_TEST_HTML.

test('all embedded generated scripts parse and no remote script assets remain',()=>{
  const scripts=[...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
  assert.equal(scripts.length,generated?3:1);
  for(const script of scripts)new vm.Script(script);
  if(generated)assert.equal(/<script\s+src=/.test(template),false);
});

test('generated table column sorting invokes the actual table handler',()=>{
  const d=dashboard(), head=()=>d.el('rsTable').children.find(e=>e.dataset.k==='degree');
  const first=()=>d.el('rsTable').innerHTML.match(/<tbody><tr><td[^>]*>([^<]+)/)[1];
  head().onclick();
  const descending=payloads.DATA_ALL.resilience.researchers.slice().sort((a,b)=>b.degree-a.degree);
  assert.equal(first(),descending[0].person);
  head().onclick();
  const ascending=payloads.DATA_ALL.resilience.researchers.slice().sort((a,b)=>a.degree-b.degree);
  assert.equal(first(),ascending[0].person);
});

test('generated filtered download contains exactly the filtered-variant research rows',async()=>{
  const d=dashboard();d.run('state.flag="out";render();');
  d.el('rsDownload').onclick();
  const csv=await d.blobs.at(-1).text();
  for(const row of payloads.DATA_NF.resilience.researchers)assert.ok(csv.includes('"'+row.person+'"'));
  const filteredIds=new Set(payloads.DATA_NF.resilience.researchers.map(r=>r.person));
  for(const row of payloads.DATA_ALL.resilience.researchers)if(!filteredIds.has(row.person))assert.equal(csv.includes('"'+row.person+'"'),false);
  assert.equal(csv.split('\r\n').length,payloads.DATA_NF.resilience.researchers.length+1);
});

test('all normal generated dashboard renderers execute for both real variants with adapters',()=>{
  const d=dashboard();
  for(const flag of ['in','out'])for(const tab of d.run('TABS.slice()')){
    assert.doesNotThrow(()=>d.run('state.flag='+JSON.stringify(flag)+';state.tab='+JSON.stringify(tab)+';render();'),flag+' '+tab);
  }
});

test('metric headers, titles, role labels and current hub cutoff agree with active fields',()=>{
  const d=dashboard();
  for(const flag of ['in','out']) {
    d.run('state.flag='+JSON.stringify(flag)+';render();');
    const r=(flag==='in'?payloads.DATA_ALL:payloads.DATA_NF).resilience;
    const html=d.el('rsTable').innerHTML;
    for(const label of ['Global pair loss (%)','Component-local pair loss (%)','Cross-community link share (%)','Pairs disconnected','Local eligible pairs'])assert.ok(html.includes(label),label);
    assert.match(html,/Normalized unweighted shortest-path betweenness/);
    assert.ok(!html.includes('Critical bridge'));
    assert.ok(!d.el('rsMethod').innerHTML.includes('Critical bridge'));
    assert.ok(!d.el('rsMethod').innerHTML.includes('undefined'));
    assert.ok(d.el('rsMethod').innerHTML.includes('at least '+(100*r.rules.high_impact_loss_fraction).toFixed(1)+'%'));
    assert.ok(d.el('rsMethod').innerHTML.includes('degree ≥'+r.rules.hub_min_degree));
    assert.match(d.el('rsMethod').innerHTML,/cutoff recalculated independently for each paper variant/);
    assert.ok(d.el('rsMethod').innerHTML.includes(r.summary.degree_top10_impact_top10_tie_inclusive_overlap+' including all cutoff-score ties'));
    assert.match(d.el('rsDetail').innerHTML,/Component-local pair loss/);
    assert.match(d.el('rsFragmentHint').textContent,/All surviving members/);
    assert.match(d.el('subtitle').textContent,/Statistics built/);
    assert.match(d.el('subtitle').textContent,/Corpus snapshot date unrecorded/);
    assert.ok(d.el('subtitle').textContent.includes((flag==='in'?payloads.DATA_ALL:payloads.DATA_NF).meta.generated));
  }
});

test('more than twelve fragments expose exact omitted fragments and survivor coverage',()=>{
  const r=structuredClone(payloads.DATA_ALL.resilience), example=r.researchers[0];
  const count=16;
  r.researchers=Array.from({length:count},(_,i)=>({...example,person:'star'+i,name:'Star '+i,
    original_component_size:count,component_survivor_pairs_before:(count-1)*(count-2)/2,
    local_pair_loss_fraction:i===0?1:0,degree:i===0?count-1:1,
    fragment_sizes:i===0?Array(count-1).fill(1):[count-1]}));
  r.edges=Array.from({length:count-1},(_,i)=>['star0','star'+(i+1),1]);
  const d=dashboard(true,true,r);
  assert.equal(d.el('rsFragments').plot.traces[0].y.length,12);
  assert.match(d.el('rsFragmentHint').textContent,/12 of 15 fragments shown, covering 12 of 15 survivors/);
  assert.match(d.el('rsFragmentHint').textContent,/3 smaller fragments \(3 survivors\) omitted/);
  d.el('rsPerson').value='star1';d.el('rsPerson').onchange();
  assert.match(d.el('rsFragmentHint').textContent,/All surviving members/);
  d.el('rsSearch').value='impossible query';d.el('rsSearch').oninput();
  assert.equal(d.el('rsFragmentHint').textContent,'');
});

test('local score unavailable is explicit and matching download uses raw fractions',async()=>{
  const d=dashboard();
  const isolated=payloads.DATA_ALL.resilience.researchers.find(r=>r.original_component_size===1);
  d.el('rsPerson').value=isolated.person;d.el('rsPerson').onchange();
  assert.match(d.el('rsDetail').innerHTML,/unavailable \(no surviving pair\)/);
  d.el('rsSearch').value=isolated.person;d.el('rsSearch').oninput();
  d.el('rsDownload').onclick();
  const lines=(await d.blobs.at(-1).text()).replace(/^\uFEFF/,'').split('\r\n');
  const headers=lines[0].split(','), values=lines[1].slice(1,-1).split('","');
  assert.equal(values[headers.indexOf('local_pair_loss_fraction')],'');
  assert.equal(values[headers.indexOf('component_survivor_pairs_before')],'0');
  assert.equal(values[headers.indexOf('lost_pair_fraction')],String(isolated.lost_pair_fraction));
  assert.ok(headers.includes('is_high_impact_articulation'));
  assert.ok(!headers.includes('is_critical_bridge'));
});

test('numeric share sorting uses raw values with missing local denominators last',()=>{
  const d=dashboard();
  for(const key of ['cross_community_fraction','lost_pair_fraction','local_pair_loss_fraction']) {
    const header=()=>d.el('rsTable').children.find(e=>e.dataset.k===key);
    const first=()=>d.el('rsTable').innerHTML.match(/<tbody><tr><td[^>]*>([^<]+)/)[1];
    header().onclick();
    const valid=payloads.DATA_ALL.resilience.researchers.filter(r=>r[key]!=null);
    const max=Math.max(...valid.map(r=>r[key]));
    assert.equal(payloads.DATA_ALL.resilience.researchers.find(r=>r.person===first())[key],max);
    header().onclick();
    const min=Math.min(...valid.map(r=>r[key]));
    assert.equal(payloads.DATA_ALL.resilience.researchers.find(r=>r.person===first())[key],min);
  }
});

test('switching variants preserves researcher identity but replaces all removal metrics',()=>{
  const d=dashboard(), filtered=new Map(payloads.DATA_NF.resilience.researchers.map(r=>[r.person,r]));
  const before=payloads.DATA_ALL.resilience.researchers.find(r=>filtered.has(r.person) && filtered.get(r.person).lost_connected_pairs!==r.lost_connected_pairs);
  d.el('rsPerson').value=before.person;d.el('rsPerson').onchange();
  d.run('state.flag="out";render();');
  const after=filtered.get(before.person);
  assert.equal(d.el('rsPerson').value,before.person);
  assert.deepEqual(Array.from(d.el('rsFragments').plot.traces[0].y),after.fragment_sizes.slice(0,12));
  assert.ok(d.el('rsDetail').innerHTML.includes(before.person));
  assert.ok(d.el('rsDetail').innerHTML.includes(after.component_survivor_pairs_before.toLocaleString('en-IN')));
  const data=d.el('rsScatter').plot.traces[0], i=data.customdata.indexOf(before.person);
  assert.equal(data.y[i],after.lost_pair_fraction);
});

test('empty downloads retain the complete active-variant schema',async()=>{
  const d=dashboard();
  d.el('rsDownload').onclick();
  const header=(await d.blobs.at(-1).text()).split('\r\n')[0];
  d.el('rsSearch').value='no such researcher';d.el('rsSearch').oninput();
  d.el('rsDownload').onclick();
  assert.equal(await d.blobs.at(-1).text(),header);
  assert.ok(header.includes('component_survivor_pairs_before'));
});

test('URL state follows controls and survives reload while preserving other hash parameters',()=>{
  const d=dashboard(true,true,null,'#tab=Network%20Resilience&theme=dark&review=keep');
  d.run('state.flag="out";state.inst="TIFR";state.tab="Method";render();');
  const hash=d.context.location.hash, params=new URLSearchParams(hash.slice(1));
  assert.equal(params.get('flag'),'out');assert.equal(params.get('inst'),'TIFR');assert.equal(params.get('tab'),'Method');
  assert.equal(params.get('theme'),'dark');assert.equal(params.get('review'),'keep');
  const reloaded=dashboard(true,true,null,hash);
  assert.equal(reloaded.run('state.flag'),'out');assert.equal(reloaded.run('state.inst'),'TIFR');assert.equal(reloaded.run('state.tab'),'Method');
});
