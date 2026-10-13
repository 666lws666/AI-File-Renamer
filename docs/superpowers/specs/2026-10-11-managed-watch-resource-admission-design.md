# Managed Watch resource admission design

Approved autonomous product scope; source dependency6b3dbbc86fd7a46ce59c6fcbe5de167cf2384f95. This bounded design does not activate production Watch.

## Context and chosen approach

The reviewed resource guard has exact pending/execution receipts. The reviewed ingress owns an input from before catalog capture through actual capture/post/public-consumer tails, but does not reserve a guard receipt. Reuse that existing ingress owner rather than adding a second queue or accepting a caller's count subtraction.

Alternatives considered: a separate resource queue duplicates authenticity/retirement; a post-capture count check admits unaccounted work and misses callback tails. Chosen: reserve a genuine pending receipt before capture_work, retain it in the exact ingress owner, retire only at existing actual-tail retirement.

## Admission and denial

Optional exact WatchResourceGuard preserves the existing standalone constructor without a guard; that old path is not resource-protected production permission. Raw admission has no trusted size yet: reserve size0 as metadata-only ownership, not a claim about actual file length. No filesystem, inference, credential or transport operation is added.

A denied reservation or ingress input-capacity overflow produces at most one authentic WatchAdmissionFailure per watch-id/incarnation, not a FileTask or fake stable fingerprint. These notices have their own finite cap1000, no pending guard receipt, no work/source payload, and the original authority snapshot. A pending duplicate notice coalesces; an allowed fresh admission is not blocked just because an older notice remains. Notice ownership counts toward actual ingress idle until capture/post/consumer tails finish. Queue-full input remains on disk; later production UI must explain it was not added and allow deliberate retry/rescan. This step cannot promise every overflowed file is retained in memory or has been analyzed.

## Lock and lifetime rules

reserve_pending executes outside ingress lock because clock/contributors may reenter ingress. The prospective owner remains capturing during that call, so close cannot remove it or lose a returned token. Assign the returned exact receipt before checking close; finally retires it if closed/stale.

release_pending is the reviewed canonical primitive-only, no-callback method, safe during exact locked pruning. If it returnsFalse (e.g. an execution still owns that pending receipt), retain ingress owner and issued identity; count/idle may retry primitive pruning later, never report false idle. Do not register ingress owned counts as a contributor on the same guard: its ledger already includes the receipts.

No callback, source I/O, arbitrary observer method or capture_work under ingress lock. Genuine denied notice still crosses the existing exact post_failure protocol, never fabricated content understanding.

## Boundaries

This step only connects pending admission. It cannot grant execution, recover ResourcePaused, resume an observer, persist a result, Apply/Undo, or activate production Watch. The next delivery task must acquire execution using the authentic stable fingerprint before body submission, retain it through Future/bridge/ack/publication tails, and map genuine resource notices visibly. Durable Review/AutoApply/shared file lane/self-events/runtime and resources/UI/model/manual/package remain separate integration Gates. Prior unexplained native Qt GC crash remains open.

## Acceptance

Synthetic actual catalog/authority/guard with native no-network/no-credential runner: reserve-before-capture, limit1 concurrent admission, bounded/coalesced denial, new allowed input despite pending notice, no fake work or I/O, capture/clock/post-tail close races, callback reentry without ingress-lock deadlock, forged/stale event rejection, exact repeated retirement, guard execution refusal preserving pending owner, finally cleanup and original ingress/lifecycle regressions. Independent scoped review and root frozen sequential full/screens/acceptance before local checkpoint. No main change, Golden update, model/network/CM/firewall, merge or push.
