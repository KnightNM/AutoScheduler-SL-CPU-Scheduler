# Locked Evaluation Gate Report

**Status: INSUFFICIENT_DATA**

- Fixed comparator: `MLFQ` (chosen only from validation data)
- Locked-test traces: 2 / 60 required
- Model cost: `0.000000`; comparator cost: `0.000000`
- Improvement: `None`; gate: `False`
- Paired model-minus-comparator 95% CI: `[0.000000, 0.000000]`; gate: `False`
- Decision P99: `0.418375 ms`; gate: `True`
- Fairness gate: `True`; details: `{'passes': True, 'selected_mean_starvation_count': 0.0, 'comparator_mean_starvation_count': 0.0, 'selected_mean_post_io_max_response_time': 0.0, 'comparator_mean_post_io_max_response_time': 0.0}`

This report is an offline replay prototype. It cannot authorize a scheduler deployment or support a real-kernel performance claim.
