# Local naming quality: actual outputs and root assessment

## Review scope

Only the reviewed synthetic corpus is used. The root inspects generated output against the actual source/derived visual, not just an oracle or mocked API. Process success, strict JSON success, common-policy acceptance and human quality are separate outcomes. No full local-mode or network-isolation pass is implied.

## Resume with available memory

Start: branch `codex/local-privacy-mode`, clean HEAD `02d1e0d3247e114dc6e395efe9dc87f2dafa5852`. Native available memory **5,906,092,032 bytes**; unchanged 5GiB preflight passed. All pinned resources were reverified by each actual runner. Root alone ran model processes serially.

### case01 / zh-CN — specific content, rewritten evidence rejected

Evidence directory: `tests/screenshots/qa-current/local-privacy/inference-runs/20260913T081954293639Z-case_01-3aa86cd560cb4db4ba48259a4f868dd0/`.

- Native elapsed **40.979206500109285s**, exit0, Job cleanup true; raw stdout/stderr retained.
- Generated parts: date `2026-08`; topic `海岚实验室星桥项目校园网络维护`; version `v2.1`.
- These facts and language match the actual source. No day was invented and the topic is specific rather than just a report category.
- Date evidence was `时间：2026 年 8 月`, but the actual immutable source says `时间：2026年8月`. The literal-excerpt check rejected it: **smart.error.ungrounded**. The quote was not repaired or retrospectively accepted.
- The dated whitespace-validator fix remains legitimate for truly spaced source text, but does not solve this separate model quotation-rewrite problem.
- Overall: **not accepted**. Next experiment replaces generated text quotations with references to parent-owned original fragments. It still requires semantic review of generated values.

### case04 / zh-CN — visual facts correct, name insufficiently selective

Evidence directory: `tests/screenshots/qa-current/local-privacy/inference-runs/20260913T082420977449Z-case_04-c601e2bdfca44b91a6faab0bdbb7831f/`.

- Native elapsed **100.65887039992958s**, exit0, Job cleanup true; stderr empty at configured verbosity1. The already-imported runner was unchanged during this invocation.
- Root viewed the actual prepared `visual_00.jpg`: Chinese labels and two exits are readable; warehouse fire-evacuation diagram, green arrows, assembly point and four area labels are present. Image SHA256 `35dda70aa8e166c552c65ad2ac0193b9bf696bf3c59efa6785f04cc1d60b3adf`.
- Generated filename: `北区仓库_北区仓库消防疏散路线_沿绿色箭头撤离_集合点_存储区、包装区、收货区、设备区.png`.
- Strict schema and policy accepted it. Every cited visual label exists; no dates, versions or unrelated objects were invented. Simplified Chinese and extension are correct.
- Human review nevertheless does **not** accept final name quality: the entity is repeated in the topic and peripheral captions/area lists are unnecessarily enumerated. They add little distinction for this file.
- Next tuning is generic information selection, not a hard-coded answer: do not repeat entity in topic; omit nonessential captions/instructions/lists; optional roles are not a checklist. The original generated filename stays in raw evidence.

### Revised text references / case01 and case04 / zh-CN

The frozen diagnostic runner SHA256 was `9d12b4ffdffeb9721ac267814885b919a7c2cf0e16e94679ca8a59b00a75409e`; root independently reran focused tests (**157 passed in 2.57s**) and the five diagnostic files (**219 passed in 25.21s**). No model output was edited.

- case01 evidence: `inference-runs/20260913T084713087684Z-case_01-afc0629778b74933acbd2a27152dccf8/` under the same QA root. Native **68.48011530004442s**, exit0/cleanuptrue, strict protocol and policy accepted. The date now resolves to exact original `时间：2026年8月`; this confirms the quotation-rewrite correction in a real model run. However the name repeats the full entity in the topic and includes three long maintenance/process/result clauses. Human naming quality remains **not accepted**, despite factually supported content.
- case04 evidence: `inference-runs/20260913T084901357424Z-case_04-3bf403ad58c94594b94c2342ceb47dfe/`. Native **104.64106649998575s**, exit0/cleanuptrue, policy accepted. The actual prepared image has the same reviewed SHA `35dda70aa8e166c552c65ad2ac0193b9bf696bf3c59efa6785f04cc1d60b3adf`. Filename: `北区仓库_北区仓库消防疏散路线_存储区、包装区、收货区、设备区_出口A、出口B_沿绿色箭头撤离.png`. Facts match, but duplicated entity and unnecessary enumeration persist: human quality **not accepted**.

