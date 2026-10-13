# Local model and runtime attribution sources

Verified on 2026-09-30 against the fixed upstream revisions below. Local text
copies match upstream after normalizing CRLF/LF and terminal newlines; no license
wording or copyright notice has been changed. These files are redistribution
inputs, not a claim that product packaging/integration is complete.

## Qwen/Qwen3.5-4B

- Source model: `Qwen/Qwen3.5-4B`, revision
  `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`.
- [Upstream license](https://huggingface.co/Qwen/Qwen3.5-4B/raw/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/LICENSE).
- Local copy: `Qwen3.5-4B-LICENSE.txt` (Apache-2.0, including the upstream
  `Copyright 2026 Alibaba Cloud` notice).
- The GGUF conversion selected by the pinned `qwen35-4b-managed-v1.json` product catalog is from
  [Unsloth's pinned repository revision](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/tree/e87f176479d0855a907a41277aca2f8ee7a09523).
  Xuxia has not independently reproduced that conversion and does not claim to
  have trained the model. Exact resource hashes remain in that managed catalog.

## llama.cpp

- Runtime release `b10885`, commit
  `d7e86430a7d5fa4a0a7ee8bfb24d413d87bb240e`.
- [Upstream license](https://raw.githubusercontent.com/ggml-org/llama.cpp/d7e86430a7d5fa4a0a7ee8bfb24d413d87bb240e/LICENSE).
- Local copy: `llama.cpp-LICENSE.txt` (MIT, including the upstream
  `Copyright (c) 2023-2026 The ggml authors` notice).
- The pinned Windows CPU archive also contains `LICENSE-LLVM-OpenMP` alongside
  `libomp.dll`. Preserve that bundled license when unpacking/distributing runtime
  members. Do not substitute the top-level MIT license for dependency notices.

## Recorded local copies

At verification the files used LF line endings. Git checkout line-ending
conversion may change byte-level hashes; compare normalized text for license
identity and do not use these hashes to authorize executable/model resources.

| File | Recorded bytes | SHA-256 (LF copy) |
| --- | ---: | --- |
| Qwen3.5-4B-LICENSE.txt | 11344 | `689f0c220c9b4e857f35ca7d0dca51397e5a545dc4ad3987438c023e24ff0ab6` |
| llama.cpp-LICENSE.txt | 1078 | `94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d` |

No model download or inference occurred during license verification. The public
license requests contained no user filenames, document content or credentials.
