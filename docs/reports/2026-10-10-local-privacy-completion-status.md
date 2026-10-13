# Local privacy completion ledger

Current delivery status: see [2026-10-12 local privacy delivery](2026-10-12-local-privacy-delivery.md).
The unfinished steps below are historical observations; their current disposition
and bounded verification evidence are recorded in that newer report. Historical
failures remain preserved and are not relabeled as passes.

Product Owner instruction: resume the approved local Qwen feature and complete a
usable Windows application autonomously. This ledger records actual dependencies
and verification boundaries, not a whole-product completion claim.

## Observed starting state

- Main checkout: `feature/xuxia-m0-foundation`, HEAD `4feb71200c08b18f0fe550295b624f9915577ae1`;
  the user-created application shortcut remains untracked and is preserved.
- Active isolated checkout: `.worktrees/ai-smart-naming`, branch
  `codex/local-privacy-mode`, HEAD `bd497caa37039d203a38338aeab0e2e746c4abec`.
- Pending service modules and tests, v8 protocol correction and plan changes from
  the previous session are preserved. No concurrent Claude writer is assigned.
- Ordinary command sandbox still fails setup refresh before process creation.
  Approved host commands work. No ownership, firewall or global collection change
  is needed to continue the implementation.

## Existing evidence to preserve

The real scanned-PDF precision failure and successful corrected trial, independent
six-frame video trial and blank-image refusal are recorded under
`tests/screenshots/qa-current/local-privacy/2026-09-30-scan-video-blank-review.md`.
Do not overwrite failed results, repeat all feasibility work, or equate these
limited examples with product acceptance.

The prepared resource store, pinned catalog, verified runtime inventory, trusted
AppContainer launch, ownership cleanup and inference service already exist. They
are the implementation to reuse, not replace with a localhost inference server.

## Completion sequence

1. **Inference checkpoint.** Scope the pending service/protocol files, preserve the
   successful real-model evidence and independent review. Current fresh focused
   baseline: 203 passed. Full regression is run before the checkpoint.
2. **Processing authority and durable choice.** Execute the existing
   `2026-09-30-processing-authority.md` Tasks 1 and 2. One process-owned authority
   controls both Batch and Watch. Selecting local closes cloud commitment before
   persistence; failed preparation or Settings Cancel cannot silently choose cloud.
3. **Final cloud send gate.** Wire the authority through all business retries and
   connection probes to the exact HTTP opener. A prior committed request may
   still transmit; an old-generation result cannot publish. Test both race orders
   with deterministic fake transports. No real cloud API is used.
4. **Local extraction and analysis.** Reuse prepared-media and naming contracts;
   branch before any cloud credential lookup. Make local extraction bounded,
   cancellable and content/path-redacted. Execute the existing video nested-I/O
   denial plan. Pass actual Watch quality through preparation and inference.
5. **Submission and result acceptance.** Capture the processing/config context at
   Batch submission and Watch event admission. Fence stale successes and failures,
   retries, queue acceptance and Auto Apply. Preserve accepted history/Undo and
   prior Watch configuration. Local failure has no cloud fallback.
6. **Managed resources and UI.** Compose one service/catalog/resource manager with
   owned user-data roots. Add asynchronous explicit download/offline import,
   progress/pause/cancel/retry and real self-check. Distinguish resource AVAILABLE
   from inference READY. Show a persistent cloud/local selector and visible privacy
   explanation in the three supported product languages.
7. **End-to-end and delivery.** Real synthetic Batch/Watch local trials, offline
   and concurrency failures, native clicks/CJK/minimum-window/scrolling, current
   full regression, three-language HTML guides, Windows package and isolated EXE
   smoke. Use current results and artifact hashes. Publish no completion claim
   for an unrun gate.

## Integration decisions

- `LocalServiceSnapshot.identity` is a stable readiness anchor.
  `LocalInferenceResult.engine_identity` additionally includes smart/template and
  selected text/visual resources. These identities are not interchangeable.
- General Settings Save/Cancel cannot roll back an immediate processing choice.
  The sole durable fact is the processing intent store, not another AppConfig mode.
- The existing naming cache has no production callsite. Do not introduce disk
  persistence of private naming content merely to fill an architecture diagram.
  Any future cache must include processing mode/model/naming/language context.
- Keep the user-selected filename output language independent of interface locale.
- New UI changes require native evidence. Formal Golden changes need a separate
  exact-scope authorization; until then, preserve baseline files and report the
  expected mismatches rather than changing comparison assertions or tolerances.

