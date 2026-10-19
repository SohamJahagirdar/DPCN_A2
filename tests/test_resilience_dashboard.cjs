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
const template = fs.readFileSync(path.join(root, 'pipeline/dashboard_template.html'), 'utf8');
const python = process.env.DPCN_TEST_PYTHON || 'python';
const payloads = JSON.parse(execFileSync(python, ['-B', '-c',
  "import json,sys;sys.path.insert(0,'tests');from test_resilience_snapshot import snapshot_result;out={};\nfor name in ['DATA_ALL','DATA_NF']:\n r,p,_=snapshot_result(name);p['resilience']=r;out[name]=p\nprint(json.dumps(out,ensure_ascii=True))"],
  {cwd:root,encoding:'utf8',maxBuffer:30*1024*1024,env:{...process.env,PYTHONIOENCODING:'utf-8'}}));

function dashboard(withFilteredData=true, hasFilteredPayload=true) {
  const elements = new Map(), networks = [], blobs = [];
  class Element {
    constructor(id) { this.id=id;this.value='';this.checked=false;this.textContent='';this.hidden=false;this.listeners={};this.children=[];this.classList={toggle(){}};this._html=''; }
    set innerHTML(value) {
      this._html=value;
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
  const script=template.match(/<script>\s*([\s\S]*?)<\/script>/)[1]
    .replace('/*__DATA__*/null',JSON.stringify(payloads.DATA_ALL))
    .replace('/*__DATA_NF__*/null',JSON.stringify(nf)).replace('/*__COMPARE__*/null','[]');
  const context=vm.createContext({document,console,URLSearchParams,Blob,
    location:{hash:'#tab=Network%20Resilience'},localStorage:{getItem:()=>null,setItem(){}},
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
  assert.match(d.el('rsTiles').innerHTML,/Critical|critical/);
  assert.match(d.el('rsTable').innerHTML,/Lost pairs/);
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
  d.el('rsRole').value='Critical bridge';d.el('rsRole').onchange();
  const critical=payloads.DATA_ALL.resilience.researchers.filter(r=>r.is_critical_bridge);
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
