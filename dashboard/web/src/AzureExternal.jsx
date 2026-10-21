import React, { useState } from 'react';
import { Badge, number, percent, Source } from './ui.jsx';

export function AzureExternal({ result }) {
  const [group,setGroup]=useState('all');
  if(!result) return null;
  const s=result.summary;
  const values=group==='all'?s.policy_means:s.by_stratum[group];
  return <section className="panel"><div className="section-heading"><div><p className="eyebrow">EXTERNAL DATA · SMALL FIXED-SEED PILOT</p><h2>Azure External Evaluation</h2></div><Badge tone="amber">Proxy robustness only</Badge></div>
    <p><strong>{s.completed_workloads} workloads tested</strong> from cleaned Azure Functions 2019. {s.attempted_workloads} attempted; {s.excluded_workloads.length} runtime exclusions. {s.completed_workloads-s.processes_over_100} workloads have at most 100 processes; {s.processes_over_100} larger exceptions retain their original 2,000 processes.</p>
    {s.excluded_workloads.length>0&&<p className="subtle">Coverage gap: {s.excluded_workloads.map(w=>`${w.workload_id} (${w.stratum.replaceAll('_',' ')}) — ${w.reason}`).join('; ')}. No completed peak-snapshot result is claimed.</p>}
    <p>Compared: {Object.keys(s.policy_means).map(n=>n==='Dynamic v5'?'Dynamic ML (v5)':n).join(', ')}. ML inference: <strong>{s.ml_inference_evaluated?'original v5 cost model evaluated':'not evaluated'}</strong>. External algorithm-selection accuracy is unavailable; the offline classifier has no fitted binary, and dynamic excursion actions are not whole-workload static labels.</p>
    <label className="cohort-picker">Azure pilot stratum<select value={group} onChange={e=>setGroup(e.target.value)}><option value="all">All completed workloads · descriptive unweighted mean</option>{Object.keys(s.by_stratum).map(name=><option key={name} value={name}>{name.replaceAll('_',' ')} · {s.completed_strata_counts[name]} workloads</option>)}</select></label>
    <div className="table-scroll"><table><thead><tr><th>Policy</th><th>Weighted score ↓</th><th>Avg. wait ms</th><th>Avg. response ms</th><th>Mean P95 ms</th><th>CPU utilization</th></tr></thead><tbody>{Object.entries(values).map(([name,m])=><tr key={name}><td>{name==='Dynamic v5'?'Dynamic ML (v5)':name}</td><td>{number(m.weighted_score,5)}</td><td>{number(m.avg_waiting_ms)}</td><td>{number(m.avg_response_ms)}</td><td>{number(m.p95_response_ms)}</td><td>{percent(m.utilization_fraction)}</td></tr>)}</tbody></table></div>
    <div className="notice neutral">1 tick = 1 ms. Published daily wall-clock means are CPU-burst proxies; minute-bin arrivals are reconstructed, including conditional-uniform peak snapshots. No measured CPU/I/O demand or real subminute timings are available. Frozen settings were not calibrated to Azure. These results do not validate a real CPU scheduler, imply population-wide rankings, or change historical ML accuracy.</div>
    <p className="subtle">{s.score_scope} {s.aggregation} Cohorts and possible source-hour overlap limit interpretation; no ML superiority or model promotion is claimed.</p><Source>{result.source} · exact selections, settings and provenance: results/azure_external_pilot/REPORT.md</Source>
  </section>;
}