## Completed checkpoints on 2026-10-10

- `0740799`: composed service/protocol checkpoint after independent review;
  203 focused tests and 3451 non-screenshot tests passed (2 skips).
- `b969c8e`: sealed processing authority, generation cancellation, durable-choice
  receipts and per-HTTP attempt commitments; 56 focused tests passed.
- `25680e2`: strict separate intent store and single serialized writer, exact
  issued-choice provenance and Windows pinned atomic publication. Fresh combined
  authority/store/schema regression: 129 passed, 1 Windows privilege skip.
- `2fa5b4b`: final concrete urllib submission gate, separately committed retries,
  synthetic probes, stale-response discard and cancellation-aware backoff.
  Root and independent review each ran the expanded 273-test regression successfully.
- `eb29afb`: bounded text/Office/PDF extraction, truthful coverage, optional
  redacted diagnostics and explicit PyAV nested-resource refusal. Root and
  independent review each ran 154 focused tests successfully. This checkpoint
  provides cooperative cancellation, NOT an OS child-process hard timeout.
- Current complete non-screenshot regression at the transport checkpoint:
  **3593 passed, 3 skipped**, 3 existing Pydantic warnings, 94.50 seconds.
- Complete non-screenshot regression after extraction checkpoint `eb29afb`:
  **3647 passed, 3 skipped**, 4 existing dependency warnings, 99.30 seconds.
  A first PowerShell report-argument invocation did not collect tests; the
  corrected invocation ran the entire suite and passed. No assertion was changed.
- Existing screenshot baseline, updater disabled: **49 M1 passed** plus
  **17 other screenshot tests passed, 1 designed update-mode skip**. Current
  Windows uses default scaling. A prior historical 0.8 scale invocation failed
  40 dimension comparisons; its failure was preserved and no Golden changed.
- Existing acceptance runner: **186/186**. This is not a local privacy product
  end-to-end or fresh model-quality claim.

The first complete regression intentionally detected the uncommitted Provider
source through the existing HEAD-blob guard, and two tests rejected an in-repo
temporary root. After scoped checkpoint and ordinary OS-temporary fixture
isolation, those conditions passed without weakening assertions. One subsequent
complete run had a native diagnostic CLI empty-output startup failure; the same
case independently passed and the final complete run passed. Exit-code and stream
length diagnostics were added. Track recurrence rather than erasing that failure.

Steps 5–7 above are still unfinished. In particular, these foundation checkpoints
do not make the current Batch/Watch cloud-only composition a completed local
privacy feature. Bounded/redacted extraction, explicit nested video-I/O denial and
the hard-cancellable native processing worker are now reviewed. Managed immutable
analysis routing is reviewed; admission/publication composition is next.
The precise worker prerequisite is recorded in
`docs/superpowers/plans/2026-10-10-local-preparation-worker.md` (`0b22806`).

The older media track was checked read-only: its PDF/video "child" propagation
changes refer to the nested image processor, not an operating-system subprocess.
No earlier summary or successful cooperative timeout test establishes a hard
native parser/decode deadline in this branch. Reuse the actual reviewed Windows
Job/process lifetime boundary rather than claiming this missing work is complete.

## Hard-cancellable preparation checkpoint and current regression failure

- `69e0381`: bounded preparation protocol, fixed early worker dispatch, rebuilt
  child environment, hard cancellation/deadline and retained cleanup ownership.
  Root and independent reviewer each ran **300 focused tests successfully**;
  the review accepted both specification compliance and code quality. Synthetic
  text, image, text/scan PDF and video processing plus real stalled/descendant
  termination were included. This is extraction/lifetime evidence, not naming
  quality or whole-product acceptance.
- Full non-screenshot regression at this checkpoint: **1 failed, 3753 passed,
  3 skipped**, 4 existing warnings, 99.82 seconds. The failure is the previously
  observed legacy missing-model CLI diagnostic: exit code 1 with both captured
  streams empty, therefore its expected diagnostic assertion did not pass.
  Do not report this complete run as green or exclude the failing test.
- Fresh investigation: the same single test passed; its whole file **247 passed**;
  preceding local test combination **267 passed**; Shell/navigation followed by
  the diagnostic **14 passed**. A synthetic startup comparison (with/without
  detached console and `--simple-io`, three attempts each) reached the expected
  missing-model error in all twelve attempts. Cause is not established from these
  passing subsets. Observation instrumentation stays in the ignored QA directory;
  it does not change the tested assertions or count a retry as success.

