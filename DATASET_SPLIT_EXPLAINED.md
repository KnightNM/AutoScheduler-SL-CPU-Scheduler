# Dataset Split Explained

| Item | What it contains | Purpose |
| --- | --- | --- |
| Dataset | Features, scheduler action, and resulting cost for each decision | What models learn and evaluate from |
| Split manifest | Lists of trace IDs assigned to train, validation, or test | Prevents data leakage |
| Training subset | Rows whose trace ID is listed as `train` | Fits model parameters |
| Validation subset | Rows from `validation` traces | Selects model type and settings |
| Test subset | Rows from `test` traces | Final unbiased check |
