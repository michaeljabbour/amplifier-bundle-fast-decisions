# Batch 2 (replicate)

Launched as a reversed-order check (`--cells orch-default-opus,plain-opus,orch-default,plain-sonnet,plain`), but
`evals/run.py` runs cells in `cells.yaml` declared order, so it ran in the same order as batch 1 (plain first,
orch-default-opus last; about 10 minutes apart). It is therefore a replicate run immediately after batch 1 (started 03:17:44 UTC, one minute after batch 1 ended),
not an order check. Within-batch time-of-run drift remains untested; the two batches agree:
orch-default vs plain 0.559x/0.484x (batch 1) and 0.574x/0.460x (batch 2); orch-default-opus vs plain-opus
0.825x/0.895x and 0.757x/0.822x.