## Managed analysis and native diagnostic checkpoints

- `c948cd5`: immutable, identity-sealed analysis admission, captured configuration,
  template, language and quality; managed local preparation/inference routing and
  guarded cloud dispatch. Root ran **359 focused tests successfully**; independent
  task review accepted specification and code quality. Local admission and analysis
  do not look up cloud credentials or silently fall back to a cloud adapter. These
  tests use controlled dependencies; they are not fresh model-quality evidence.
- `8bc5f99`: test-only correction to the native Unicode-working-directory parsing
  diagnostic. A synthetic 400-attempt investigation reproduced 11 empty-output
  missing-model exits. The pinned runtime uses an intentionally unflushed logging
  singleton on this failure path. The diagnostic now tests eager prompt/schema
  parsing via the explicitly flushed `--help` exit, with real negative tests for
  missing prompt, missing schema and malformed JSON. No model weights are loaded;
  actual model self-check and naming validators are unchanged. Root ran **250
  focused tests successfully** and independent review accepted both verdicts.
- Complete non-screenshot regression on these frozen source changes:
  **3838 passed, 3 skipped**, 4 existing dependency warnings, 101.31 seconds.
- Existing screenshot regression, update mode disabled: **66 passed, 1 skipped**,
  86 existing Pillow deprecation warnings, 47.18 seconds. The skip is the designed
  update-mode test; no Golden, assertion or tolerance changed.
- Acceptance: **186/186 passed**, zero failures. Configuration and keyring access
  in this runner are isolated/faked; this is not a new local-mode end-to-end Gate.

The original failed full run and raw synthetic startup observations are retained.
No passing rerun replaces them. The runtime logging defect was not repaired by this
test-only change; instead, the diagnostic now measures its stated parsing purpose
without relying on the lossy missing-model exit log.

Next: distinct, fixed-purpose candidate connection permits; a Qt-owned coordinator
for submission/choice/persistence acknowledgement and result acceptance; managed
Watch admission; resources/UI; real end-to-end, manuals and packaged delivery.
Neither reviewed analysis routing nor the passing existing screenshot suite means
the user-facing local privacy feature is complete.

## Fixed connection purpose checkpoint

- `113363e`: distinct identity-sealed CloudProbeContext, exact candidate/model
  matching, fixed typed ping body and dedicated last-moment send commitment.
  Ordinary WorkContext cannot be replaced by a probe permit for business analysis.
  Candidate capture requires no active cloud binding and does not change unrelated
  work. Both contexts are invalidated by LOCAL selection; attempt registration and
  one-use receipt consumption share one bounded implementation.
- Implementer focused authority/identity/Provider contract run: **228 passed**.
  Root cross-layer admission/routing regression: **315 passed**, 3 existing Pydantic
  warnings. Independent scoped review accepted specification and quality after a
  shared attempt-registration helper replaced duplicated logic.
- Complete non-screenshot regression after the reviewed source checkpoint:
  **3912 passed, 3 skipped**, 4 existing dependency warnings, 102.15 seconds.
  This includes the new fake-transport negative cases, not real API verification.
- The existing screenshot and acceptance results above still apply to unchanged
  visual files. They will be rerun at the runtime integration boundary. The four
  sequential C1 plans specify coordinator, Batch publication, managed Settings
  probes and runtime composition; those are not implemented at this checkpoint.

Unchanged analysis callers were checked: BatchAnalysisService.capture_work issues
only ordinary WorkContext, and AnalysisWork/AnalysisOutcome retain that exact type.
Coordinator invalidation-before-input-publication, closed admission and queued
result acceptance remain explicit next-task Gates, not claims made by C0.

## Qt choice coordination and metadata startup checkpoint

- `65e60fd`: owning-thread processing coordinator, private queued exact-intent
  acknowledgements, bounded writer/Qt drain, and explicit-path metadata-only config
  loading before migration, credential access or directory creation. LOCAL closes
  cloud admission immediately. A repeat explicit CLOUD choice also revokes prior
  work and stays unavailable until the exact latest durable acknowledgement; failed
  saving and stale acknowledgements cannot reopen it. Previously committed transport
  receipts remain finishable rather than pretending an upload was unsent.
- Initial scoped review found the repeat-CLOUD admission gap. The report preserves
  that finding; the focused authority correction and negative tests resolved it.
  Independent re-review accepted specification and code quality. Root focused run:
  **193 passed, 1 skipped**, 3 existing Pydantic warnings, 2.75 seconds.
