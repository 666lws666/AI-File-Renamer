# Real local naming: three-language mixed corpus, v7

## Verdict and scope

**PARTIAL, not a local-privacy release pass.** The frozen v7 diagnostic completed
24 actual model runs (eight synthetic cases in three languages). All processes
exited 0 with supervisor cleanup confirmed. Structural policy accepted 20 names;
the three blank-image runs correctly refused insufficient content, and the
English scanned-PDF run refused ungrounded metadata. Those are distinct outcomes,
not a claim that 20 names passed human semantic review.

The exact runner SHA-256 is
`0384e9d3ad3233f5d4af6354650f081b150893f86e8ebb9846e3a20bf4ad6bce`.
Use pinned Qwen3.5-4B Q4_K_M, F16 visual projector and llama.cpp b10885 recorded
in `resources/local-models/qwen35-4b-feasibility.json`. CPU-only fixed sampling,
single process at a time; no model download, cloud API, credential or private
input. All runs are ordinary supervised offline processes, **not yet proven
outbound-isolated**. Raw results intentionally retain
`outbound_isolation_verified:false` and `human_model_quality_reviewed:false`;
the human review is recorded separately here.

Only `semantic-corpus-v1-reviewed` was used. Cases 01–03 are text, 04 a fire-route
diagram, 05 a two-page scanner evaluation PDF, 06 a two-page scanned coffee-machine
maintenance record, 07 a plant propagation video, 08 a blank image. Case05 uses
the explicit contiguous-text experiment; the other cases retain the default
line layout. This is not a universal text-grouping migration. Balanced video
uses six prepared frames; no complete PDF/video was a model input.

## Results reviewed against source content

Elapsed seconds are process-supervisor elapsed time, not a promised user-visible
end-to-end speed. Filename extensions below are original, unchanged.

| Case | Language | Seconds | Actual suggestion / refusal | Assessment |
| --- | --- | ---: | --- | --- |
| 01 | zh-CN | 34.189 | 2026-08_校园网络间歇中断问题维护_v2.1.txt | Grounded topic, correct month/version. |
| 01 | zh-HK | 35.516 | 2026-08_星橋項目校園網絡維護_v2.1.txt | Grounded project/topic, correct month/version. |
| 01 | en-US | 35.902 | 2026-08_Hailan Lab Xinqiao Campus Network Maintenance_v2.1.txt | Grounded transliterated proper names/topic, correct month/version. |
| 02 | zh-CN | 25.525 | 山岚社区雨水花园维护指引.txt | Specific supported subject; no invented date/version. |
| 02 | zh-HK | 26.088 | 山岚社區雨水花園維護指引.txt | Descriptive text traditional; original proper-name character 岚 retained. |
| 02 | en-US | 26.590 | Shanlan Community Rain Garden Maintenance Guide.txt | Supported subject; no invented metadata. |
| 03 | zh-CN | 33.649 | 北码头档案数字化迁移评估_v3.2.txt | Supported topic/version; no invented date. |
| 03 | zh-HK | 35.955 | 北岸檔案數位化遷移評估_v3.2.txt | Topic/version supported; `北岸` is a loose rendering of North Pier, not a verified official name. Proper-name fidelity limitation. |
| 03 | en-US | 35.690 | North Pier Archive Digitisation Migration Assessment_v3.2.txt | Accurate concise source topic and version. |
| 04 | zh-CN | 82.788 | 北区仓库消防疏散路线示意图.png | Matches visible diagram. |
| 04 | zh-HK | 79.862 | 北區倉庫消防疏散路線圖.png | Matches visible diagram. |
| 04 | en-US | 78.091 | North warehouse fire evacuation routes and assembly point location map.png | Matches visible routes/assembly point. |
| 05 | zh-CN | 30.078 | 装订书扫描与色彩 OCR 评估.pdf | Complete title covering both source sections. |
| 05 | zh-HK | 30.656 | 書脊掃描架與頂部掃描架比較.pdf | `書脊掃描架` is imprecise for cradle scanners; do not count as an unqualified semantic pass. |
| 05 | en-US | 29.273 | Cedar Research Library scanner evaluation workflow.pdf | Grounded but less discriminating than bound-book/colour/OCR evaluation. |
| 06 | zh-CN | 140.104 | 2026-08_青禾咖啡馆咖啡机维护记录_v1.1.pdf | Correct topic/month/version from visible pages. |
| 06 | zh-HK | 143.655 | 2026_青禾咖啡館咖啡機與鍋爐維護記錄_v1.1.pdf | **Date-precision mismatch:** quoted evidence explicitly says 2026年8月, value drops month. Current guard accepted it; must address before integration. |
| 06 | en-US | 139.200 | smart.error.ungrounded; no name | Correct refusal of output whose date evidence was only `text`; readable input nonetheless failed to yield a usable accepted name. |
| 07 | zh-CN | 78.032 | 植物繁育流程.mp4 | Correct but broad; does not distinguish cutting/rooting/transplanting. |
| 07 | zh-HK | 77.660 | 植物繁殖流程圖.mp4 | Correct general subject, broad; source is a sequence of diagrams in video. |
| 07 | en-US | 77.262 | Plant propagation stages from pruning to transplanting in a pot.mp4 | More discriminating supported sequence; no invented species. |
| 08 | zh-CN | 40.170 | smart.error.insufficientContent; no name | Correct blank-image refusal. |
| 08 | zh-HK | 39.407 | smart.error.insufficientContent; no name | Correct blank-image refusal. |
| 08 | en-US | 38.288 | smart.error.insufficientContent; no name | Correct blank-image refusal. |

