# Computer-use selector

The default backend is Jev. The opt-in behavior explicitly permits sending the
bounded snapshot to TypeSafe; standalone calls require external-state consent.
Laya remains an explicit experimental backend.

When the next UI step is selecting an observed control, use `jev_cua` with a
sanitized, scoped snapshot from the host browser/computer tool. Snapshot fields:
`surface_id`, `revision`, `text`, and `elements`. Each element has a unique `id`,
`label`, `role`, and `operations` (CLICK, TYPE_TEXT, or SELECT). SELECT also needs
an `options` map of observed option IDs to labels. Mark sensitive controls with
`sensitive: true`; remove private text from the goal and summary yourself.

This tool returns a proposal, never executes a computer action. Reobserve before
acting, check the snapshot hash/expiry, map IDs only to the host's current native
references, and use the normal approved computer tool. Unsupported or uncertain
steps return to reasoning. TYPE_TEXT requires the host to generate and check the
text. DONE requires independent verification of every goal requirement.

A proposal needs the top choice at 0.90 or more with a 0.20 lead. The selector never
proposes a target whose label names an irreversible or external change (buy, pay,
delete, remove, send, submit, publish, post, transfer, merge, deploy and similar),
even when the goal asks for it: it returns `side_effect_requires_confirmation`.
Carry out such steps through the host's normal, approved computer tool with the
user's confirmation, never by lowering the gate.

For multi-step automation without a generative call between clicks, use the
Python `jev_cua.run` host integration described in `docs/JEV-CUA.md`. Merely
calling this selector from a reasoning loop does not establish savings.