- Full non-screenshot regression on that committed source: **3950 passed, 3 skipped**,
  4 existing dependency warnings, 102.01 seconds. No failed test was excluded beyond
  the separately tracked screenshot suite; no screenshots/Golden changed here.

This is still a prerequisite, not user-facing local-mode completion. Managed Batch
publication, Settings probes, runtime/Watch composition and resources/UI/native/
manuals/package remain. C1B/C1D now specify one atomic pure catalog admission scope
and one-use deferred local execution budgets for long queues; they are not yet
implemented or passed.

## Managed Batch publication checkpoint

- `d70ee1f`: immutable analysis catalog, atomic catalog capture scope, owner-thread
  admission, one-use deferred local execution budget, exact queued completion
  fencing, safe coverage notices and bounded pending ownership. Workspace-save
  failures remain retryable without claiming an unsaved suggestion is durable.
  Idle requires actual completion-signal emission to have returned, not merely
  `Future.done()`. Independent specification and quality review passed after the
  two reported lifecycle corrections. Focused source regression: **221 passed**.
- The broader Windows run exposed native Qt crashes. A test-only correction now
  retains controllers until actual worker/queued-message drain and destroys them
  on their owning thread; an unfinished-callback negative case must time out and
  keep its target alive. Publication plus performance: **73 passed**. Neither
  disabling Python GC nor switching Qt backends was accepted as a fix.
- A normal-GC full run then completed with **4038 passed, 1 failed, 3 skipped**;
  the sole failure was the older executable's language resources differing from
  current source. After a clean Windows rebuild, complete non-screenshot regression:
  **4039 passed, 3 skipped**, 4 existing warnings, 82.75 seconds. No failing test
  was excluded. Earlier in-repository temporary-root/replace failures and native
  crash diagnostics remain recorded; the final run uses normal OS temporary input
  fixtures rather than altering outside-repository assertions.
- Existing screenshot comparison with updates disabled: **66 passed, 1 designed
  update-mode skip**, 86 existing Pillow warnings, 44.22 seconds. Acceptance with
  isolated/fake credentials and disabled network: **186/186**. The rebuilt existing
  UI's package/smoke tests are included in the complete regression; they are not
  evidence for the unfinished local-mode production graph or model semantics.
- Provisional executable `dist/Xuxia/Xuxia.exe`: 11,100,799 bytes, SHA-256
  `5C56D9C9FFDDB4AED17981DF6B90F33AB001C8FF348FFCD02A398613BEA59503`.
  This is an intermediate source checkpoint, not a final local-privacy release.

Next: managed Settings/probes, one production graph with bounded Qt lifetime,
managed Watch/file operations, resources/UI, manuals and real-model/native/package
acceptance. No formal Golden changed, no main checkout merge or push occurred.

## Managed Settings and fixed-probe checkpoint

- `56f04280212083143f6d16dbcb36af8432a484c1` adds the five-file C1C checkpoint:
  live credential-read policy, bounded asynchronous fixed probes, exact candidate/
  session provenance and pre-publication runtime input hooks. Candidate lifecycle
  wiring is exercised using actual QML; no layout or formal Golden changed.
- Independent task review approved spec and quality after correcting canonical
  adapter identity, reentrant admission, per-lookup policy, cancellation notifications,
  private mutation/Save continuation and failed-thread-start ownership. Old Save
  cannot transact a replacement session. Actual durable runtime commit/failure hooks
  still run even if the Settings session was replaced during the transaction.
- Root's fresh guarded Windows ten-file run on the final frozen source: **364
  passed**, 3 existing Pydantic warnings, 8.02 seconds, no skips/xfail. It uses fake
  services/temporary stores and hard-forbidden real keyring/socket callbacks. It is
  not real API, model-quality, native visual or whole-product LOCAL acceptance.
- Historical evidence remains: the writer's prior combined run had **362 passed,
  1 WinError 5 setup failure** before the final failed-submit addition. Its exact
  failed setup node and the later focused retry are retained; cause is unestablished.
  The subsequent fresh root pass does not erase or reclassify that failure.
- Next is C1D's single production graph: intent-before-credentials bootstrap,
  immutable atomic catalog publication and truthful bounded Qt-owner cleanup. The
  existing engineering manifest is inert metadata only, not product resources or
  a readiness claim. Managed Watch and resources/UI remain unfinished gates.

