/* Shared bounded explorer; no acquisition, external libraries, or global UI state. */
(function(global){
'use strict';
function eligible(r,scope){return (scope.inst==='All'||r.homes.includes(scope.inst))&&(scope.flag!=='out'||r.authors_gt_12===false);}
function hasQuery(r){return r.query_complete||!['not_started','pending','unresolved_identity'].includes(r.query_status)||r.observed_citers>0;}
function filterRows(seeds,state,scope={inst:"All",flag:"in"}){
 const q=state.search.toLowerCase();
 const rows=seeds.filter(r=>eligible(r,scope)&&(!q||(r.title+' '+r.original_id+' '+(r.canonical_id||'')).toLowerCase().includes(q))&&
  (state.institution==='All'||(state.institution==='Joint'?r.homes.length>1:r.homes.includes(state.institution)))&&
  (state.field==='All'||(r.field_id||'Unknown')===state.field)&&(state.year==='All'||String(r.year)===state.year)&&(!state.pilot||r.pilot)&&
  (state.coverage==='All'||(state.coverage==='complete'?r.query_complete:state.coverage==='not_started'?!hasQuery(r):hasQuery(r)&&!r.query_complete)));
 return rows.sort((a,b)=>{
  if(state.sort==='id')return a.original_id.localeCompare(b.original_id);
  const key={citers:'observed_citers',share:'cross_field_share',year:'year'}[state.sort];
  if(a[key]==null||b[key]==null)return a[key]==null?(b[key]==null?0:1):-1;
  return b[key]-a[key]||a.original_id.localeCompare(b.original_id);
 });
}
function csvText(columns,rows){
 const cell=x=>'"'+String(x==null?'':Array.isArray(x)?x.join(';'):x).replaceAll('"','""')+'"';
 return '\ufeff'+[columns.map(cell).join(','),...rows.map(r=>columns.map(k=>cell(r[k])).join(','))].join('\r\n')+'\r\n';
}
function denominatorBreakdown(s){
 const missingSeedKnown=s.known_field_citers-s.cross_denominator;
 const valid=Number.isInteger(missingSeedKnown)&&missingSeedKnown>=0&&s.direct_edges===s.known_field_citers+s.unknown_field_citers&&s.cross_numerator>=0&&s.cross_numerator<=s.cross_denominator;
 return {valid,total:s.direct_edges,unknownCiter:s.unknown_field_citers,unknownSeed:missingSeedKnown,classifiable:s.cross_denominator,cross:s.cross_numerator};
}
function learningMarkup(prefix){
 return `<div class="learn-intro card panel" id="${prefix}learnBasics"><h2>What are we following?</h2><p>We start with <b>seed papers</b> from IISc and TIFR and examine which later works cite them, which research fields those works belong to, and how far we can trace citation paths. A citation records a scholarly link; it does not automatically show that an idea was adopted.</p>
 <details><summary>Learn the basics: four papers and two arrow directions</summary><p><b>Illustrative example, not a study result:</b> A is a seed. B and C cite A, so B and C are <b>direct citers (G1)</b>. D cites B, making D a <b>second-hop work (G2)</b> through B. D counts as a direct citer of A only if a separate D→A citation is recorded.</p><p>The stored citation edge points <b>from citing paper to cited paper: B → A</b>. The explorer follows the opposite direction, <b>A → B → D, meaning “is cited by”</b>. A citation could acknowledge background, reuse a method, compare results or disagree. Same-year order can be uncertain and year inversions remain flagged.</p><p><b>Link versus unique work:</b> if B cites two different seeds, that is 2 links but 1 unique citing work. Do not add per-seed unique counts to estimate a population's unique audience.</p><p><b>Primary field:</b> OpenAlex assigns one main field label to a paper; it does not capture every topic. If seed A is Physics, a Physics citer is in-field and a Chemistry citer is cross-field. Of 4 classified citers, 1 cross-field gives 1/4 = 25%. A fifth citer with an unknown field is excluded from that denominator, not treated as in-field. Higher means more label difference, not higher quality or proven transfer.</p></details>
 <details><summary>Start here: nine steps through a real seed</summary><ol>
 <li>Choose Both, IISc or TIFR in the header. These choose the original seed population; worldwide citing works remain in scope. In the standalone preview, use the institution control beside the table.</li>
 <li>Read the seed count and paper-size setting. Excluding >12-author papers removes flagged <em>seeds</em>, not large external citing works. A joint IISc/TIFR seed belongs to each institution and is counted once in Both.</li>
 <li>Choose a retrieved seed field or publication year. These refine the table and its seed CSV; they do not recompute the headline population or fetch more papers.</li>
 <li>Select a paper title in the table. Read its ordinary-language summary below; each table row is one original ID.</li>
 <li>Inspect its direct citers in the displayed path excerpt. Missing excerpts are not empty citation histories.</li>
 <li>Compare the seed's primary field with the citer fields. Read both numerator and known-field denominator; unknown labels stay unknown.</li>
 <li>Use “Open paper” or a citation title to inspect a concrete work. Links open external sources only when you choose them. Edge evidence proves a recorded reference, not what its passage means.</li>
 <li>Choose sampled G2 to inspect any available two-step paths. Only two seeds have a G2 sample; unvisited branches remain unknown. Both edge proofs are shown where paths exist.</li>
 <li>Export filtered seeds for every matching table row, beyond the visible page. Export displayed paths for just that seed's bounded excerpt; it is not the complete citation network.</li>
 </ol><p id="${prefix}walkExample"></p></details></div>`;
}
function create(options){
const IDEA_DATA=options.data,root=options.root||document,prefix=options.prefix||'';
let scope={inst:'All',flag:'in'};
const COLUMNS=['original_id','canonical_id','title','homes','year','stored_type','stored_citations','citation_band','sampling_field','retrieved_field','field_id','field_drift','identity_status','provider_self_reference','query_status','query_complete','observed_citers','known_field_citers','unknown_field_citers','cross_field_citers','cross_field_share','field_coverage','richness','rarefied_richness_10','known_year_citers','known_date_citers','known_type_citers'];
const PATH_COLUMNS=['seed','cited','citing','generation','title','doi','year','type','field','chronology','frontier_id','snapshot','retrieved_utc','parent_frontier_id','parent_snapshot','parent_retrieved_utc','evidence_status'];
const state={search:'',institution:'All',field:'All',year:'All',coverage:'All',pilot:false,sort:'id',page:0,selected:null,window:'cutoff'};
const $=id=>root.querySelector('[id="'+prefix+id+'"]');
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=x=>Number(x).toLocaleString('en-US');
const pct=x=>x==null?'Unavailable':(100*x).toFixed(1)+'%';
const precisePct=x=>x==null?'Unavailable':(100*x).toFixed(2)+'%';
const label=r=>r.query_complete?(r.query_status==='complete_empty'?'Complete · empty':'Complete'):r.query_status==='not_started'||r.query_status==='pending'?'Not acquired':r.query_status.replaceAll('_',' ');
function link(w){return w.doi&&/^10\.\d{4,9}\//i.test(w.doi)?'https://doi.org/'+encodeURI(w.doi):'https://openalex.org/'+encodeURIComponent(w.id||w.canonical_id||w.original_id);}
function filtered(){return filterRows(IDEA_DATA.seeds,state,scope);}
function download(name,columns,rows){const url=URL.createObjectURL(new Blob([csvText(columns,rows)],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);}
function pathExport(){
 const s=IDEA_DATA.seeds.find(r=>r.original_id===state.selected&&eligible(r,scope));if(!s)return[];
 const p=IDEA_DATA.paths[s.canonical_id];if(!p)return[];
 return [...p.g1,...p.g2].map(r=>({seed:s.canonical_id,cited:r.cited,citing:r.id,generation:r.generation,title:r.title,doi:r.doi,year:r.year,type:r.type,field:r.field,chronology:r.chronology,frontier_id:r.evidence?.frontier_id,snapshot:r.evidence?.page,retrieved_utc:r.evidence?.retrieved_utc,parent_frontier_id:r.parent_evidence?.frontier_id,parent_snapshot:r.parent_evidence?.page,parent_retrieved_utc:r.parent_evidence?.retrieved_utc,evidence_status:'API bibliographic link; text interpretation unverified'}));
}
function renderTable(){
 const rs=filtered();
 updateWalkExample(rs);
 if(!rs.some(r=>r.original_id===state.selected))state.selected=rs[0]?.original_id||null;
 const pages=Math.max(1,Math.ceil(rs.length/30));state.page=Math.min(state.page,pages-1);
 $('resultCount').textContent=n(rs.length)+' matching original works';
 $('seedRows').innerHTML=rs.slice(state.page*30,state.page*30+30).map(r=>`<tr class="${r.original_id===state.selected?'active':''}"><td><button class="seed-button" data-seed="${esc(r.original_id)}">${esc(r.title||'[Title unavailable]')}</button><span class="id">${esc(r.original_id)}</span></td><td>${esc(r.homes.join(' / '))}<br><span class="tiny">${r.year}</span></td><td>${esc(r.retrieved_field||'Unknown / not retrieved')}</td><td>${hasQuery(r)?n(r.observed_citers):'Not acquired'}</td><td>${hasQuery(r)?n(r.known_field_citers)+' / '+n(r.unknown_field_citers):'Unavailable'}</td><td>${pct(r.cross_field_share)}</td><td><span class="badge ${r.query_complete?'complete':hasQuery(r)?'partial':'pending'}">${esc(label(r))}</span></td></tr>`).join('')||'<tr><td colspan="7" class="empty">No papers match these filters. Empty filters do not change acquisition coverage.</td></tr>';
 renderDetail();
 $('pageCount').textContent='Page '+(state.page+1)+' of '+pages+' · 30 rows per page';$('previous').disabled=state.page===0;$('next').disabled=state.page>=pages-1;
 $('seedRows').querySelectorAll('[data-seed]').forEach(b=>b.addEventListener('click',()=>{state.selected=b.dataset.seed;renderTable();}));
}
function renderDetail(){
 const r=IDEA_DATA.seeds.find(s=>s.original_id===state.selected&&eligible(s,scope));if(!r){options.compositionPlot?.([],null,null,IDEA_DATA.field_names);['seedDetail','composition','pathScope','pathRows'].forEach(id=>$(id).textContent='No selected seed matches these filters.');$('downloadPaths').disabled=true;return;}
 const evidence=r.query_complete?'Source query exhausted':r.query_status==='unresolved_identity'?'Provider identity unresolved; no direct-citer query':hasQuery(r)?'Partial observation; frontier incomplete':'Direct-citer acquisition not started';
 $('seedDetail').innerHTML=`<div class="eyebrow">G0 · ${esc(r.homes.join(' / '))} · ${r.year}</div><div class="detail-title">${esc(r.title)}</div><a href="${esc(link(r))}" target="_blank" rel="noopener">Open paper ↗</a><span class="id">${esc(r.original_id)}${r.canonical_id&&r.canonical_id!==r.original_id?' → '+esc(r.canonical_id):''}</span><div class="metric-row"><div><strong>${hasQuery(r)?n(r.observed_citers):'—'}</strong><span>observed direct citers</span></div><div><strong>${pct(r.cross_field_share)}</strong><span>cross-field share · n=${n(r.known_field_citers)} known</span></div><div><strong>${hasQuery(r)?n(r.richness):'—'}</strong><span>observed fields</span></div></div><p class="tiny">${esc(evidence)}. ${n(r.unknown_field_citers)} retrieved citers have unknown fields. Retrieved seed field: ${esc(r.retrieved_field||'unavailable')}.</p><p class="tiny">${r.provider_self_reference?'Provider same-ID reference flagged; excluded from distinct-paper reach. ':''}Sampling field: ${esc(r.sampling_field||'unknown')}${r.field_drift?' · FIELD DRIFT RECORDED':''}. Stored citation band: ${esc(r.citation_band)}. All publication types retained.</p><p class="tiny">Equal-age window: ${esc(r.age_window.status)}. Exact expected richness at ten known citers: ${r.rarefied_richness_10==null?'unavailable':r.rarefied_richness_10.toFixed(3)}.</p><details><summary>Chronology and query provenance</summary><pre>${esc(JSON.stringify({chronology:r.chronology,frontier:r.query_frontier,query_reason:r.query_reason,age_window:r.age_window},null,2))}</pre></details>`;
 $('seedDetail').insertAdjacentHTML('afterbegin',`<p class="learn-observation"><b>In ordinary language:</b> This seed belongs to ${esc(r.homes.join(' / '))}. ${!hasQuery(r)?'Its direct-citer reach is not yet known.':n(r.observed_citers)+' distinct acquired works cite it directly.'} ${r.cross_field_share==null?'A cross-field percentage is unavailable because the seed field or a usable denominator is missing.':n(r.cross_field_citers)+' of '+n(r.known_field_citers)+' known-field citers have a different primary field ('+precisePct(r.cross_field_share)+').'} ${n(r.unknown_field_citers)} citer fields are unknown. This is a citation-label comparison, not evidence of idea adoption.</p>`);
 const g2result=IDEA_DATA.g2_results?.seeds.find(s=>s.seed===r.canonical_id);
 const metric=state.window==='g2'?g2result?.g2_field_composition:state.window==='age'?r.age_window.metrics:r;
 const entries=Object.entries(metric?.field_counts||{}).sort((a,b)=>b[1]-a[1]);const max=entries[0]?.[1]||1;
 const windowLabel=state.window==='g2'?'Conditional G2, sampled intermediates only':state.window==='age'?`Equal-age window ${r.retrieved_year}–${r.retrieved_year+3}`:'Through publication cutoff';
 $('composition').innerHTML=entries.length?`<p class="tiny">${esc(windowLabel)} · ${n(metric.known_field_citers)} classified distinct citers · ${n(metric.unknown_field_citers)} unknown${state.window!=='g2'?' · cross-field share '+pct(metric.cross_field_share):' · not a global G2 estimate'}. Green marks the seed's field.</p><div class="bars">${entries.map(([id,count])=>`<div class="bar-row"><span>${esc(IDEA_DATA.field_names[id]||id)}</span><div class="bar-track"><div class="bar-fill ${id===r.field_id?'seed-field':''}" style="width:${100*count/max}%"></div></div><b>${n(count)}</b></div>`).join('')}</div>`:`<div class="empty">${state.window==='g2'?'No acquired classifiable G2 for the selected sample. Unvisited branches remain unknown.':state.window==='age'&&r.age_window.status!=='eligible'?'Equal-age comparison unavailable: '+esc(r.age_window.status)+'. Recent windows are right-censored.':'No classified citers are available for this seed.'} This does not establish a lack of cross-field reach.</div>`;
 if(options.compositionPlot){$('composition').querySelector('.bars')?.remove();options.compositionPlot(entries,r,metric,IDEA_DATA.field_names);}
 $('composition').insertAdjacentHTML('beforeend',`<p class="tiny">${state.window==='g2'?'G2 is a conditional sample, not full-population reach.':state.window==='age'?'Right-censoring means a newer paper has not yet had its seed year and three following years fully observed; unavailable windows are not zeros.':'Each bar counts acquired distinct citing works in one primary field, not their number of topics.'} ${r.retrieved_field?'Seed field: '+esc(r.retrieved_field)+'. Match the written field name on the axis; matching labels are in-field, other known labels cross-field.':'The seed field is unknown, so in-field versus cross-field cannot be assigned.'}</p>`);
 const paths=IDEA_DATA.paths[r.canonical_id];
 $('pathScope').textContent=paths?`${paths.g1.length} of ${paths.g1_total} direct links shown; ${paths.g1_omitted} omitted from this excerpt. ${paths.g2_sample?'G2 uses ten sampled G1 intermediates; later links below are also excerpted.':'G2 not acquired for this seed; unvisited branches are unknown.'}`:'No path excerpt is embedded for this seed. This explorer embeds bounded examples; consult the normalized citation tables for all acquired links.';
 $('pathRows').innerHTML=paths?[...paths.g1,...paths.g2].map(w=>`<div class="path-row"><div class="path-label">G${w.generation} · ${w.year??'year unknown'} · ${esc(w.type||'type unknown')} · ${esc(w.field||'field unknown')} · ${esc(w.chronology)}${w.generation===2?' · sampled branch via '+esc(w.parent?.title||w.cited):''}</div><a href="${esc(link(w))}" target="_blank" rel="noopener">${esc(w.title||w.id)} ↗</a><span class="id">${w.generation===2?esc(r.canonical_id)+' → ':''}${esc(w.cited)} → ${esc(w.id)} · is cited by</span>${w.evidence?`<details><summary>Relationship evidence</summary><pre>${esc(JSON.stringify(w.parent_evidence?{seed_to_intermediate:w.parent_evidence,intermediate_to_citer:w.evidence}:w.evidence,null,2))}</pre></details>`:''}</div>`).join('')||'<div class="empty">No links in this acquired excerpt.</div>':'<div class="empty">Path excerpt unavailable. No branch-ending claim is made.</div>';
 $('downloadPaths').disabled=!paths||!(paths.g1.length+paths.g2.length);
 if(paths?.g2_sample&&g2result)$('pathScope').textContent+=' Conditional G2 sample: '+paths.g2_sample.sampled_intermediates.length+' of '+paths.g2_sample.g1_population+' direct intermediates (selection probability '+paths.g2_sample.selection_probability+'); '+g2result.observed_new_g2_distinct+' distinct new G2 works and '+g2result.g1_g2_overlap+' already-direct overlaps. Unvisited branches remain unknown.';
}
function renderStories(){
 $('cases').innerHTML=IDEA_DATA.cases.candidates.filter(c=>IDEA_DATA.seeds.some(r=>r.original_id===c.original_id&&eligible(r,scope))).map(c=>`<article class="case"><div class="eyebrow">${esc(c.role)}</div><h3>${esc(c.title)}</h3><span class="badge partial">Bibliographic candidate</span><p>${pct(c.cross_field_share)} cross-field share among ${n(c.known_denominator)} known-field citers.</p><p>${esc(c.evidence_status)}</p><button data-case="${esc(c.original_id)}">Inspect this seed →</button></article>`).join('')||'<div class="panel empty">No candidate meets the declared metadata and coverage criteria yet.</div>';
 $('cases').querySelectorAll('[data-case]').forEach(b=>b.onclick=()=>{state.search=b.dataset.case;state.pilot=false;state.field=state.year=state.coverage=state.institution='All';state.page=0;for(const id of ['field','year','coverageFilter','institution'])$(id).value='All';$('pilotOnly').checked=false;$('search').value=state.search;state.selected=b.dataset.case;renderTable();$('paths').scrollIntoView({behavior:'smooth'});});
 const reviewed=(IDEA_DATA.reviewed_cases||[]).filter(c=>IDEA_DATA.seeds.some(r=>r.canonical_id===c.seed&&eligible(r,scope)));
 $('reviewedSection').hidden=!reviewed.length;
 $('reviewedCases').innerHTML=reviewed.map(c=>`<article class="case"><div class="eyebrow">${esc(c.relation_type)}</div><h3>${esc(c.metric_row?.title||c.seed)}</h3><span class="badge ${c.bibliographic_edge_in_study?'complete':'partial'}">${c.bibliographic_edge_in_study?'Citation edge verified':'Edge unresolved'}</span><span class="id">${esc(c.seed)} → ${esc(c.citing)} · is cited by</span>${c.citing_work?`<p><a href="${esc(link(c.citing_work))}" target="_blank" rel="noopener">${esc(c.citing_work.title)} ↗</a></p>`:""}<p>${esc(c.supported_interpretation)}</p><p>${esc(c.limitations)}</p><details><summary>Text evidence and access limits</summary><p>${esc(c.original_evidence)}</p><p>${esc(c.citing_evidence)}</p><p>${esc(c.reviewer)} · Independent human review: ${c.independent_human_review?'yes':'no'}</p><pre>${esc(JSON.stringify({checked_utc:c.checked_utc,api_edge_evidence:c.api_edge_evidence},null,2))}</pre>${c.source_urls.filter(u=>/^https:\/\//.test(u)).map(u=>`<p><a href="${esc(u)}" target="_blank" rel="noopener">Source ↗</a></p>`).join('')}</details></article>`).join('');
}
function initialize(){
 $('overview').insertAdjacentHTML('afterbegin',learningMarkup(prefix));
 $('tiles').insertAdjacentHTML('afterend',`<div class="learn-denominator" id="${prefix}denominatorHelp"></div><div class="learn-intro" id="${prefix}learningSummary"></div>`);
 $('resultCount').parentElement.insertAdjacentHTML('afterend',`<p class="tiny" id="${prefix}filterNote">Local filters refine the table, selected seed and seed CSV. Header institution / paper-size controls set the headline population; no control acquires new data.</p><details class="learn-intro"><summary>What does each filter change?</summary><p><b>Search</b> matches seed titles or IDs. <b>Institution</b> uses original seed membership, including joint papers; a separate local institution control in the standalone preview refines its table. <b>Retrieved seed field</b> filters the seed's primary field, not citer fields. <b>Publication year</b> selects a seed cohort, not an equal exposure time.</p><p><b>Query coverage</b> selects exhausted, partial or unstarted provider queries; “complete” means stored pagination was exhausted, not that all global scholarship was found. <b>Pilot only</b> selects the fixed 24-paper initial sample; it does not start a new study. <b>Sort</b> changes order only: numeric high-to-low, unknown ratios last; Work ID sorts alphabetically. Pagination displays 30 rows; the seed CSV includes all matches at full precision.</p><p><b>Field-composition scope</b> changes only the selected paper's composition: all direct observations, the seed year plus three following years, or conditional sampled G2. It does not change header totals or resample G2. <b>Missing metadata</b> means unknown, not zero or in-field; an unknown seed field also prevents cross-field classification.</p></details>`);
 const filterHints={search:'Match seed titles or work IDs; no data is acquired.',institution:'Refine seed membership, including joint papers; worldwide citing works stay in scope.',field:'Select the seed primary field, not the fields of its citers.',year:'Select the seed publication cohort; this does not equalize time since publication.',coverageFilter:'Provider-query state, not completeness of all global scholarship.',pilotOnly:'The fixed 24-paper pilot subset; this does not acquire or resample data.',sort:'Change row order only; numeric values descend, unknown ratios last.',compositionWindow:'Change the selected seed composition only; G2 is sampled and recent age windows can be censored.'};
 for(const [id,hint] of Object.entries(filterHints)){if(id!=='compositionWindow')$(id).setAttribute('aria-describedby',prefix+'filterNote');$(id).title=hint;}
 const completed=IDEA_DATA.seeds.filter(r=>r.query_complete).length;
 const unresolved=IDEA_DATA.seeds.filter(r=>!r.canonical_id).length;
 $('cutoffLabel').textContent='Publication cutoff · '+IDEA_DATA.cutoff+' UTC';$('scopePill').textContent='OpenAlex Core · worldwide citing works';
 $('notice').textContent=IDEA_DATA.summary.full_quality_gate.passed?`Direct-citer acquisition passed the full-corpus quality gate. ${n(unresolved)} original IDs remain provider-unresolved. Source indexing and metadata limitations still apply.`:`Acquisition in progress or incomplete: ${n(completed)} of ${n(IDEA_DATA.seeds.length)} original seeds have exhausted direct-citer queries. Remaining reach is unknown.`;
 const known=IDEA_DATA.seeds.reduce((a,r)=>a+r.known_field_citers,0),unknown=IDEA_DATA.seeds.reduce((a,r)=>a+r.unknown_field_citers,0);
 $('tiles').innerHTML=[['Original seeds covered',n(completed)+' / '+n(IDEA_DATA.seeds.length),'Query completion, not scholarly completeness'],['Distinct direct citers',n(IDEA_DATA.distinct_direct_citers),'Unique acquired works that cite an original seed'],['Direct citation links',n(IDEA_DATA.direct_edges),'Distinct citing → cited work pairs'],['Known citing fields',known+unknown?pct(known/(known+unknown)):'Unavailable','Coverage across observed seed–citer incidences']].map(([l,v,s])=>`<div class="tile"><span class="label">${l}</span><span class="value">${v}</span><small>${s}</small></div>`).join('');
 const fields=[...new Set(IDEA_DATA.seeds.map(r=>r.field_id||'Unknown'))].sort((a,b)=>(IDEA_DATA.field_names[a]||a).localeCompare(IDEA_DATA.field_names[b]||b));
 $('field').innerHTML='<option value="All">All fields</option>'+fields.map(f=>`<option value="${esc(f)}">${esc(IDEA_DATA.field_names[f]||f)}</option>`).join('');
 $('year').innerHTML='<option value="All">All years</option>'+[...new Set(IDEA_DATA.seeds.map(r=>r.year))].sort().map(y=>`<option>${y}</option>`).join('');
 const pairs=[['search','search','input'],['institution','institution','change'],['field','field','change'],['year','year','change'],['coverageFilter','coverage','change'],['sort','sort','change']];
 pairs.forEach(([id,key,event])=>$(id).addEventListener(event,()=>{state[key]=$(id).value;state.page=0;renderTable();}));
 $('pilotOnly').addEventListener('change',()=>{state.pilot=$('pilotOnly').checked;state.page=0;renderTable();});
 $('compositionWindow').addEventListener('change',()=>{state.window=$('compositionWindow').value;renderDetail();});
 $('previous').onclick=()=>{state.page--;renderTable();};$('next').onclick=()=>{state.page++;renderTable();};
 $('downloadSeeds').onclick=()=>download('follow-the-idea-filtered-seeds.csv',COLUMNS,filtered());
 $('downloadPaths').onclick=()=>download('follow-the-idea-displayed-path-excerpt.csv',PATH_COLUMNS,pathExport());
 renderStories();
 $('coverageStats').innerHTML=[['Provider','OpenAlex Core'],['Original seeds',n(IDEA_DATA.seeds.length)],['Queries exhausted',n(completed)],['Not exhausted',n(IDEA_DATA.seeds.length-completed)],['Provider-unresolved IDs',n(unresolved)],['Resolved seeds missing field',n(IDEA_DATA.seeds.filter(r=>r.canonical_id&&!r.field_id).length)],['Equal-age eligible seeds',n(IDEA_DATA.seeds.filter(r=>r.age_window.status==='eligible').length)],['Right-censored seeds',n(IDEA_DATA.seeds.filter(r=>r.age_window.status==='right_censored').length)],['Provider same-ID reference flags',n(IDEA_DATA.seeds.filter(r=>r.provider_self_reference).length)],['Known field incidences',n(known)],['Unknown field incidences',n(unknown)],['Retrieval started',IDEA_DATA.provenance.first_retrieval||'Not started'],['Retrieval latest',IDEA_DATA.provenance.last_retrieval||'Not started'],['G2 scope',IDEA_DATA.g2.eligible_to_acquire?'Sampled frontiers; see provenance':'Not acquired / quality gate pending'],['Affiliations','Not collected in this release']].map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
 $('frontierStates').textContent=JSON.stringify(IDEA_DATA.summary.acquired.frontiers,null,2);$('provenance').textContent=JSON.stringify(IDEA_DATA.provenance,null,2);
 $('taxonomyNote').textContent='Classification: primary_topic.field.id; one primary field per work. Sampling labels and retrieved fields are retained separately. Metadata retrieved later does not recreate the index as it existed at the publication cutoff.';
 $('footer').textContent='Group 18 · Follow the Idea · Local preview built '+IDEA_DATA.generated_utc+' · Bibliographic linkage is not proof of idea adoption.';
 state.selected=(IDEA_DATA.seeds.find(r=>r.pilot&&r.query_complete)||IDEA_DATA.seeds[0])?.original_id;
 const s=IDEA_DATA.scopes?.in?.All;
 if(s)renderPopulation(s,'Both institutions · flagged seed papers included');
 if(!options.deferRender)renderTable();
}
function renderPopulation(s,title){
 const d=denominatorBreakdown(s);
 $('tiles').innerHTML=[['Seed IDs covered',n(s.completed)+' / '+n(s.original_seeds),'Resolved query IDs / original IDs; '+n(s.unresolved)+' provider-unresolved'],['Distinct direct citers',n(s.distinct_direct_citers),'Each citing work counted once across these seeds'],['Direct links',n(s.direct_edges),'One citing → cited pair; one work can contribute several links'],['Cross-field share',precisePct(s.cross_field_share),n(s.cross_numerator)+' / '+n(s.cross_denominator)+' classifiable link incidences']].map(([l,v,caption])=>`<div class="tile"><div class="l label">${l}</div><div class="v value">${v}</div><div class="d"><b>${esc(caption)}</b><br>${esc(title)}</div></div>`).join('');
 $('denominatorHelp').innerHTML=d.valid?`<strong>Read the cross-field denominator:</strong> ${n(d.total)} total links − ${n(d.unknownCiter)} with unknown citing fields − ${n(d.unknownSeed)} additional links whose seed field is unavailable = <strong>${n(d.classifiable)} classifiable link incidences</strong>. The last group has known citing fields, so it is not subtracted twice. ${n(d.cross)} / ${n(d.classifiable)} = ${precisePct(s.cross_field_share)}. This is a <b>link-level</b> statistic from primary-field labels, not the percentage of unique citing works that adopted an idea or a measure of research quality.`:'Classification counts do not reconcile; do not infer a denominator. Inspect the frozen metadata before interpreting this percentage.';
 $('learningSummary').innerHTML=`<h3>What did we learn?</h3><p class="learn-observation"><b>Observation.</b> ${n(s.original_seeds-s.unresolved)} of ${n(s.original_seeds)} original IDs resolved in this header scope; ${n(s.distinct_direct_citers)} distinct direct works contribute ${n(s.direct_edges)} links. Links can outnumber works because a work may cite several seeds.</p><p><b>Interpretation / why care?</b> Comparing primary fields shows the disciplinary spread of recorded citation links. Joint seed memberships overlap; institutional subtotals cannot be added to obtain a combined unique audience.</p><p class="learn-limit"><b>Limits.</b> ${n(s.age_censored)} seed windows are right-censored. G2 is sampled, provider coverage is incomplete, and source-inspected stories have no independent human review. Neither citations nor field differences establish idea adoption.</p>`;
 updateWalkExample(filtered());
}
function updateWalkExample(rows){
 const example=rows.find(r=>r.query_complete&&r.observed_citers>0&&IDEA_DATA.paths[r.canonical_id]);
 $('walkExample').textContent=example?'One available example in the current table scope: '+example.original_id+' — '+example.title+'; '+n(example.observed_citers)+' direct citers. Search this ID and select its title to follow the steps.':'No acquired seed with an embedded path excerpt matches the current local filters. Clear filters to find an example; no missing path is inferred to be empty.';
}
const api={state,filtered,csvText,pathExport,renderTable,renderDetail,columns:COLUMNS,pathColumns:PATH_COLUMNS,data:IDEA_DATA,setScope};
function setScope(inst,flag){
 if(!['All','IISc','TIFR'].includes(inst)||!['in','out'].includes(flag))throw new Error('Invalid research scope');
 scope={inst,flag};
 const s=IDEA_DATA.scopes?.[flag]?.[inst];
 if(!s)throw new Error('Verified scope summary unavailable');
 const title=(inst==='All'?'Both institutions':inst)+' · flagged seed papers '+(flag==='out'?'excluded':'included');
 $('scopePill').textContent=title;
 renderPopulation(s,title);
 $('scopeNote').textContent='Tiles describe the header institution / seed-paper flag scope. Local filters refine the table and seed CSV. Worldwide citing papers are retained. Known cross-field denominator: '+n(s.cross_denominator)+'; cross-field links: '+n(s.cross_numerator)+'; unknown citing fields: '+n(s.unknown_field_citers)+'. Provider-unresolved seeds: '+n(s.unresolved)+'; right-censored seed windows: '+n(s.age_censored)+'.';
 renderStories();renderTable();
}
initialize();
return api;

}
const exported={create,filterRows,csvText,eligible,denominatorBreakdown,learningMarkup};
if(typeof module!=='undefined'&&module.exports)module.exports=exported;
else global.IdeaFlowView=exported;
})(typeof window==='undefined'?globalThis:window);