Thus prompt-only advice to omit optional fields did not reliably solve small-model over-expansion. The next bounded diagnostic experiment will simplify the model-facing response to one content-bearing title plus optional evidenced date/version. It must still summarize actual content, include relevant distinguishing entities within that title when useful, preserve exact evidence references and run the unchanged common safety policy. It must not truncate or silently repair generated values. This does not change the existing cloud strategy, template choices or product UI.

### Compact protocol / initial text and image / zh-CN

Frozen runner SHA256 `efa10eed0b894bbb2bf3dfccf11305be77356e6ba6d3949046c195ff17334425`, protocol `local-summary-v2`. Root fresh verification: **167 passed in3.03s** (runner + shared policy), **229 passed in20.31s** (five diagnostic files). Same resources, arguments and reviewed inputs; no name was shortened after generation.

| Case | Actual suggestion | Runtime | Root content/name assessment |
|---|---|---|---|
| case01 | `2026-08_海岚实验室星桥项目校园网络维护报告_v2.1.txt` |35.57005949970335s|Accept this sample: specific organization/project/topic, correct month/version, no invented day, no duplicate or body-text expansion; simplified Chinese and extension correct.|
| case04 | `北区仓库消防疏散路线.png` |78.51314179971814s|Accept the name for this sample: directly matches the reviewed evacuation diagram and location, no peripheral area list or invented dates; simplified Chinese and extension correct.|

Evidence directories under the local-privacy QA root: `inference-runs/20260913T090535467307Z-case_01-dfe8dc5f2ab24797a4a815d1f52d192e/` and `inference-runs/20260913T090614996009Z-case_04-31da27beb3264892876eb5602b80f492/`. Both process exit0, cleanuptrue, strict protocol and shared policy accepted. The case04 prepared visual SHA remains the previously inspected `35dda70aa8e166c552c65ad2ac0193b9bf696bf3c59efa6785f04cc1d60b3adf`.

Case04's model-supplied visual evidence text was only `标题` (title). This is weaker explanatory evidence than requested; the root's independent comparison with the actual image, not that self-report, supports the naming assessment. Do not promote the self-report to proof of semantic grounding. Broader language/media/refusal tests and OS network isolation remain pending; these two samples are not an overall local-mode pass.

### Compact protocol / remaining six samples / zh-CN

The same frozen v2 runner completed the remaining six actual model runs serially. Every process exited0 and reported Job cleanuptrue; none used cloud APIs. The outer matrix command completing successfully does **not** mean every sample passed. Strict policy rejections remain recorded failures, not corrected outputs.

| Case | Runtime(s) | Actual result | Root assessment |
|---|---:|---|---|
|case02|32.55718629993498|Topic `山岚社区雨水花园维护指引`; invented date `YYYY-MM-DD` and version `v2`; rejected `smart.error.invalidResponse`.|FAIL: source has no date/version. Missing metadata must be explicit absence, not fabricated placeholders.|
|case03|37.98629290005192|Topic `North Pier Archive Digitisation Migration Assessment`; invented date `YYYY-MM-DD`; correct versionv3.2; rejected `smart.error.invalidResponse`.|FAIL: date absent and requested zh-CN not respected by copying the English heading.|
|case05|38.94134319992736|Topic `Cedar Research Library Scanner Evaluation - Bound-Book`; invented date2024-01-01/versionv1.0; rejected `smart.error.ungrounded`.|FAIL: two-page source contains neither metadata item; topic also fails requested Chinese output.|
|case06|148.92099309992045|Topic `青禾咖啡馆咖啡机维护确认`; date `2026年8月`; versionv1.1; rejected `smart.error.invalidResponse`.|Facts match the scan, but date does not follow canonical numeric format. Topic could distinguish the central boiler descaling/seal replacement work more clearly. No post-hoc normalization accepted.|
|case07|80.01488320017233|Policy accepted `植物繁育流程图解.mp4`.|Human name quality not yet accepted: output omits the core cutting/water-rooting/transplant workflow even though the model's own visual evidence recognized those steps.|
|case08|39.368824400007725|`understood:false`, no parts, `smart.error.insufficientContent`, no name.|Expected refusal PASS for blank content. This is not a failure to fix by inventing a title.|

