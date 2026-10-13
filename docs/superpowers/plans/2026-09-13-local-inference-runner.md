# Bounded Real Local Inference Plan

> For agentic workers: use subagent-driven-development and test-driven-development. The root owns actual model execution and visual/semantic assessment.

**Goal:** Run the approved synthetic corpus through the pinned native Qwen3.5-4B text/vision engine and retain honest per-case runtime, policy and human-review evidence.

**Architecture:** One diagnostic script validates fixed resources and the accepted corpus, prepares only text or bounded still images, constructs a modality-specific constrained response and uses the existing Windows Job runner. Optional named roles prevent duplicate role emissions; a pure converter preserves each generated value/evidence and passes it through the unchanged SmartNamingPolicy. This is not product integration or network isolation.

**Tech Stack:** Existing Python 3.14, Pillow/PyMuPDF/PyAV, pinned llama.cpp b10885, existing media preprocessors and scripts/local_probe_process.py.

## Global Constraints

- Work only in the existing `D:\文件AI-AGENT\.worktrees\ai-smart-naming`, branch `codex/local-privacy-mode`. Starting HEAD `720a01355e3f3c992261d5782474d6cc12bc2333`.
- No product src/QML/config/Provider changes, no real API/Key/Credential Manager, no private inputs, no download, no system security changes, no Golden updates, no merge/push.
- Keep the 5GiB available-memory guard unchanged; check at run_case entry before resource/output work and again immediately before every model launch. Root alone starts actual inference, one process at a time. Tests must inject a fake process function and cannot load model weights.
- Actual input must come only from the eight fixed opaque sources in `tests/screenshots/qa-current/local-privacy/semantic-corpus-v1-reviewed`. Expected/prohibited facts in its manifest are reviewer-only and must never enter prompts/schema/argv.
- Verify manifest SHA256 `CD820442DFFCB12C8C71DAF804C8C88FE87E46A0E4760A68A8E175BA99639D8B`, each chosen source size/hash, all model/projector/archive sizes/hashes, and every extracted runtime file against the pinned archive before executing. Never execute a PATH binary or accept caller-provided runtime/URL/extra flags.
- Output only to a new directory under ignored `tests/screenshots/qa-current/local-privacy/inference-runs/`. Reject existing directories and path escape; never overwrite/delete prior evidence. Preserve raw bounded stdout/stderr, prompt/schema, input hashes/indices/timestamps and process outcome. These contain only synthetic data, are not public product logs, and must stay ignored.
- A process exit or JSON parse is not semantic acceptance. All generated reports retain `human_model_quality_reviewed=false` and `outbound_isolation_verified=false`; root records real human assessment separately. No automatic repair, truncation, invented fields or silently discarded parts.

## Task 1: Single-case runner, structured contract and fault tests

**Own exactly:** new `scripts/run_local_inference_probe.py`, new `tests/unit/test_local_inference_probe.py`, new `docs/reports/2026-09-13-local-inference-runner-task-report.md`. Root owns plan/progress/Git and executes real models after tests. Do not modify existing helper or policy.

**Interfaces:**

```python
def local_schema(locale: str, *, has_text: bool, has_visuals: bool) -> dict: ...
def decode_response(raw: bytes, locale: str, *, has_text: bool, has_visuals: bool) -> dict: ...
def prepare_input(case_id: str, output_dir: Path, quality: str = 'balanced') -> dict: ...
def run_case(case_id: str, locale: str, *, quality: str = 'balanced',
             timeout_seconds: float = 600, cancellation_event=None,
             process_runner=run_bounded, memory_reader=windows_available_memory) -> dict: ...
```

`local_schema` accepts exactly zh-CN/zh-HK/en-US. Use two mutually exclusive object branches: understood=false allows only required understood/language; understood=true requires understood/language/topic and allows optional date/entity/version objects and context array (max3). This must be enforced by the generation schema as well as the decoder, not only prose. Each segment has only `value` (nonempty max180), `evidence` (nonempty max2000), `evidence_source` constrained to actually available modalities. No additional properties. No mandatory optional field filling. The model supplies no paths or extensions. `decode_response` uses strict UTF-8, may remove one exact terminal native ` [end of text]` marker confirmed in completion stdout, and rejects duplicate JSON keys, multiple objects, fences, thoughts, truncation, NaN and unknown fields; converts optional named roles to ordinary policy `parts` in date/entity/topic/context/version order without altering values. `understood=false` requires all role fields absent. `understood=true` requires topic. Final validation invokes unchanged `SmartNamingPolicy(locale).render(..., extension=source suffix)` with actual extracted text and actual visual presence. Invalid output remains a failure record, not an edited name.

Input preparation: case01/02/03 read their verified UTF-8 text; case05 extracts both real PDF text layers (bounded two pages); case04/08 use `ImagePreprocessor.process_file`; case06 uses `PdfRenderer.render_file(page_indices=[0,1])`; case07 uses `VideoKeyframeExtractor.extract_file(quality_mode=quality)` preserving 4/6/8 order and timestamps. PreparedVisualPayload byte data is written to opaque `visual_00.jpg` etc in the new diagnostic directory. Never pass a PDF/MP4 path to the model. Exclude source basename/path and oracle from prompt. Text extraction is bounded to32KiB, prepared images total16MiB and at most8; fail instead of truncating source text.

