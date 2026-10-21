# Azure v5: fixed prediction-only model comparison

Saved Azure-proxy score-delta labels; no new labels, scheduler changes or simulations. Same 18/6/6 provenance groups and 216/72/72 states. Test groups were previously inspected; final 73-group holdout untouched.
All candidates retain 19 ordered observed features and six ordered raw cost outputs. Only Ridge scales inputs, using training-only StandardScaler. No target scaling, masking, clipping or imputation. Aggregation matches historical pooled decision-action R²; constant per-output R² is undefined.
Validation selection requires both MAE and RMSE below the training-mean dummy; rank by average relative error. Each new candidate has one fixed configuration (protocol.json).

Model | Split | MAE | RMSE | R²
---|---|---:|---:|---:
existing_tree | train | 0.000434939047 | 0.00341546289 | 0.112991778
existing_tree | validation | 0.000983039559 | 0.00804962295 | -0.159357876
existing_tree | test | 0.000245306932 | 0.00112175962 | -9.42541869
regularized_tree | train | 0.000426544106 | 0.00357749206 | 0.0268363905
regularized_tree | validation | 0.000804531867 | 0.00761099063 | -0.0364510937
regularized_tree | test | Not evaluated | Not evaluated | Not evaluated
ridge | train | 0.000381656412 | 0.00356414174 | 0.0340860513
ridge | validation | 0.00084810431 | 0.00817960659 | -0.197102318
ridge | test | Not evaluated | Not evaluated | Not evaluated
random_forest | train | 0.000411518412 | 0.00349904859 | 0.0690455083
random_forest | validation | 0.000765401678 | 0.0072674275 | 0.0550086022
random_forest | test | Not evaluated | Not evaluated | Not evaluated
dummy_mean | train | 0.000348392496 | 0.00362509557 | 0.000765488273
dummy_mean | validation | 0.000677957387 | 0.00748435399 | -0.00224772654
dummy_mean | test | 9.67462455e-05 | 0.000355869491 | -0.0492413843

Selected: none; no candidate beats dummy on both validation errors. Existing-tree and dummy test metrics are historical; only the selected frozen model received new test predictions.
Target distributions, outlier provenance, per-output errors, nonconstant-head metrics and error shares are saved in target_diagnostics.json/results.json. R² is supporting evidence, never classification accuracy. No scheduling-performance improvement is established.
Original models/artifacts remain unchanged. Any saved candidate is experimental, not promoted.

## Diagnosis
Two outputs are identically zero; FCFS and Priority targets are identical in each split (neutral-priority Azure proxies). Raw six-head errors therefore reflect duplicated rare non-preemptive costs plus trivial zero heads; low MAE alone is not evidence of useful switching.
Existing-tree train: FCFS/Priority supply 99.591% of absolute error and 99.997% of squared error (and pooled R² error numerator).
train: pooled target variance 1.31513851e-05; nonconstant-head near-zero counts FCFS=211, Round Robin=211, Priority=211, Priority RR=211.
Existing-tree validation: FCFS/Priority supply 99.738% of absolute error and 100.000% of squared error (and pooled R² error numerator).
validation: pooled target variance 5.58899293e-05; nonconstant-head near-zero counts FCFS=70, Round Robin=70, Priority=70, Priority RR=70.
test: pooled target variance 1.20699676e-07; nonconstant-head near-zero counts FCFS=71, Round Robin=71, Priority=71, Priority RR=71.
Test pooled target variance is 108.96 times smaller than training. Non-preemptive target maximum drops from .073184 (training) / .107650 (validation) to .005049 (test); prediction errors on this much smaller target scale sharply penalize test R². This is distribution/rare-target instability, not feature-order or scaling inconsistency.
The fixed forest improves validation RMSE relative to the existing tree and dummy, but its MAE exceeds the dummy. No candidate meets the preregistered joint MAE/RMSE requirement. Stop: no new test scoring, no candidate artifact saved, no scheduler run or claimed scheduling improvement.