Evidence directories, relative to `tests/screenshots/qa-current/local-privacy/inference-runs/`:

- case02: `20260913T091316352763Z-case_02-084792179a234f7d9c4344d28c0b4051/`
- case03: `20260913T091352935820Z-case_03-9ce108126bc74565ba9906bdbaa21661/`
- case05: `20260913T091434818269Z-case_05-09e35556182f4e9b91a7be56bc4f64fb/`
- case06: `20260913T091517797447Z-case_06-5f77bc97e0ee4ea2963d538a89237580/`
- case07: `20260913T091751143816Z-case_07-196769f824664b8aa5a3359c937f7b3d/`
- case08: `20260913T091915378861Z-case_08-459a4d0e110841a2894aa476f493c1bd/`

Root directly inspected both case06 rendered1200x1600 pages: upright, readable Chinese, no missing/cropped page content. Page0 contains CM-20, maintenance month2026年8月; page1 specifies boiler descaling, seal replacement and v1.1. Root also inspected case07 frames0/2/3/5 from the actual balanced run: cutting → water-rooting → transplant, with clear Chinese captions. Frame timestamps were0.5/1.5/2.5/4.0/4.75/5.5s. No plant species is established by these illustrations; naming one would be unsupported.

Next bounded experiment: required nullable metadata, exact parent-owned candidates for text dates/versions, numeric visual-date syntax, an explicit requested-language instruction and a content-bearing topic across pages/frames. Protocol version is result metadata, not document evidence. Existing shared policy remains unchanged; original bad outputs remain intact.

### Nullable metadata / complete actual v3 zh-CN matrix

Frozen runner `df252133ecf787dab0dad81fe3859d7d9867f0ae5dda85df1b8fadd271db3b46`; frozen supervisor `8be5ec3ff433274eec53128cf5353c9aa0467296c23c368629a19f60ed764120`. Root fresh seven-file verification:447 passed in20.78s. All eight native processes exited0 with cleanuptrue. This used the ordinary diagnostic path, not a verified AppContainer.

|Case|Seconds|Actual outcome|Root quality assessment|
|---|---:|---|---|
|01|34.61655099969357|`2026-08_海岚实验室星桥项目校园网络维护_v2.1.txt`|Accepted sample: specific subject/project, correct month/version.|
|02|24.19056269992143|`山岚社区雨水花园维护指引.txt`|Accepted sample: actual source bank reread; absent date/version correctly omitted.|
|03|35.120176300406456|`发票与工程图纸的OCR迁移评估_v3.2.txt`|Accepted sample: actual source bank reread; Chinese captures two collections/migration purpose with correct version, no fabricated date.|
|04|76.82830619998276|`北区仓库消防疏散路线.png`|Accepted sample: prepared image SHA identical to the independently viewed diagram.|
|05|30.74779379973188|Raw topic `Cedar Research Library Scanner Evaluation`, both metadata null; PROTOCOL_INVALID, no accepted name.|FAIL: still copied English despite requested Chinese. Raw stdout inspected.|
|06|151.1423961999826|`2026_青禾咖啡馆咖啡机维护确认_v1.1.pdf`|Policy accepted, but visible month omitted and title remains broad; refinement pending. Both prepared scan hashes unchanged.|
|07|77.38855679985136|`植物繁育.mp4`|Policy accepted; human specificity FAIL: misses defining cutting/water-rooting/transplant process.|
|08|37.37303330004215|understood:false, smart.error.insufficientContent, no name|Expected refusal PASS; blank image hash unchanged.|

Raw run directories below the existing local-privacy `inference-runs/` root:

