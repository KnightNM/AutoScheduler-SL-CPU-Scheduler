# Refined Azure evaluation data quality

This run changes selection and derived artifacts only. No extraction, cleaning, scheduler modifications, training or model evaluation was performed. SHA-256 checks prove both original cleaned observation tables unchanged. Original cleaning/inspection/audit files remain historical inputs.

| Existing cleaned table | Original rows | Retained rows | Missing numeric cells | Previously invalid cells blanked | Conflicting-key rows retained |
|---|---:|---:|---:|---:|---:|
| invocation | 618,545 | 618,545 | 0 | 0 | 0 |
| duration | 662,927 | 662,927 | 2 | 24 | 123 |

No genuine duplicate rows or missing-identifier rows were dropped in the original cleaning. This refinement drops no observation records. Original audit: 24 invalid numeric cells across seven duration rows; two missing duration bounds remain missing.

| Existing match eligibility | Invocation rows |
|---|---:|
| ambiguous_duration | 56 |
| invalid_statistics | 7 |
| missing_duration | 8,477 |
| nonpositive_or_missing_mean | 8,083 |
| usable | 601,922 |

Executed validation passed: **True**. Constructed 520,408 valid Process objects in 510 groups. Preserved every original control Process record. Checks include source rows and duration identifiers, original vs sampled minute counts, bounded quotas, distinct sampled ordinals, seeded reconstruction, snapshot exposure, integer milliseconds, positive bursts, neutral priority, absent I/O, and immutable cleaned-table hashes.

Sampling is not cleaning: omitted invocations remain in the original cleaned files. High-volume sampled groups retain their entire original 60-bin source count vectors plus sampled counts and within-minute inclusion fractions. No missing/zero-duration value is fabricated or mapped to a positive CPU time.

## Source interpretation

[Official Microsoft dataset documentation](https://github.com/Azure/AzurePublicDataset/blob/master/AzureFunctionsDataset2019.md) describes wall-clock execution statistics in milliseconds, excluding cold starts. Invocation bins are recorded after execution; percentile columns summarize interval averages, not individual invocation latencies. Released daily means may have lost submillisecond precision, which cannot be recovered here.

The data is CC-BY; retain attribution to Shahrad et al., “Serverless in the Wild,” USENIX ATC 2020. See README and the original extraction manifest for source provenance.

## Limitations

High-hour samples preserve the observed minute shape and quiet bins but attenuate absolute arrival rates. Local snapshots approximate original peak-minute rates only under uniform independent within-minute arrivals; they do not measure subminute bursts. All times are integer milliseconds. Long execution durations remain wall-clock proxies, not CPU demand. No I/O phases, priorities or dependencies are observed. Purposeful selection is not a population probability sample.
