// Every row belongs to the same completed Azure cohort; ties are not wins.
export const metrics = [
  {key:'avg_waiting_ms',label:'Average waiting time',unit:'ms',explanation:'Less time waiting in the ready queue; first-response delay is measured separately.'},
  {key:'weighted_score',label:'Weighted scheduling score',unit:'',explanation:'The combined scheduling objective remains better under tuned MLFQ.'},
  {key:'avg_response_ms',label:'Average response time',unit:'ms',explanation:'Tuned MLFQ provides earlier first CPU service.'},
  {key:'p95_response_ms',label:'Mean workload P95 response',unit:'ms',explanation:'Tuned MLFQ avoids the long first-service tails caused by policy excursions.'},
  {key:'avg_turnaround_ms',label:'Average turnaround time',unit:'ms',explanation:'Lower completion delay accompanies the waiting-time improvement.'},
  {key:'starvation',label:'Starvation diagnostic',unit:'jobs / workload',explanation:'Fewer jobs exceed waiting time > 3 × proxy CPU demand; this is a simulator diagnostic.'},
  {key:'context_switches',label:'PID context switches',unit:'per workload',explanation:'Fewer PID transitions were recorded; this does not measure Linux overhead.'},
  {key:'throughput_jobs_per_ms',label:'Throughput',unit:'jobs / ms',higher:true,explanation:'Completed jobs per simulated makespan.'},
  {key:'utilization_fraction',label:'CPU utilization',unit:'fraction',higher:true,explanation:'Busy fraction of the simulated window.'},
];

export function compareMetric(v5,baseline,higher=false) {
  if(!Number.isFinite(v5)||!Number.isFinite(baseline)) return {winner:null,percent:null,status:'unmeasured'};
  const delta=(higher?1:-1)*(v5-baseline);
  if(Math.abs(delta)<=Math.max(1,Math.abs(v5),Math.abs(baseline))*1e-12) return {winner:null,percent:0,status:'tie'};
  const winner=delta>0?'v5':'baseline';
  const reference=winner==='v5'?Math.abs(baseline):Math.abs(v5);
  return {winner,percent:reference?Math.abs(v5-baseline)/reference*100:null,status:'compared'};
}