-01: `20260913T094857881068Z-case_01-d953d0ae6910494b8ae71f7d70b716aa`
-02: `20260913T094318373765Z-case_02-cc2faa8d1e6f435bbe4e4943271f0eb7`
-03: `20260913T094346519982Z-case_03-29f4651fade24fba9f344a55d38d9491`
-04: `20260913T094936496554Z-case_04-88786155f7904d3ea3c95a969d8e8290`
-05: `20260913T094425618443Z-case_05-9f53c3ab51ad45d2ac2aa5dfb5ae84ee`
-06: `20260913T094500665465Z-case_06-cbcb79fe98794d70867199064a50fcf0`
-07: `20260913T094736377973Z-case_07-7e1dfa407bea4115bd33f38121d2c8e2`
-08: `20260913T095057484441Z-case_08-1b9687edd9f241be90c7cbaf01562eeb`

Independent review also found incomplete metadata-token acceptance outside this fixed corpus: spaced invalid dates, third range endpoints, ambiguous pure years and unsupported version suffixes. Root independently reproduced the first three pure-helper counterexamples. A removed-field negative test also lacks otherwise-required null metadata. These are being corrected together without altering any model evidence.

Next v4 experiment keeps response fields/common policy, fully localizes instructions and puts topic evidence before generated value. It also reinforces requested language and known date precision. This is a hypothesis requiring actual model reruns, not proof of understanding or a full local-mode pass.

## Remaining gate

## v4 actual targeted results, preserved at resume (2026-09-28)

The three runs below were captured on 2026-09-13, not rerun on the resume date.
Runner SHA-256: `211265de2ab3c22bf78e023f261b78a752f8b90ecc44bde317c77584decf4b2d`.
All exited 0 and reported completed cleanup. They are real local CPU inference,
but outbound isolation was not established and raw human-review flags are left
unchanged. Judgments below are separate from the immutable raw outputs.

| Case | Seconds | Result | Human assessment |
| --- | ---: | --- | --- |
| 05 | 32.968511 | PROTOCOL_INVALID; no accepted name | Still copied the English heading for requested zh-CN. Missing date/version now remain null; language requirement FAIL. |
| 06 | 153.978031 | `2026-08_青禾咖啡馆咖啡机维护_v1.1.pdf` | Correct visible site, object, activity, month precision and version. Useful accurate summary; no full quality-matrix claim. |
| 07 | 82.546365 | `植物繁殖流程.mp4` | Broadly accurate but does not distinguish cutting, water rooting and transplanting. Specificity remains a quality limitation. |

Evidence directories under the ignored local-privacy inference-runs directory:

- `20260913T100608640293Z-case_05-7a5ece72955a4881a668e790365b3ef4`
- `20260913T100812235872Z-case_06-0b2ab762f2a3459499e02064bdef7b14`
- `20260913T100645552775Z-case_07-fc13ca1c160a46d9bda9f6f6f08cc3c5`

Fresh resume regression: the eight diagnostic/policy/process/security/profile/
resource/corpus test files passed `520 passed in 78.43s`. This does not turn the
case05 language failure into a semantic pass. Available physical memory at the
resume preflight was only 293468 KiB; no new model process was started.

### Outstanding acceptance

No three-language/mixed-media matrix pass yet. Next tests must use the revised protocol on actual text and vision, then all8 cases across zh-CN/zh-HK/en-US plus frame-count variants. Missing/unreadable content must remain an explicit refusal. Constrained source-reference selection proves where evidence came from, not that a model's summarized value is entailed.

The current diagnostic exercises smart naming only. Real template-field generation/rendering remains a separate pending gate, including missing-required-field refusal; a compact smart response is not proof that every existing template can be satisfied by the local model. Existing product templates/defaults/Watch choices must not be changed to hide that gap.

Independent review of `02d1e0d..de135c9`: no Critical/Important issue found. Two Minor findings: a whitespace-only2000-character chunk can cause a conservative bank self-rejection (backlog); the migrated runner integration test no longer reached a policy failure (explicitly repaired in the next compact diagnostic task). No resource/memory/process/grounding safety checks were relaxed. The reviewer did not rerun model/pytest and did not claim semantic quality.
