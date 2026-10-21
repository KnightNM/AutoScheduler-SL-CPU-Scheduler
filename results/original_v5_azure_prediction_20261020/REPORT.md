# Original v5: saved Azure development labels, inference only

Exact artifact `artifacts/dynamic_v5_20261019/policy_cost/model.joblib`, SHA256 `a8783b65b60aaf381694910affd7e2c2acce4c7c871911b782514d8e37064a64`. Ordered 19 inputs, six outputs, controller configuration and source-model hash verified against existing labeling protocol. Targets retain original feasible-horizon score-delta interpretation and frozen normalization.

72 previously inspected internal-test states, six provenance groups; dummy uses means of 216 training states in 18 disjoint groups. No fitting, simulations, final-holdout evaluation or independent-validation claim.

Original model: MAE 0.012602638, RMSE 0.019537636, pooled R² -3161.553846.

Training-mean dummy: MAE 0.000096746, RMSE 0.000355869, R² -0.049241.

Per-output metrics and source hashes: metrics.json; numerical pairs: predictions.json. Zero-head R² is undefined. These figures belong to original v5, not the Azure-retrained tree.

Tree inspection: only ['Priority'] can be argmin and satisfy the unchanged .005 benefit margin. FCFS wins only the all-zero leaf and is denied by the margin; guards can retain/return MLFQ. No RR/FCFS demo is manufactured.

Azure reconstructed arrivals/wall-clock demand proxies, not measured Linux scheduling. These state trajectories were collected under MLFQ/preemptive exploration, not necessarily the original-model trajectory. No scheduling improvement is inferred.
