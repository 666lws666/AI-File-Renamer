# DeepSeek V4.1 Flash — approved update

The Product Owner approved the preceding four-part proposal: update the default and selectable models, resolve actual image capability, update all three UI languages/manual, and verify/rebuild Windows. Continue inline in the current feature checkout as previously requested.

## Verified contract (2026-09-10)

Official sources: https://api-docs.deepseek.com/updates/ , https://api-docs.deepseek.com/guides/vision/ , https://api-docs.deepseek.com/quick_start/pricing/ . The canonical API name is `deepseek-flash`. Both `deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` are compatibility aliases routed to V4.1 Flash. All three support text, images/multiple images and JSON object output. Strict JSON schema is not claimed. V4 Pro stays text-only under this dated snapshot; its announced September 14 transition is not preemptively enabled by a local clock.

## Boundaries

Use one exact-model capability source for presets and adapter validation. Preserve official endpoint enforcement, unknown-model fail-closed behavior, connection verification and request-level downgrade checks. Custom gateways do not inherit official capabilities from a model-name string. New default configuration uses `deepseek-flash`; existing saved models/credentials are never rewritten automatically. Upgrading an existing selection requires testing and saving the candidate.

Keep local image preprocessing and existing conservative 8-image/byte/dimension limits. Upload only prepared inline images in user messages. Scan pages and video keyframes use the same pipeline; never send complete PDF/video files or source paths. No new Files API or external-image-URL support.

The form lists canonical Flash, V4 Pro, old Vision alias and old Flash alias with explicit labels. Three languages explain that the aliases now route to V4.1 Flash; unknown models remain unverified. Remove outdated experimental-only claims. Retire stale DeepSeek numeric prices from current preset evidence (UNKNOWN/empty), without implementing price UI or re-auditing other providers.

## Verification

Test the new canonical model and both aliases through actual adapters with a fake transport; image, multiple scan/video frames, structured JSON, model overrides, unknown/Pro/forged gateway rejection, and retained saved config. Test QML selection/capability changes without real credentials. Native three-language form captures go only to ignored qa-current; no Golden updates. Full non-screenshot and screenshot pytest, acceptance, rebuilt EXE packaging/smoke, and a scoped local commit finish this update. No real API/Key/Credential Manager, push or release.
