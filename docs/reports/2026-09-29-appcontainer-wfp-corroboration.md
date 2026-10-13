# Scoped Windows network-block evidence and experiment continuation

## Verdict

The original socket-code probe remains **FAILED**: the contained loopback connect
timed out instead of returning WSAEACCES/10013. Independent inspection of existing
Windows Filtering Platform records supports a narrower conclusion: the
synthetic loopback attempt was blocked by AppContainer isolation on the receiving
side. This permits a controlled model-compatibility experiment, not a declaration
that the local privacy feature or arbitrary network denial is complete.

## Evidence examined

Ignored evidence root: `tests/screenshots/qa-current/local-privacy/`.

- Read-only query run: `wfp_ffe1b0985f1daa2d2cb376cbb4d8f47e`.
- Native access run: `access_78c9c7b309dd4e0850b61ff98b4be981`.
- Contained interval: 2026-09-29 11:42:45.131259–11:42:47.220896 UTC.
- Held ordinary listener: TCP `127.0.0.1:51578`.
- Two matching WFP events: 11:42:45.193Z and 11:42:46.199Z, source port 51580,
  destination listener port 51578, inbound loopback, PUBLIC_CLASSIFY_DROP,
  FWP_ACTION_BLOCK, filter 115478, layer 44, AppContainer Loopback origin,
  FWPP_SUBLAYER_INTERNAL_FIREWALL_APP_ISOLATION sublayer.
- The events name the receiving Python process (PID 4004), not the initiating
  contained process. Package SID is S-1-0-0. Do not describe these records as a
  direct child-SID attestation; correlation uses the held random port, bounded
  time window, synthetic attempt and positive control. Parent PID was not
  separately persisted in the correlation record.
- Parent token verification records the exact intended package SID,
  AppContainer=true, zero capabilities. Read-only exemption enumeration found
  zero entries. The ordinary control read both fixtures and received the exact
  26-byte listener nonce/EOF. The contained child read the allowed fixture,
  received file access error 5 for the denied fixture, external literal TEST-NET
  connect error 10013, and loopback timeout with zero sent bytes.
- Native process exited 0 and exact-owned cleanup completed. The journal's
  outcome remains failed/contained_access; completed state denotes cleanup, not
  assertion success. Raw contained stdout retains the measurements rejected by
  the strict validator.
- `events-remote.xml` is empty. That query filtered loopback remoteport=51578;
  it was not an external-endpoint observation and cannot show external silence.

## Scope and integrity

The user authorized administrator **read-only** verification of this synthetic
test. NETEVENTS was already on. The ordinary parent/probe remained non-admin;
only the reader was elevated. No collection enabling, capture start, security
setting, firewall rule or loopback exemption mutation was performed. No further
external-endpoint query was executed. The attempted extension was rejected by
the permission reviewer and was not applied or bypassed.

| Artifact | SHA-256 |
| --- | --- |
| events-local.xml | 85f9daa50101b0e0b09655cf08390c789537e437c21bc6f9be0ed4cddd1f3a74 |
| events-remote.xml | 6b73aad5e89faa8083c1b8243864e33dc9e9413dd08e4e8d970d496c5692551c |
| probe-correlation.json | b1aaf859935ef5e8e8ce6470d2c786f29a975c34ff0c8fde7a7299c3f3550c8e |
| reader result.json | 2105612027599c4b39e3aa99bd5363f6d00b724eb41a57d7f13c5179fc3a8e82 |
| compiled access probe | 6a5d88e50c9204fbb7361fac50f420dac87dd6f503543e4a5421070503f806d0 |

The fixed read-only query helper's focused tests ran: **12 passed**. These tests
verify bounded query behavior, not OS enforcement. An independent read-only
security review agreed that the raw evidence supports the bounded interpretation
above. The strict validator and its failure semantics are unchanged.

## Next milestone and remaining gates

Use the pinned llama.cpp/Qwen resources in a new, exact-owned read-only stage;
verify the contained process token before resume; run only reviewed synthetic
text and image inputs with a bounded Job; inspect actual output and cleanup.
Never retry outside containment on failure. Compatibility results are distinct
from semantic quality and from product privacy readiness.

Still unverified: actual model compatibility inside containment, product resource
manager/download/import lifecycle, shared Batch/Watch mode-switch exclusion,
cache/log/temp boundaries, beginner-facing UI and manuals for local mode,
packaged end-to-end privacy behavior. No cloud API/credentials/private data,
Golden change, merge, push or release occurred in this evidence step.
