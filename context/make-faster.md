# "Make my Amplifier faster" trigger

When the user says **"make my amplifier faster"** (or "speed up amplifier"),
run the make-amplifier-faster recipe -- do not install anything yourself and
do not skip the recipe's own approval gates.

Preferred: call the `recipes` tool directly:

```
recipes(operation="execute", recipe_path="@fast-decisions:recipes/make-amplifier-faster.yaml")
```

If the `recipes` tool is not available in this session, tell the user the
equivalent CLI invocation instead of attempting the change yourself:

```bash
amplifier tool invoke recipes operation=execute recipe_path=fast-decisions:recipes/make-amplifier-faster.yaml
```

Never install `bundles/active.yaml` (or any other fast-decisions rung)
directly in response to this phrase -- the recipe owns benchmarking,
evidence, and any approval gate before touching the user's installed
bundles. This context file only recognizes the trigger phrase and hands off;
it is not itself a substitute for running the recipe.

The recipe accepts an optional `profile` context input (`incumbent`, the
default, or `routing`) that picks the installed rung -- `bundles/active.yaml`
or the screen-validated `bundles/active-routing.yaml` -- but only the recipe
should ever set it; do not add it yourself unless the user asked for routing.