Prompt: use existing policy description once (do not repeat it within an embedded schema), explain the optional named-role JSON contract, state actual available evidence modalities explicitly, then delimit actual text as untrusted source data. Visual-only requires all evidence_source=visual, including printed words seen inside an image. Add concise specific topic, omit nonessential enumerations, one role per named field, no thinking/prose. Do not include case-specific answers. The fixed schema is sent separately via `--json-schema-file` and may be compactly illustrated without duplicating instructions.

Fixed native argv: explicit `--offline -m <verified GGUF> -f <prompt> --json-schema-file <schema> -n 1024 -c 8192 -t 4 -tb 4 --device none --no-op-offload --no-kv-offload --flash-attn off --no-warmup --seed 1 --temp 0 --log-colors off --verbosity 1`. Text-only uses verified `llama-completion.exe` with `--conversation --single-turn --jinja --reasoning off --no-display-prompt --simple-io`. Vision uses verified `llama-mtmd-cli.exe` with verified `--mmproj`, `--mmproj-device none --no-mmproj-offload --image <comma joined prepared images> --image-max-tokens 1024`; no nonexistent text-only flags. Both binary help sets have been directly verified. Root can revise experimental tuning after measured evidence; implementer must not invent new flags.

The Job runner receives only SystemRoot/WINDIR plus PATH containing the pinned runtime and System32, and TEMP/TMP pointing to the new evidence directory. No ambient LLAMA/HF/proxy/auth variables. timeout finite positive at most900s; stdout262144bytes/stderr1048576bytes; cancellation and cleanup are mandatory. Result separates `launched`, lifecycle status/exit/cleanup, parsed response, `policy_accepted`/safe error and suggested_name. Failed process must not be decoded as success. JSON output printed to terminal is a concise summary, not unbounded logs. CLI: `--case case_01 --locale zh-CN --quality balanced --timeout 600`; each invocation creates a unique new evidence directory and returns nonzero on process/protocol/policy failure, including honest insufficient-content; report is still retained. Root determines whether that negative is expected for blank case08.

- [x] RED tests before script: schema evidence modality, fixed one-role mapping, required topic, no fields when understood=false, duplicate-key/unknown-key/fenced/NaN/truncated/multiple JSON rejection, no value sanitizing or shortening.

```python
def test_visual_text_is_still_visual_evidence():
    schema = local_schema('zh-CN', has_text=False, has_visuals=True)
    branches = schema.get('oneOf', schema.get('anyOf'))
    understood = next(b for b in branches if b['properties']['understood']['enum'] == [True])
    assert understood['properties']['topic']['properties']['evidence_source']['enum'] == ['visual']
def test_duplicate_json_key_is_rejected():
    with pytest.raises(ValueError):
        decode_response(b'{"understood":true,"understood":false,"language":"zh-CN"}', 'zh-CN', has_text=True, has_visuals=False)
```

- [x] Implement pure schema/decoder and real preparation; verify all eight inputs with no oracle leakage, page/frame indexes and source types. Use temporary synthetic copies for fault injection; do not mutate accepted corpus.
- [x] RED launch tests using fake process: low RAM, bad resource/source hash, unsafe output path/existing target cause zero process calls; text chooses completion and no image/projector; visual chooses mtmd with only prepared stills; environment excludes injected fake secrets/proxy/LLAMA variables; cancel/timeout/nonzero/output_limit/cleanup_incomplete never accepted; malformed/ungrounded/language-invalid output rejected by real policy; raw result retained on failure.

```python
def test_low_ram_never_launches():
    calls = []
    with pytest.raises(RuntimeError, match='MEMORY_BLOCKED'):
        run_case('case_01', 'zh-CN',
                 process_runner=lambda *a, **k: calls.append((a, k)),
                 memory_reader=lambda: 1)
    assert calls == []
```

- [x] Run `python -m pytest tests/unit/test_local_inference_probe.py -q`, then all five local diagnostic files. Report exact RED/GREEN and no claim about real model quality. Freeze three owned files; root reviews and commits.

Task 1 closed at `a1bd3e66`: independent review approved the strict runner after a post-preparation memory-refusal report was added. Root focused result: 43 passed; current complete non-screenshot suite: 2107 passed, 1 existing skip. Native file-reading comparison required one engineering adjustment: child cwd is the new evidence directory and prompt/schema/visual arguments use their ASCII basenames because this pinned CLI cannot open their absolute Unicode filenames. No paths or names are sent as content. Separately, `7673c28` corrects an independently reproduced whitespace false rejection in existing Chinese date grounding; see its own narrow plan/report. Neither change establishes model quality or outbound isolation.

## Task 2: Root-owned actual inference and human assessment

- [ ] First one text and one image case: full verified resource path, one process, raw results, memory/time/cleanup. Stop/tune on actual errors; never lower guard or force private mode readiness.
- [ ] All eight cases in three locales; additional case07 economy/quality frame runs as needed. Read actual outputs against actual source media and reviewer oracle. Mark each specific-name/grounding/language/style/length result independently; preserve failure attempts. No mocked quality PASS.
- [ ] Report measured hardware/runtime limits and protocol changes, perform scoped independent review, then continue L1 only after real feasibility can be accepted.
