# Fixed Local Inference Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Build only the verified CPU inference recipe from owned stage evidence,
without caller flags, inherited proxy/cache variables or diagnostic imports.

**Architecture:** Pure launch construction consumes validated bundle evidence and
trusted Windows directory values. The future coordinator owns all launching,
token checks, cancellation and cleanup; this module cannot execute anything.

**Tech Stack:** Python standard library, immutable dataclasses, pathlib, ctypes
only for a separate explicit Windows directory discovery function, pytest.

## Global Constraints

- Fixed Qwen3.5-4B CPU recipe, not a generic process launcher or model service.
- Original files/paths, credentials, URLs, raw prompt/schema/stream text and
  arbitrary executable flags are not accepted. All request inputs are staged.
- No model/process launch, network/API/credential/private input, security settings,
  QML/Golden, main checkout, merge or push. Windows directory queries are read-only.
- Product module imports no scripts/QA/config/Qt. Import has no filesystem/process
  or native discovery side effects. No new third-party dependencies.

## Task 1: Fixed argv and minimal environment

Files: create `src/services/local_ai/inference_launch.py` and
`tests/unit/test_local_inference_launch.py`. Do not change native runner behavior.

Stable pure API:

```python
@dataclass(frozen=True)
class TrustedWindowsPaths:
    system_root: Path
    local_app_data: Path

@dataclass(frozen=True)
class LocalLaunchSpec:
    executable: Path  # repr=False
    cwd: Path         # repr=False
    arguments: tuple[str, ...]  # repr=False
    environment: Mapping[str, str]  # frozen MappingProxyType, repr=False
    recipe_version: str

def discover_windows_paths() -> TrustedWindowsPaths: ...
def build_launch(evidence: BundleEvidence, *, model_name: str,
                 projector_name: str | None, visual_names: tuple[str, ...],
                 windows_paths: TrustedWindowsPaths) -> LocalLaunchSpec: ...
```

The coordinator alone passes catalog-derived model/projector basenames; this is
not a UI API. Validate those names and every selected member against the evidence
set (case-insensitive duplicates prohibited); paths must be exactly the evidence
directory joined with that safe basename. Require prompt.txt/schema.json, one
model, 0 or1 projector consistent with visuals, and ordered contiguous visual_00
through visual_07 names with supported image suffixes. Reject unexpected/missing
selected entrypoint, cross-directory path, false type/bool masquerading as count,
duplicate/index/suffix mismatch, comma/NUL/path syntax. No silent sanitizing.

Text entrypoint is `llama-completion.exe`; visual is `llama-mtmd-cli.exe`. The
evidence executable_path must equal the selected required member. Pin recipe
version `qwen35-cpu-b10885-v1`; use exactly the following measured flag order:

```python
common = (
    "--offline", "-m", staged_model_path, "-f", "prompt.txt",
    "--json-schema-file", "schema.json", "-n", "1024", "-c", "8192",
    "-t", "4", "-tb", "4", "--device", "none", "--no-op-offload",
    "--no-kv-offload", "--flash-attn", "off", "--no-warmup", "--seed", "1",
    "--temp", "0", "--log-colors", "off", "--verbosity", "1",
)
text_extra = (
    "--conversation", "--single-turn", "--jinja", "--reasoning", "off",
    "--no-display-prompt", "--simple-io",
)
visual_extra = (
    "--mmproj", staged_projector_path, "--mmproj-device", "none",
    "--no-mmproj-offload", "--image", ",".join(visual_names),
    "--image-max-tokens", "1024",
)
```

Only six environment keys: SystemRoot/WINDIR from Windows directory discovery,
PATH = owned stage + System32, TEMP/TMP = owned stage, LOCALAPPDATA = OS-known user
local AppData. Assert the exact set SystemRoot, WINDIR, PATH, TEMP, TMP,
LOCALAPPDATA. Do not copy os.environ, PATH/proxy/HF/model
cache/CUDA/user overrides or QA paths. Explicit discovery uses typed Windows
directory/known-folder APIs and frees API-owned buffers, never an env-var fallback.
Reject missing/nonabsolute/UNC/device/NUL/semicolon/reparse directory values with
fixed errors; pure builder performs string/structure checks without disk I/O.
Discovery performs filesystem/type checks and no directory creation or ACL change.
No package writable-cache exception is introduced; actual compatibility/privacy of
LOCALAPPDATA remains for the composed AppContainer native Gate.

Check the generated argv quoting and environment UTF16 sizes before return:
command line <32767 UTF16 units, environment <=32767 units, no duplicate
case-insensitive environment keys. Stage parent <=180 characters follows native
staging; no developer checkout/install path can enter defaults or output.

- [ ] RED exact recipe fixtures for text, single image and8mixed supported image
  suffixes; missing resource/entrypoint, malformed evidence/names/paths, env poison,
  mutation attempt on returned environment and size bound tests.
- [ ] Implement minimal pure builder and explicit typed discovery, fixed errors
  and repr privacy. Tests use fake native APIs for error/freeing paths; one actual
  read-only Windows discovery test may verify existing directories, never a model.
- [ ] Run new tests plus native import and contained inference fixture suites to
  compare exact recipe parity. No probing/launching binary is allowed in this task.
- [ ] Report RED/GREEN/commands/files to
  `.superpowers/sdd/local-inference-launch-report.md`, diff check and scoped commit.
  This is launch metadata only, not model readiness or outbound-denial evidence.
