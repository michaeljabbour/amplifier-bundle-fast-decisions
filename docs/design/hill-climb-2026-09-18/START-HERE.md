# Start the Fast Decisions improvement campaign

**Paste [PROMPT.txt](PROMPT.txt) into a new Amplifier session.** It tells Amplifier to implement and run the campaign, beginning with the existing root-cause evidence and preserving your dirty checkout.

- [SPEC.md](SPEC.md): architecture, ordered experiments, measurement, quality gates, durable history, Observatory behavior and release criteria.
- [campaign.json](campaign.json): proposed initial limits of **12 hours / $150 total campaign spend / eight candidates**. Edit before launching if you want different limits. This file is not an existing Amplifier recipe.
- [PROMPT.txt](PROMPT.txt): the complete launch instruction with local source/evidence paths.
- [experiment-template.json](experiment-template.json): a concrete first experiment record, with hypotheses, controls, falsification criteria and unrun gates.

The goal is a substantial improvement in completed work, with a 20% first milestone and a 2× speed / 50% cost stretch target. These are objectives to test, not promised results. The warm full decision boundary must target p95 below 500 ms.

This package contains the specification only. No optimization campaign, paid hosting, installation, merge or new benchmark was started when it was written. The launch creates its own durable campaign directory and resumes from that directory on later runs.

The launch prompt uses absolute paths on this Mac. Keep the repository copy in place, or update those paths if transferring this package elsewhere. The Downloads copy is a convenience snapshot; compare hashes in `FILES.sha256` before assuming copies still match.

The existing six-run evidence is at `~/dev/afast-forge-evidence-20260918-02/`. Its improvements were modest, and two runs timed out. The spec addresses that directly by prioritizing state retention, useful action batches and active model/effort routing, then testing the resulting complete tasks independently.
