'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const {filterRows,csvText,eligible,denominatorBreakdown,learningMarkup}=require('../pipeline/idea_flow_view.js');
const state={search:'',institution:'All',field:'All',year:'All',coverage:'All',pilot:false,sort:'id'};
const rows=[
 {original_id:'W1',title:'Joint known',canonical_id:'W1',homes:['IISc','TIFR'],authors_gt_12:false,field_id:'f1',year:2020,pilot:true,query_complete:true,query_status:'complete',observed_citers:2,cross_field_share:0.123456789},
 {original_id:'W2',title:'Flagged',canonical_id:'W2',homes:['TIFR'],authors_gt_12:true,field_id:'f2',year:2021,pilot:false,query_complete:true,query_status:'complete_empty',observed_citers:0,cross_field_share:null},
 {original_id:'W3',title:'Partial unknown',canonical_id:null,homes:['IISc'],authors_gt_12:false,field_id:null,year:2025,pilot:false,query_complete:false,query_status:'partial',observed_citers:3,cross_field_share:null}
];
test('header institution and flag scopes govern the seed population with joint membership',()=>{
 assert.deepEqual(filterRows(rows,state,{inst:'TIFR',flag:'out'}).map(r=>r.original_id),['W1']);
 assert.deepEqual(filterRows(rows,state,{inst:'IISc',flag:'in'}).map(r=>r.original_id),['W1','W3']);
 assert.equal(filterRows(rows,state,{inst:'All',flag:'in'}).length,3);
});
test('local search, field, year and pilot filters intersect the header scope',()=>{
 assert.equal(filterRows(rows,{...state,search:'joint',field:'f1',year:'2020',pilot:true},{inst:'TIFR',flag:'out'}).length,1);
 assert.equal(filterRows(rows,{...state,institution:'Joint'},{inst:'IISc',flag:'out'}).length,1);
 assert.equal(filterRows(rows,{...state,search:'Flagged'},{inst:'TIFR',flag:'out'}).length,0);
});
test('unknown-field and partial query states are explicit filters',()=>{
 assert.deepEqual(filterRows(rows,{...state,field:'Unknown',coverage:'partial'}).map(r=>r.original_id),['W3']);
 assert.deepEqual(filterRows(rows,{...state,coverage:'complete'}).map(r=>r.original_id),['W1','W2']);
});
test('numeric share sorting keeps unknowns last and uses raw precision',()=>{
 const rs=filterRows(rows,{...state,sort:'share'});
 assert.equal(rs[0].cross_field_share,0.123456789);assert.ok(rs.slice(1).every(r=>r.cross_field_share==null));
});
test('CSV includes every filtered row, precision, escaped quotes and empty headers',()=>{
 const rs=filterRows(rows,state,{inst:'All',flag:'out'});
 const csv=csvText(['original_id','cross_field_share'],rs);
 assert.ok(csv.includes('0.123456789'));assert.equal(csv.trim().split('\r\n').length,3);
 assert.equal(csvText(['title'],[{title:'A "quote", B'}]),'\ufeff"title"\r\n"A ""quote"", B"\r\n');
 assert.equal(csvText(['id','share'],[]),'\ufeff"id","share"\r\n');
});
test('unknown seed author flag cannot silently enter excluded population',()=>{
 assert.equal(eligible({...rows[0],authors_gt_12:undefined},{inst:'All',flag:'out'}),false);
});

test('headline denominator reconciles unknown citing fields and additional unknown seed fields without double counting',()=>{
 const s={direct_edges:807678,known_field_citers:806339,unknown_field_citers:1339,cross_numerator:184420,cross_denominator:806331};
 assert.deepEqual(denominatorBreakdown(s),{valid:true,total:807678,unknownCiter:1339,unknownSeed:8,classifiable:806331,cross:184420});
 assert.equal((100*s.cross_numerator/s.cross_denominator).toFixed(2),'22.87');
 assert.equal(denominatorBreakdown({...s,cross_denominator:806340}).valid,false);
 assert.equal(denominatorBreakdown({...s,direct_edges:807679}).valid,false);
});

test('teaching example distinguishes stored citation direction, displayed direction and G2; walkthrough uses scoped IDs',()=>{
 const text=learningMarkup('if-');
 for(const phrase of ['B → A','A → B → D','Illustrative example','2 links but 1 unique citing work','unknown field','not higher quality']){
  assert.ok(text.includes(phrase),phrase);
 }
 assert.equal((text.match(/<li>/g)||[]).length,9);
 assert.ok(text.includes('id="if-walkExample"'));
 assert.ok(!text.includes('807678'),'Frozen totals must come from the scope payload, not teaching markup');
});
