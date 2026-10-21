# Primary-source literature notes for workload coverage

Accessed 2026-10-13. These notes distinguish published observations from implications for this simulator. No external trace was downloaded or replayed. Literature does not calibrate this project's numeric ranges.

## Operating-system scheduling foundations

OSTEP Chapter 7 deliberately begins with simplifying assumptions: equal job lengths, simultaneous arrivals, completion without preemption, no I/O, and known runtimes. It then relaxes those assumptions. Its examples show why length heterogeneity and later arrivals matter, why I/O blocking permits CPU overlap, and why response time and turnaround favor different policies. RR quantum choice trades response against context-switch overhead. These support testing such dimensions; the textbook examples are not measurements validating AutoScheduler's ranges. [Arpaci-Dusseau and Arpaci-Dusseau, *Scheduling: Introduction*, §§7.1, 7.4–7.9](https://pages.cs.wisc.edu/~remzi/OSTEP/cpu-sched.pdf).

OSTEP Chapter 8 distinguishes frequent CPU relinquishment in interactive jobs from long CPU-intensive execution. It explicitly discusses starvation under sustained competing interactive demand and a process changing from CPU-bound to interactive behavior. Thus a stationary mixture of process types does not exhaust the behavior changes relevant to adaptive scheduling. Starvation remains an outcome of the policy and competition, rather than a probability distribution attached to a workload name. [*The Multi-Level Feedback Queue*, §§8.1–8.3](https://pages.cs.wisc.edu/~remzi/OSTEP/cpu-sched-mlfq.pdf).

## Measured CPU lifetimes and arrival dependence

Harchol-Balter and Downey measured historical academic UNIX workstation workloads and found heavy-tailed, Pareto-like **total process CPU lifetimes**. Their terminology defines lifetime as total CPU time from start to completion; their model excludes I/O. They also report serial correlation and greater burstiness than Poisson arrivals in their observed trace. This is direct empirical motivation for evaluation beyond bounded uniform demands and independent increments. It is not evidence that individual CPU bursts in present-day applications follow the same distribution, nor that one Pareto parameter should be universally adopted. [Harchol-Balter and Downey, *Exploiting Process Lifetime Distributions for Dynamic Load Balancing*, ACM TOCS 15(3), 1997, §§1.2, 1.4.2, 2.1](https://www.cs.cmu.edu/~harchol/Papers/TOCS.pdf).

Feitelson's workload-modeling text treats heavy tails, correlations, temporal dependence, and hierarchical generative models as separate topics. **Assessment implication:** marginal per-feature diversity alone cannot establish coverage of dependence or temporal structure. This is a methodological implication, not an empirical claim about this project's generator. [Author's book page and table of contents, *Workload Modeling for Computer Systems Performance Evaluation*](https://www.cs.huji.ac.il/w~feit/wlmod/).

## Google Cluster Workload Traces: useful but a different abstraction

The official 2019 release covers eight Borg cells in May 2019. It focuses on resource requests and usage, adds CPU-usage histograms over five-minute periods, and explicitly excludes access patterns to storage systems and other services. [Google, *ClusterData 2019 traces*](https://github.com/google/cluster-data/blob/master/ClusterData2019.md).

The official schema records cluster scheduling events and instance resource-usage summaries, typically over 300-second windows; CPU quantities are normalized. It distinguishes latency-sensitivity scheduling class from cluster scheduling priority. It does not provide the ordered per-process runnable/blocked CPU/I/O burst stream required by this simulator. **Inference from the schema:** aggregate CPU usage cannot uniquely reconstruct that stream. Deriving synthetic bursts would require stated assumptions, unit conversion, and validation; cluster SCHEDULE/EVICT events cannot simply be treated as OS CPU dispatch/preemption events. [Google, v3 protobuf schema, `EventType`, `LatencySensitivity`, `Resources`, and `InstanceUsage`](https://raw.githubusercontent.com/google/cluster-data/master/clusterdata_trace_format_v3.proto).

## Parallel Workloads Archive: job-level scheduling data

The archive supplies raw logs and workload models for evaluating parallel systems and their schedulers. It is useful evidence of real job submission and demand heterogeneity, but its target is parallel-system scheduling. [Parallel Workloads Archive, official overview](https://www.cs.huji.ac.il/labs/parallel/workload/).

SWF defines submit time, queue wait, wall-clock runtime, allocated processors, and average CPU time per processor, plus user/application/queue and optional dependency/think-time fields. It explicitly distinguishes wall-clock runtime from aggregate CPU use. No field specifies an alternating CPU/I/O burst sequence. **Inference:** wall-clock job runtime is not one uninterrupted CPU burst, and combining a parallel job's processors into one simulated process changes the execution model. Logs also reflect the original scheduler's decisions; recorded waits and starts are outcomes, not scheduler-independent arrivals or service demands. Trace adaptation should preserve these distinctions and disclose missing-field handling. [Parallel Workloads Archive, *Standard Workload Format*, data fields 2–6 and 15–18](https://www.cs.huji.ac.il/labs/parallel/workload/swf.html).

## Claims this literature does not justify

- None of the consulted sources validates this project's particular integer CPU/I/O ranges, default process counts, uniform priorities 1–5, or equal mixed-profile selection probabilities. The current generator defines these directly and supplies no calibration reference: [`autoscheduler/workloads.py`](../../autoscheduler/workloads.py).
- CPU-bound, I/O-bound, and interactive categories have a sound qualitative foundation. Their names do not establish empirical realism, time-unit calibration, or population prevalence.
- Poisson/exponential arrivals are useful controlled comparison cases, not a universal description of real arrivals; the historical UNIX study above provides a specific counterexample.
- A bounded demand distribution can test large-demand outliers over a chosen finite range without being mathematically heavy-tailed. Describe any truncated diagnostic accurately.
- No consulted source supports equating simulator accuracy, same-generator holdout performance, or successful trace conversion with generalization to real OS scheduling. That would require additional empirical validation.

## Practical recommendation supported by these sources

Keep the existing five profiles as transparent synthetic baselines. Before trace adaptation, add evaluation-only tests that independently vary arrival concentration/dependence, process count/load, demand heterogeneity and outliers, CPU/I/O behavior, and behavior changes over time. Test quantum and switching-cost sensitivity explicitly. For future trace work, prefer runnable/blocked transition data at OS scheduling granularity; use cluster/SWF traces only with an explicit, validated abstraction mapping. These are recommendations inferred from the abstraction gaps and scheduling mechanisms above, not measured improvements in this project.
