import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulation } from './Simulation.jsx';
import { Intelligence, Review } from './Research.jsx';
import { api, Badge, ErrorNotice } from './ui.jsx';
import './style.css';

const pages = [ ['overview', 'Overview', '01'], ['simulation', 'Scheduling lab', '02'], ['intelligence', 'ML intelligence', '03'], ['review', 'Research & review', '04'] ];

function Overview({ data, navigate }) {
  return <>
    <div className="hero"><div><p className="eyebrow">CPU SCHEDULING · EXPLAINED THROUGH EXECUTION</p><h1>One CPU.<br/>Many possibilities.</h1><p className="lead">Explore how scheduling policies share processor time—and where machine learning helps, or falls short.</p><button className="primary" onClick={() => navigate('simulation')}>Open the scheduling lab <span>↗</span></button><p className="subtle">Small, deterministic workloads. Real simulator output.</p></div>
      <div className="hero-visual" aria-label="Conceptual single CPU architecture"><div className="visual-caption">THE SCHEDULING PROBLEM</div><div className="job-stream"><span>P1</span><span>P2</span><span>P3</span><span>P4</span></div><div className="connector">↓</div><div className="cpu"><span className="cpu-mark">▦</span><strong>SINGLE CPU</strong><small>Who runs next?</small></div><div className="connector">↓</div><div className="tradeoffs"><span>Responsiveness</span><span>Fairness</span><span>Efficiency</span></div><p>Every dispatch is a tradeoff.</p></div></div>
    <div className="section-heading"><div><p className="eyebrow">FROM WORKLOAD TO EVIDENCE</p><h2>The AutoScheduler pipeline</h2></div><Badge>Simulator research</Badge></div>
    <div className="architecture">{[['01','Workload','Arrivals, CPU / I/O bursts, priorities'],['02','Feature extraction','Workload statistics or observed history'],['03','Policy selection','A fixed policy or an ML decision'],['04','Scheduling engine','Shared event-driven Python simulator'],['05','Evaluation','Timing, fairness and acceptance gates']].map(([n,t,d])=><div key={n}><small>{n}</small><h3>{t}</h3><p>{d}</p></div>)}</div>
    <div className="section-heading"><div><p className="eyebrow">THREE DISTINCT TRACKS</p><h2>Same question. Different evidence.</h2></div></div>
    <div className="tracks"><article className="panel"><Badge>Simulation</Badge><h3>Traditional policies</h3><p>FCFS, SJF, SRTF, Round Robin, Priority and Priority RR. MLFQ adds feedback queues and aging.</p><p className="subtle">SJF and SRTF know true burst lengths here. They are oracle references, not deployable predictions.</p></article><article className="panel"><Badge>Offline classifier</Badge><h3>Choose once per workload</h3><p>A decision tree maps workload-level statistics to a scheduling policy. Historical features include declared burst information.</p><p className="subtle">Classification accuracy describes labels; scheduling performance needs its own comparison.</p></article><article className="panel"><Badge>Observed-state controller</Badge><h3>Adapt at safe boundaries</h3><p>Dynamic ML considers observed state, a no-switch action and constrained excursions from MLFQ.</p><p className="subtle">No future arrivals or true remaining CPU time enter realistic dynamic inference.</p></article></div>
    <div className="method"><div><p className="eyebrow">METHODOLOGY</p><h2>Measure the outcome,<br/>not just the prediction.</h2></div><ol><li>Construct or capture workloads and preserve their provenance.</li><li>Separate training and validation groups; keep frozen tests untouched.</li><li>Compare actual scheduling score, response tails and fairness.</li><li>Require all safety gates before promotion. Report negative results.</li></ol></div>
    <div className="notice">AutoScheduler simulates a single CPU. It does not replace the operating system scheduler, and simulator ticks are not Linux latency measurements.</div>
  </>;
}

function App() {
  const initial = pages.some(([id])=>id === location.hash.slice(1)) ? location.hash.slice(1) : 'overview';
  const [page, setPage] = useState(initial), [data, setData] = useState(null), [error, setError] = useState(''), [attempt, setAttempt] = useState(0);
  const [workload, setWorkload] = useState('short_jobs');
  useEffect(() => { const abort = new AbortController(); setError(''); api('/api/catalog',abort.signal).then(setData).catch(e=>{if(e.name!=='AbortError')setError(e.message);}); return ()=>abort.abort(); }, [attempt]);
  useEffect(()=>{ const change=()=>setPage(pages.some(([id])=>id===location.hash.slice(1))?location.hash.slice(1):'overview'); window.addEventListener('hashchange',change); return ()=>window.removeEventListener('hashchange',change); },[]);
  function navigate(id) { setPage(id); location.hash=id; window.scrollTo({top:0,behavior:'instant'}); }
  return <div className="app-shell"><a className="skip-link" href="#content">Skip to content</a><aside className="sidebar"><a href="#overview" className="brand" onClick={()=>navigate('overview')}><span className="brand-icon">▦</span><span>AutoScheduler<small>CPU SCHEDULING LAB</small></span></a><p className="nav-label">WORKSPACE</p><nav aria-label="Main navigation">{pages.map(([id,label,n])=><button key={id} aria-current={page===id?'page':undefined} className={page===id?'selected':''} onClick={()=>navigate(id)}><span>{n}</span>{label}<b>↗</b></button>)}</nav><div className="sidebar-note"><span className="status-dot"/>RESEARCH CHECKPOINT<p>Evidence first.<br/>Performance with safeguards.</p><small>No ML model promoted.</small></div><div className="sidebar-footer">Single CPU · Python simulator<br/>Academic review workspace</div></aside>
    <div className="workspace"><header className="topbar"><span>PROJECT / <strong>{pages.find(([id])=>id===page)?.[1]}</strong></span><span className="connection"><i className={data?'status-dot':'status-dot muted'}/>{data?'Local data connected':'Connecting to local server'}</span></header><main id="content" tabIndex="-1">
      {error ? <><ErrorNotice>{error}</ErrorNotice><button onClick={()=>setAttempt(a=>a+1)}>Retry connection</button></> : !data ? <div className="loading" role="status"><div className="loading-line"/><h1>Preparing the scheduling lab…</h1><p>Reading local metadata and research results.</p></div> : <>
        {page==='overview'&&<Overview data={data} navigate={navigate}/>}
        {page==='simulation'&&<Simulation data={data} workload={workload} setWorkload={setWorkload}/>}
        {page==='intelligence'&&<Intelligence data={data} workload={workload} setWorkload={setWorkload}/>}
        {page==='review'&&<Review data={data}/>}
      </>}
    </main><footer className="footer"><span>AutoScheduler / Research made visible</span><span>Local demo · No external services required</span></footer></div></div>;
}

createRoot(document.getElementById('root')).render(<App/>);
