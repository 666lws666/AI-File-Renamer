# Actual local inference observations — incomplete feasibility gate

Date: 2026-09-13. Branch `codex/local-privacy-mode`. Synthetic inputs only; no cloud API, credentials or model download in this experiment. Actual inference is now demonstrated, but naming quality and the process privacy boundary are not yet accepted.

## Native image probe 1: runtime success, policy failure

Resources were reverified immediately before execution against the pinned manifest and all extracted runtime members against the original archive. Input was only accepted synthetic `case_04.png`, SHA256 `203532d6a0ed9a3cfe679a5471ec85d8907d3e275729be5a32f90eeb959adb36`. The prompt contained the existing smart-policy description and schema, not the reviewer oracle or filename. The schema had the original array-of-parts form. The CLI received local image/model/projector paths; no remote flags or ambient credentials/proxy settings.

- Executable: pinned `llama-mtmd-cli.exe` b10885.
- Settings: CPU-only, four generation/batch threads, 4096 context, 1024 output tokens, image max1024 tokens, seed1, temperature0, no warmup, explicit offline, flash attention off.
- Available RAM immediately before model load: **6,302,380,032 bytes**; unchanged 5GiB guard passed.
- Actual result: lifecycle **completed**, exit **0**, tree cleanup **true**, PID36080, **208.980657 seconds**. These establish execution, not semantic acceptance.
- One live resource observation: working set6,176,808,960 bytes; private memory4,652,199,936 bytes. This is one process sample, not a peak or a minimum hardware requirement.
- Runtime stderr reported image encoding **97,525ms**, experimental CLI warnings and `find_slot` non-consecutive token-position warnings. Preserve these as compatibility/performance evidence; do not claim a warning-free inference.

Actual generated JSON (whitespace reformatted only):

```json
{
  "understood": true,
  "language": "zh-CN",
  "parts": [
    {"role":"topic","value":"北区仓库消防疏散路线","evidence":"北区仓库 消防疏散路线","evidence_source":"text"},
    {"role":"entity","value":"存储区","evidence":"存储区","evidence_source":"text"},
    {"role":"entity","value":"包装区","evidence":"包装区","evidence_source":"text"},
    {"role":"entity","value":"收货区","evidence":"收货区","evidence_source":"text"},
    {"role":"entity","value":"设备区","evidence":"设备区","evidence_source":"text"},
    {"role":"entity","value":"出口A","evidence":"出口A","evidence_source":"text"},
    {"role":"entity","value":"出口B","evidence":"出口B","evidence_source":"text"}
  ]
}
```

Root invoked the real unchanged `SmartNamingPolicy.render` on that response with `extracted_text=''`, `has_visuals=True`, extension `.png`: **`smart.error.ungrounded`**. The model identified the visible topic but incorrectly called observed image text extracted-text evidence and repeated the entity role. This is a failed naming result, not a usable filename.

The next diagnostic contract uses optional named roles rather than an unconstrained role array and restricts evidence_source to actual available modalities. It preserves generated values and evidence, converts them mechanically to the common policy structure, and still rejects unknown fields, duplicate keys, insufficient evidence, excessive length or wrong language. It does not force unavailable facts into a fixed template or silently repair names. No product policy/Provider code was changed.

## Evidence boundaries

This first ad-hoc native probe's stdout/stderr was captured in the tool transcript, not a durable raw-output artifact; the JSON above is transcribed from that output. The formal runner will retain raw bytes and per-case metadata in ignored QA storage. Do not describe the first probe as a complete reproducible quality matrix. Text/three-language/mixed-media quality, AppContainer outbound denial, offline end-to-end behavior and managed local-mode product integration are still open.

## Native text probe 1: no dummy visual, required topic missing

The verified `llama-completion.exe` was used for actual text-only `case_01.txt` (SHA256 `9f172ee18c0eb46b63e88eb61725e19c86a9498e29cb46f96c54c83f9014ace3`). Unlike mtmd, this binary supports explicit conversation single-turn, embedded Jinja template, reasoning off, no-display-prompt and simple-io. No image/projector was passed. Available RAM before load was **6,377,213,952 bytes**. Context8192/output1024/four threads/CPU/offline/seed1/temperature0; deadline240s.

Actual lifecycle: completed, exit0, cleanup true, PID14592, **45.2409137 seconds**; stderr empty. Stdout was JSON followed by the exact native ` [end of text]` marker and trailing whitespace. It declared understood=true/language=zh-CN but emitted only:

- version v2.1, text evidence `版本：v2.1`;
- context `2026 年 8 月`, evidence `时间：2026 年 8 月`;
- context `海岚实验室 星桥项目`, evidence `海岚实验室 星桥项目校园网络维护报告`;
- context `图书馆与东教学楼`, evidence `巡检确认图书馆与东教学楼的接入交换机出现端口故障和异常重启`.

There was **no topic field**. Thus the response cannot be accepted as a smart name, despite containing several grounded facts. This probe's optional-role grammar did not enforce the already-required relationship understood=true implies topic. The formal runner must encode two exclusive schema branches (false/no roles; true/required topic) and independently validate the relationship. Native marker handling is exact framing removal, not arbitrary prose stripping. These observations revise the diagnostic plan before its implementation is accepted; they do not weaken product policy or retrofit a successful name.

## Formal runner attempt and current memory limitation

The first formal case01/zh-CN invocation retained raw evidence at `tests/screenshots/qa-current/local-privacy/inference-runs/20260913T072332446471Z-case_01-5ef1063804e542d998101f0ac867fb96/`. Native exit was 1 and Job cleanup true; stderr showed `-f` could not open its absolute Unicode prompt filename. This was an invocation failure before model inference, not a semantic result. A no-model comparison (intentionally nonexistent GGUF) confirmed the same file is readable with the evidence directory as cwd and ASCII prompt/schema basenames. The fixed runner applies the same rule to prepared still images. No original media or resource was moved/replaced.

At committed runner `38f482c`, the next actual command stopped at the initial memory gate before creating output or launching a process. Available RAM was then measured at **4,763,938,816 bytes**, later **4,955,713,536** and **4,965,593,088**, each below the unchanged **5,368,709,120-byte** guard. No user applications were closed or paging settings changed. All three pinned resource roles and the extracted runtime continued to verify.

The second, post-preparation memory check had a separate source/test-confirmed report-retention defect, fixed in `a1bd3e66` and approved on independent re-review. Do not conflate that injected case with the actual first-guard refusal above.

In `7673c28`, a pure-policy reproduction also fixed an exact-source Chinese-date whitespace rejection (`2026 年 8 月` to `2026-08`), with precision/invented-date negative tests. This corrects the validator, not the earlier missing-topic or wrong-modality model responses. No successful naming result has been retroactively asserted. The formal eight-case/three-language matrix remains unrun; repeat from case01 after memory is available, using the current committed runner and corrected policy.
