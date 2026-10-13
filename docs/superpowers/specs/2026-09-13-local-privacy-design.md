# Managed local privacy: approved direction and feasibility gate

## Authority and baseline

The Product Owner approved autonomous design, implementation, testing and documentation on 2026-09-13, after closing the prior smart-naming milestone. Baseline `488e6fcaedd9c71edf747bcc78c2fecc4bc4b9ea` has 1872 non-screenshot passes / 1 existing skip, 54 screenshot passes / 1 expected skip, acceptance 186/186 and package smoke 23 passes. Work remains isolated from the main checkout on `codex/local-privacy-mode`; the physical worktree retains its existing `ai-smart-naming` directory name. Do not push, publish, change user credentials or update further Golden files.

## Independent choices

Naming: smart naming or template naming. Processing: cloud or managed local privacy. Both processing paths must support both naming modes. Existing configurations, templates and Watch rules retain their choices; legacy processing defaults remain cloud until the user explicitly switches.

Local selection immediately closes the shared cloud-dispatch gate for Batch and Watch, including work queued before the click. Previously transmitted requests cannot be recalled; the UI must say so. Preparation, failure and cancellation keep that gate closed. Only an explicit switch back to cloud reopens it. Local failure never falls back to cloud.

## Runtime alternatives and selected experiment

1. **Native llama.cpp CPU GGUF + visual projector (selected first experiment).** Small Windows runtime, no external Python, suitable for CPU-only machines; exact model architecture, vision and structured output must be demonstrated. CPU speed is unknown until measured.
2. Transformers with packaged Python/Torch: closest to the official model format, but significantly larger runtime and memory footprint for this 16GB CPU-only host. Not selected for the first experiment.
3. User-managed Ollama/other local service: convenient for developers but conflicts with beginner setup and trusted managed-process requirements. Not used as the built-in privacy path.

The selected model is the post-trained `Qwen/Qwen3.5-4B`, not Base and not a cloud Qwen endpoint. The traced Unsloth quantization names that model as its base and declares Apache-2.0. Revision, hashes and exact sizes are pinned in the feasibility manifest. Upstream model revision: `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`; quantization revision: `e87f176479d0855a907a41277aca2f8ee7a09523`; runtime release: `b10885`.

Official source and license: https://huggingface.co/Qwen/Qwen3.5-4B and https://huggingface.co/Qwen/Qwen3.5-4B/blob/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/LICENSE . Quantization provenance: https://huggingface.co/unsloth/Qwen3.5-4B-GGUF . Runtime: https://github.com/ggml-org/llama.cpp/releases/tag/b10885 . Redistribution must retain model/runtime licenses and third-party notices.

## Milestones and hard dependency order

1. **L0 resources / feasibility:** verify/download exact public resources to ignored QA storage, inspect the trusted archive, verify runtime version; generate only synthetic text/images/scanned pages/video frames; run real inference and manually assess language/content/style. No product switch is added before real runtime feasibility.
2. **L1 trusted process boundary:** prove supervised lifetime/cancellation and per-process outbound denial without changing system firewall/security settings. `--offline` alone is insufficient. Prefer a no-network-capability Windows AppContainer with handle-based IPC; if the chosen runtime cannot work within the boundary, do not label it private. No loopback exemptions are silently installed.
3. **L2 resource management:** transactional staged download, hashes, pause/cancel/retry, exact disk accounting, verified offline import and restart recovery. Downloads carry only pinned public resource URLs, never file content, source paths or user filenames. The app requires the user's explicit Download and enable action.
4. **L3 dispatch/integration:** one process-mode authority guards every actual cloud send (not only task admission), snapshots mode generation, cancels superseded work and partitions local/cloud/model caches. Local bounded extraction, OCR/vision, naming and video-frame analysis stay inside the managed path. Preserve extension/preflight/Apply/Undo and Watch safety.
5. **L4 product UX:** persistent processing-mode selector; settings resource/status management; separate preparing/ready/failed states with visible privacy explanation. Three locales and filename-language independence. No unsupported speed/RAM promises.
6. **L5 adversarial/real acceptance:** synthetic mixed files, actual model semantics, download and process faults, Batch/Watch race negatives, disconnected end-to-end and process network checks, Windows clicks/CJK/minimum-size/scrolling, complete regression, package and isolated EXE smoke.
7. **L6 handoff:** three-language manuals, independent review, raw gate summaries/artifact hashes/hardware limitations, safe checkpoint. Stop after the approved scope. New Golden changes require a separate exact-scope approval.

## Host evidence and safe execution limit

Observed host: i5-13420H (8 cores / 12 logical), Intel UHD integrated graphics, 16,891,371,520 physical RAM bytes, over 460GB free D-drive space. At the first check available RAM was about 1GiB and pagefile usage about 15GB. These are observations, not minimum requirements.

The feasibility runner must not forcibly close user applications or change paging/security policy. For the first 4B Q4 + F16 projector experiment require at least 5GiB currently available RAM before model loading; this is a conservative test safety margin, not a published product minimum. If unmet, finish resource/provenance and safe negative tests, record that actual inference is blocked, and request that the user free memory. Do not substitute mock semantic results or ship a false-ready switch.

## Privacy claims

Limit wording to “Xuxia does not upload file content or naming requests in local privacy mode.” Resource downloads are a separate explicitly consented online activity. Do not claim control over other applications, operating-system sync or the whole computer. Redact content from logs/diagnostics, restrict temporary artifacts, and prevent runtime remote URL fetch/tool/network configuration. Observing zero network connections is evidence, not a substitute for outbound enforcement.

## Review

User direction resolves product choices; ordinary engineering decisions proceed autonomously. No unresolved value is represented as implemented. Exact runtime feasibility, process isolation and semantic quality each have a measurable gate. Hardware or permission failure blocks downstream integration while preserving the previous release checkpoint.