Main checkout remains `4feb712`; no merge, push, release or formal Golden update.

## Managed runtime composition checkpoint — 2026-10-11

- `c367a2610ac717674256d0debb692ab7694619fb` composes one guarded runtime:
  intent-before-metadata-only startup, immutable catalog publication before public
  signals, exact-profile late credential reads, managed Batch/probes, one-way
  lifetime close and finite actual owner drain before Qt deletion. Default Watch
  remains an intentional unavailable development boundary pending C2; no saved
  Watch/history execution or rewrite occurs. The engineering catalog is inert,
  pinned metadata, not product model resources/readiness.
- Independent scoped spec and quality review approved. Root fresh focused Windows
  regression: **540 passed**, 3 existing warnings, 13.84 seconds. A reproduced
  close-save error changed from **2 failed** to **2 passed**; cleanup now retains
  owners and retries persistence rather than losing the partial-construction handoff.
- Initial direct PyInstaller invocation omitted the existing official build script's
  DLL-path filtering and companion manual copy. That artifact failed three genuine
  tests (**4183 passed, 3 failed, 3 skipped**): manual, ICU symbols and EXE smoke.
  No source/assertion change or test exclusion was used; rebuilding with the existing
  `scripts/build_windows.ps1` yielded **23 passed** packaging tests and isolated
  frozen smoke. Existing optional build warnings remain recorded.
- One intervening complete test process exited 1 at 100% progress without its final
  summary. Its cause remains unestablished; it is not counted as passing or attributed
  to Qt/GC/environment without evidence. Subsequent complete normal-GC Windows runs
  both finished with **4186 passed, 3 skipped**, 4 existing warnings: 80.92 seconds
  with faulthandler diagnostics and 80.22 seconds in an ordinary stability repeat.
  Both returned explicit pytest status 0. The earlier unexplained exit is retained.
- Complete unchanged screenshot comparison: **66 passed, 1 designed update-mode
  skip**, 86 existing Pillow warnings, 48.00 seconds. Acceptance: **186/186**.
  All verification used synthetic fixtures, isolated user data and fake credentials;
  real network/keyring callbacks were blocked before test/application imports.
- Current intermediate official-build EXE: 11,191,754 bytes, SHA-256
  `CE6B918645950E9AB4342E7DB36CB532DAA3C3CDC53F623F9649D560CCFF493B`.
  Package: 3141 files, 576,775,887 bytes. This is not a final local-privacy release;
  no model weights were packaged. Previous build hashes are historical, not expected
  values for this source.

Next: correct the synthetic-reproduced Undo history-save outcome loss, then the
shared serial file-operation lane and actual managed Watch, product resources/UI,
three-language manuals and real-model/native/package acceptance. No main merge,
push, release or formal Golden update occurred. Earlier failures remain recorded.

## Scoped review backlog

- P2: retain runtime/readiness invalidation independently of cancellation after
  cleanup; current service may report CANCELLED and retain READY after a token or
  resource failure. Each later invocation still repeats actual safety checks.
- P2: shutdown journal cleanup should re-raise KeyboardInterrupt/SystemExit after
  retaining ownership and reporting RECOVERY_REQUIRED.
- P2: dormant CacheManager restore should reject unsupported schema versions.
- P2: Windows intent candidate descriptor-conversion failure may orphan a mode-only
  temporary record; prior durable bytes remain intact. Add exact-handle cleanup
  before closing that conversion-failure branch.
- P2: the pinned runtime can lose missing-model exit logs; retain this upstream
  limitation. Do not replace managed self-check with the parsing diagnostic.
- P2: strengthen the native help option check to match a standalone `-f` option;
  the current substring check also occurs inside `--json-schema-file`. The real
  missing/malformed input negative tests already establish eager parsing behavior.
- P2: preparation deadline conversion of an enormous integer raises OverflowError
  before native allocation, rather than the fixed PreparationError category. No
  process, content leak or ownership loss occurs on that rejected input.
- Existing Pydantic class-config and Pillow deprecation warnings are maintenance
  items, not evidence that model semantics or privacy were validated.

## Boundaries

No real cloud API, key, Credential Manager or private input in verification. Model
operations use prepared synthetic text/images/pages/keyframes and the trusted
managed runtime. No system-security change, global network collection, formal
Golden update, push, release or unapproved feature expansion. Preserve source,
Git history, raw failures and current worktrees until reviewed integration.
