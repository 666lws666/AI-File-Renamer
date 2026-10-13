# Verified runtime inventory milestone

## Verdict

Runtime extraction/inventory service passes its scoped implementation review,
negative tests and actual pinned Windows archive verification. It does not
launch a model, enable local privacy mode or prove packaged runtime readiness.

Implementation `ab1d09e`; focused review fixes `b6cb3a7`.

## Test and review evidence

- Initial20 failures preceded implementation of the product inventory module.
- Source ZIP is hashed and parsed through the same held pinned stream. Complete
  archive validation and member hashing precede creation of the destination.
- Limits:68 flat safe members,64MiB expanded total,16MiB metadata-read bound,
  <=1MiB underlying read requests. The68-member limit leaves room within the
  existing80-member inference stage for weights/request/visual inputs.
- Existing partial prefixes are compared before append; corrupt finals or
  mismatching partials are preserved, never overwritten or silently truncated.
- Independent review identified raw zlib.error escaping on malformed DEFLATED
  bytes. A real broken compressed-block fixture with matching catalog ZIP hash
  reproduced the issue. A second RED test exposed an overflowing timeout integer.
  Both now produce fixed resource errors with no target/source corruption.
- Four deterministic no-sleep tests exercise archive-hash cancellation and
  verification/extraction/final-recheck deadlines, retaining recoverable files.
- Final six-suite result:198 passed,1 skipped in2.47s. The skip is the existing
  Windows symlink-creation privilege limit; native junction/hardlink tests still
  run. No security privilege or policy was changed to force the skip to run.
- Independent focused re-review approved specification compliance and quality.

## Actual pinned archive: PASS

Root QA used the previously verified owned resource cache, not a replacement or
downloaded test package. Native run
`runtime-inventory-native-dcd1e1bf0593498683bfa2ae1436af3e` produced:

-51 independently hashed members /46,749,981 expanded bytes;
-both required native entrypoints and `LICENSE-LLVM-OpenMP` retained;
-fresh second invocation reverified and returned an identical immutable inventory;
-source archive hash unchanged; no executable/model/network call made.

First extraction/verification took1.1003 seconds on this host; that is not an
inference performance promise. Exact results remain in the ignored local-privacy
QA run folder.

An earlier QA run (`runtime-inventory-native-bb55b90362ea4ec4895666c213fc347e`)
failed an incorrect root-test assumption: it expected case-sensitive ordering,
while the product deterministically sorts by(casefold(name),name). The initial
intent and failure record were retained. The QA expectation was corrected and
the full native check rerun in a fresh directory. No product code, assertions in
the committed suite, image tolerance or Golden was changed for that correction.

## Remaining integration

The returned paths alone are not trusted launch authorization. Product staging
must re-pin/re-hash them, use the fixed entries and preserve all dependencies.
Native helper promotion, product naming protocol, trusted coordinator, shared
cloud-dispatch/mode authority, UI/manuals and packaged acceptance remain. No main
checkout merge, push, public release, real cloud API or credential access occurred.
