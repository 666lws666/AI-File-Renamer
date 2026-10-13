# Product-native runtime foundation promotion

> One mechanical implementation task, followed by an independent scoped review.

**Goal:** Product code can use the already-tested native isolation, process and
owned-staging foundations without importing diagnostic QA modules or duplicating
their native implementation. This task changes module ownership, not security
policy or process behavior.

## Global constraints

- Preserve all verified native behavior, validation, resource bounds, exception
  classes, ownership, token checks, kill-on-close Job, cleanup ordering and
  fail-closed semantics. No new fallback or platform bypass.
- No real model launch, network/API/key/credential/private file/security-setting
  change, QML/Golden update, main-checkout edit, merge or push.
- Keep exactly one implementation of each native component. Diagnostic scripts
  remain compatible import shims, not copies or runtime source-code loaders.
- Product modules cannot import `scripts.*`, QA paths, test helpers, GUI or
  application configuration. Package import itself must not launch/create
  profiles, stages, files or processes.
- No test skips, weakened assertions or added tolerance. Existing native tests
  may change module/import-location plumbing only as required by relocation.

## Task 1: Move native foundations and preserve diagnostic imports

Mapping (retain original function/class names):

| Existing file | Single product implementation |
| --- | --- |
| scripts/local_probe_security.py | src/services/local_ai/native/security.py |
| scripts/local_probe_profile.py | src/services/local_ai/native/profile.py |
| scripts/local_probe_process.py | src/services/local_ai/native/process.py |
| scripts/local_probe_exemptions.py | src/services/local_ai/native/exemptions.py |
| scripts/local_probe_stage.py | src/services/local_ai/native/stage.py |
| scripts/local_model_stage.py | src/services/local_ai/native/model_stage.py |

Also create a side-effect-free package `native/__init__.py` and
`tests/unit/test_local_native_imports.py`.

Do not rewrite the native algorithms, split internal classes or opportunistically
clean up code. Move the source, adjust only intra-package imports, then turn the
old module into a thin module-identity alias to its product implementation. A
normal import through the old or new path must obtain the same module/class
objects, including private dependency-injection seams. Do not use `exec`, reading
another .py at runtime, copying globals wholesale, or two independent native
module instances to fake this compatibility.

Existing tests for security/profile/process/exemptions currently load modules by
file location. Update their MODULE/PATH constants to the new product path so they
exercise the real implementation; ordinary old-path imports continue exercising
the compatibility alias. Adjust any supervisor subprocess's repo-root derivation
that relied on the old scripts directory depth. Do not change tested outcomes,
native failure injection, resource-cleanup assertions or platform restrictions.

Allowed existing test files are `tests/unit/test_local_probe_security.py`,
`test_local_probe_profile.py`, `test_local_probe_process.py`,
`test_local_probe_exemptions.py`, `test_local_probe_stage.py`,
`test_local_model_stage.py` and `test_contained_inference_probe.py`; only import
plumbing changes justified by relocation. No diagnostic orchestrator behavior,
product startup/packaging or resource manager changes belong in this task.

### RED/GREEN sequence

1. Add tests requiring product imports to exist and old/new module objects and
   public types to be identical; run RED before creating the package.
2. Move implementations and update their intra-package imports; install thin
   compatibility aliases. Do not copy implementations and leave originals alive.
3. Assert package import in a clean child has no `scripts.*`/QA modules loaded;
   no constructors/API calls are allowed at package import. Assert source imports
   of product native modules do not depend on scripts/test/QA/config/UI. Static
   import checks complement, not replace, the existing real native test suites.
4. Run the existing security/profile/process/exemptions/stage/model-stage/hello/
   appcontainer probe/access/contained-inference and new import suites with the
   project Python. These execute only harmless temporary fixtures or mocked
   native boundaries, never the model or new administrator/security actions.
5. Report exact RED/GREEN outputs, file list and semantic diff justification.
   Confirm one-copy implementation and `git diff --check`. Commit only approved
   source/tests in a new commit, no amend.

Report to `.superpowers/sdd/native-runtime-promotion-report.md`. Root will later
run production-composed real inference after protocol and coordinator tasks;
this import promotion alone is not a new runtime or privacy acceptance.
