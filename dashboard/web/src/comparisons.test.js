import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {compareMetric,metrics} from './comparisons.js';

const source=JSON.parse(readFileSync(new URL('../../../results/real_source_dynamic_review_20261020/dashboard.json',import.meta.url)));
const v5=source.external.metrics['Dynamic v5'],baseline=source.external.metrics['Tuned MLFQ'];
test('verified waiting advantage rounds to 49.5 percent',()=>{
  const c=compareMetric(v5.avg_waiting_ms,baseline.avg_waiting_ms);
  assert.equal(c.winner,'v5');assert.equal(c.percent.toFixed(1),'49.5');
});
test('all reported metric winners and percentages follow direction',()=>{
  for(const m of metrics){
    const c=compareMetric(v5[m.key],baseline[m.key],m.higher);
    const a=v5[m.key],b=baseline[m.key];
    if(a===b){assert.equal(c.status,'tie');continue;}
    assert.equal(c.winner,(m.higher?a>b:a<b)?'v5':'baseline');
    assert.equal(c.percent,Math.abs(a-b)/Math.abs(c.winner==='v5'?b:a)*100);
  }
});
test('score and both response metrics remain MLFQ wins',()=>{
  for(const key of ['weighted_score','avg_response_ms','p95_response_ms']) assert.equal(compareMetric(v5[key],baseline[key]).winner,'baseline');
});
test('higher-is-better, missing and zero references are handled honestly',()=>{
  assert.equal(compareMetric(2,1,true).percent,100);
  assert.equal(compareMetric(2,0,true).percent,null);
  assert.equal(compareMetric(null,1).status,'unmeasured');
  assert.equal(compareMetric(0,0).status,'tie');
});
