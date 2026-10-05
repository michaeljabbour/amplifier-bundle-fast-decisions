# Round 1 external review (reconstructed)

> **Reconstructed from the authors' response.** The original review text is not in this repository. This file
> restates the reviewer's points as listed in Appendix C ("Response to review") of the report
> `docs/papers/2026-10-02-paired-measurement/paired-measurement.pdf`. Wording is the authors', not the reviewer's.

Reviewed: the 48-page draft of "Measured, not estimated: what routing an agent to a cheaper model actually costs".

1. "Preregistered" overstates what was fixed in advance: the estimator, the pair filter and the definition of a
   savings claim were fixed after the data; "all 4 hypotheses confirmed" depends on that scoping.
2. The headline 44 % saving is a geometric mean of per-pair cost ratios; the actual spend reduction is smaller and
   is not reported next to it.
3. The test split has no docs scenario; claims about docs (and the Opus docs exception) rest on training data.
   (The reviewer also stated docs was the largest Fable saving; review is.)
4. The primary pair filter conditions on a post-treatment outcome; the Fable sticky quality margin is thin.
5. The largest savings coincide with the largest quality losses (knowledge family); the savings and quality tables
   are not cross-referenced.
6. The tools normalization looks about ten times too small (about $260 expected vs $15.37 reported) and is applied
   asymmetrically. (The size premise did not hold; see the response.)
7. The sticky arm is not "mostly plain Sonnet": it made fewer requests than a plain-Sonnet / plain-host mix would.
8. Two different turn counts (11,576 and 11,588) are not reconciled.
9. Several subsections in the exploratory section are empty headings.
10. The Opus A/A bias is attributed to launch order without evidence.
11. Sticky-on-Sonnet was never compared with plain Sonnet (it turned out to differ in reasoning effort).

Responses: Appendix C of the report. Verification of every point against the evidence before the response was
written: `verification-round1.md` and `verification-scripts/`.
