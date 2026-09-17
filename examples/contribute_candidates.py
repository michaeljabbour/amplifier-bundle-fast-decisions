"""Illustrative trusted extension. No tool is executed by this file.

Call register() from your own mounted module after supplying a validator that
rechecks the actual application's current permissions, objects and revisions.
The example tool name is a placeholder for a tool YOU mount and allowlist.
"""
from amplifier_fast_decisions.contracts import Candidate


def register(coordinator, application_state, validate_application_action):
    def candidates():
        # This state must be owned by your application, not model-generated text.
        artifact = application_state.current_readable_artifact()
        if artifact is None:
            return []
        return [Candidate(
            id="inspect_current_artifact",
            label="Inspect the current prepared artifact",
            tool="my_read_only_artifact_tool",
            arguments={"artifact_id": artifact.id},
            rationale="Retrieve the evidence needed for the current task",
            origin="trusted-application-module",
            revision=str(artifact.revision),
        )]

    coordinator.register_contributor("fast_decisions.candidates", "my-artifact-reader", candidates)
    coordinator.register_capability("fast_decisions.validate_candidate", validate_application_action)
