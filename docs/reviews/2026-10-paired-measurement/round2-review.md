# Round 2 external review (reconstructed)

> **Reconstructed from the authors' response.** The original review text is not in this repository. This file
> restates the reviewer's round-2 items as listed in Appendix C ("Round 2") of the report. Wording is the authors'.

Reviewed: the 57-page revision (on `main`). Recommendation: accept with minor revisions.

- **R1 (substantive): effort confound on the primary endpoint.** The anchors ran at the provider default effort and
  routed Sonnet at medium. State the anchor's effort, tabulate main-request effort by host x arm x model, add a
  limitation with the bias direction (optimistic on Fable, conservative on Opus) and an explicitly labelled
  extrapolation from the Sonnet follow-up; qualify the Fable recommendation (host-at-medium not measured); describe
  the sticky-on-host result as an indication of bundle overhead, not a finding.
- **R2:** add confidence intervals to the Fable sticky by-task-type results; three task types fail the quality
  margin; the earlier rank-correlation argument ("family effect, not a general rule") is an underpowered test.
- **R3:** publish the cross-arm (shared-prefix) read volume and say exactly what the foreign-read audit tests.
- **R4:** the 32,100-token normalization allowance is below the median first-request static write; quantify the
  residual and its effect on the ratios; explain the sessions with very large first writes.
- **R5:** state that the medium arm's default-effort requests are all background requests.
- **R6:** label the Sonnet effort follow-up "preregistered, provenance-limited".
- **R7:** describe the quality instrument: what the checks assert, how they were validated, discrimination, difficulty
  by family, examples, and the correlation of turn-pass with the final hidden tests.
- **R8:** say plainly that the evidence does not establish the decision-judge machinery's value; acknowledge
  multiplicity and the 23-scenario confirmatory basis.

The reviewer also corrected his own round-2 reproduction of the $15.37 tools-normalization total.

Responses: Appendix C ("Round 2") of the report. R1 was later answered with a measurement (the Fable effort
follow-up, `docs/evidence/2026-10-06-effort-control-fable/`).