No source-less dates or versions were added to cases 02/04/05/07. Accepted names
use the same role ordering and underscore separator; date precision in case06
HK is the concrete exception needing correction. Similar titles are not an
end-to-end same-name-conflict/Apply/Undo validation; those product paths have not
been exercised with the local model.

## Evidence index

All directories are under ignored
`tests/screenshots/qa-current/local-privacy/inference-runs/`; each preserves
result JSON, raw stdout/stderr, exact prompt/schema and supplied evidence. IDs
are recorded rather than rewriting historical results to reflect later review.

| Case | zh-CN run | zh-HK run | en-US run |
| --- | --- | --- | --- |
| 01 | 20260928T162207710529Z-case_01-cbd3c5b889c045eda922cf0b5b4c77c7 | 20260928T163012272760Z-case_01-ea5f436cfe6a46deaeed4e94c9559261 | 20260928T163757289237Z-case_01-2b6aacc8259b48baaf68f5737e83d9db |
| 02 | 20260928T162245561180Z-case_02-9ab59b2faa0e428e86ada48932f3bfc0 | 20260928T163051473732Z-case_02-50439104248c4ae39460380f24ddacfe | 20260928T163836821839Z-case_02-a9650aba620f47129c13783c8cb37f00 |
| 03 | 20260928T162314778834Z-case_03-9bbfbab052e041939716c678a66b9051 | 20260928T163121206309Z-case_03-cd468139455e4f27a19e55202b3af7ea | 20260928T163907282996Z-case_03-af5162ace02c4ae2a1af4e0b9f402c68 |
| 04 | 20260928T162352050568Z-case_04-53cdeed1c57e47c5af1412d21e245d97 | 20260928T163200704911Z-case_04-ada128fc7089463c9aac0433babb74a6 | 20260928T163946621228Z-case_04-f77c1a3fa93e43e3ba104ce24ea4a1a4 |
| 05 | 20260928T161555762054Z-case_05-24037d076dc1401597874d08babf3ddd | 20260928T161629545503Z-case_05-6cde0b39839f4a128c8fec3a41099fc2 | 20260928T161703909801Z-case_05-fbb1f30999d942a78c8df779fb099690 |
| 06 | 20260928T162518621904Z-case_06-500f2bbcfe3c4b0f9d365c245d9aace4 | 20260928T163324443792Z-case_06-283336a032b24efcaae3965a834b54c4 | 20260928T164108500650Z-case_06-ba25e8c3f863445bbdf3a0da120d6e49 |
| 07 | 20260928T162742851741Z-case_07-28b56cff55ec497e999e88d8d9a1e7e4 | 20260928T163552211009Z-case_07-00b7ba64eb4d4255874d0a4766e26505 | 20260928T164331824585Z-case_07-ccd2e33242a1400abde920b99b7ba8ef |
| 08 | 20260928T162905048280Z-case_08-431627d7daeb431e872fe643e454d31e | 20260928T163714127663Z-case_08-040244daee58456f8fc7bf9631406de5 | 20260928T164453165596Z-case_08-e4488cccc9524c3fb4ba2b5347bec44f |

## Resource and next-stage limitations

This host reports i5-13420H and Intel UHD Graphics; these runs explicitly use
CPU, not a measured GPU acceleration path. A read-only sample during scanned
processing observed a 5,966,561,280-byte process working set (not a measured peak).
The existing 5 GiB preflight threshold is not proof that 5 GiB available RAM
will support all visuals without paging. No user programs were closed and no
pagefile/driver/security settings changed.

Before product integration: correct the demonstrated date/evidence precision
contradiction, retain the failed English scan as a real usability limitation,
complete protected staging/contained execution/network-denial evidence, and
exercise the actual managed-model lifecycle and Batch/Watch paths. Ordinary
local process success is not evidence of privacy, offline end-to-end UI,
download/recovery behavior or packaged local-mode readiness. Do not continue
unbounded prompt tweaking or count mocked API tests as semantic approval.

## Additional real video frame-count comparison

The same v7 runner and synthetic video also completed economy (four frames) and
quality (eight frames) in zh-CN. This brings the recorded batch to **26 actual
model executions**, separate from the 24-cell balanced-language matrix above.

| Mode | Seconds | Name | Run |
| --- | ---: | --- | --- |
| economy / 4 | 53.317 | 植物繁育流程：剪枝、水培生根、移栽。.mp4 | 20260928T164610684240Z-case_07-1c9dfad857084e3bb5507b36fb826215 |
| balanced / 6 | 78.032 | 植物繁育流程.mp4 | Existing zh-CN case07 matrix run |
| quality / 8 | 92.616 | 植物繁育流程.mp4 | 20260928T164708139440Z-case_07-f7b018cfa3e94bfda4a3464dad131c37 |

Both extra processes exited 0, cleanup true, structural acceptance true. Root
opened all four economy JPEGs and all eight quality JPEGs: Chinese labels are
readable, stages are ordered, and there are no black or cropped-out main scenes.
The economy timestamps are 0.75, 2.25, 4.0, 5.25 seconds; quality timestamps are
0.375, 1.25, 1.875, 2.625, 4.0, 4.75, 5.25, 5.75. Several frames show the same
stage with animation/growth differences; they are not eight distinct actions.

The four-frame name is more informative but includes sentence-ending Chinese
punctuation before the extension, an awkward style outcome. Eight frames took
longer without improving title specificity on this sample. No model output was
trimmed or rewritten; more frames cannot be advertised as guaranteed better
naming. These runs cover sampled-image input, not arbitrary-video quality.
