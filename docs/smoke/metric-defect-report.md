# ArtiCheck — toy-artifact-v1-metric_average

Run: `96e841b4f3d7419cb8d363d66a67f220`
Policy: `FixedPlanner`; execution mode: `local`

Verdicts apply only to supplied claims and probe evidence. A successful probe is not full paper reproduction.

| Claim | Verdict | Evidence | Reason |
|---|---|---|---|
| C1 | issue | a86c2fb150b61f8280987dcfc79fbe62e0ff787399cf038b21dfd382f48f2bb4 | Observed 0.8333333333333334; expected 0.7777777777777778 ± 1e-06; result limited to supplied probe |
| C2 | supported | a86c2fb150b61f8280987dcfc79fbe62e0ff787399cf038b21dfd382f48f2bb4 | Train/test overlap: 0 IDs; result limited to supplied probe |
| C3 | supported | a86c2fb150b61f8280987dcfc79fbe62e0ff787399cf038b21dfd382f48f2bb4 | Method steps=100; baseline steps=100; result limited to supplied probe |

Stop reason: complete
Tool calls: 1; model tokens: 0; configured API cost: $0.000000

Cost excludes GPU rental and infrastructure. No trained-model benchmark is claimed.
