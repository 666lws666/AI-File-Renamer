# Local-mode integration inventory (read-only)

This is a source inventory at `02d1e0d3247e114dc6e395efe9dc87f2dafa5852`, not an implementation plan or a privacy gate pass. It was collected while the independent diagnostic text-evidence task was running. Product integration remains gated on real model quality and a demonstrated managed process boundary.

## Actual production routes

- `src/qml_bootstrap.py:99` builds the production BatchAnalysisService. Its profile callback selects the active verified/enabled cloud profile; its credential callback reads the provider credential account. The adapter factory binds OpenAICompatibleAdapter.
- `src/qml_bootstrap.py:314` and `:323` inject the same analysis service into ReviewFirstHandler and AutoApplyHandler. A local-mode switch must therefore cover both Watch handlers, not only Batch admission or the selected page.
- `src/core/batch_analysis.py:137` implements Batch analysis. It selects profile and credential before extraction, prepares text/visual payloads, builds ProviderRequest, then invokes the adapter at `:224`. Cancellation checks are not currently processing-mode checks. Local processing must not require a cloud profile or credential read.
- The Watch adapter in `src/core/batch_analysis.py:90` currently invokes the same service using template naming. Existing Watch naming choices must be preserved rather than silently converted when a global processing mode is added.
- `_prepare_visuals` in that module currently uses `allow_vision_cloud` / `allow_video_keyframes_cloud` consent flags. A future local path must separate local preprocessing permission from consent to upload, while retaining the existing cloud behavior.
- `src/providers/openai_compatible.py:630` invokes the provider through RetryExecutor. Each retry reaches `_send_transport` at `:705`, then the injected transport at `:722`. The real urllib boundary is `UrllibJsonTransport.send` at `:161`, opening the request at `:180`. A check only when a task is admitted is insufficient for queued work or retry after a local-mode switch.
- `invoke_probe` at `:661` sends fixed ping data without file content. Local mode still needs a clearly separate explicit connection-test consent/behavior; a generic localhost address cannot establish a trusted local runtime.

## Cache observations

`CacheContext` currently includes content hash, provider profile/provider/model, quality, template/vocabulary versions, locale, preprocessing and requested-schema versions. It has no explicit processing-mode or verified local-resource fingerprint. A future local integration must distinguish these contexts and never treat a prior cloud entry as proof of local execution. Source search found no production `CacheContext(...)` / `CacheManager(...)` construction in `src` at this baseline; do not describe the cache service's existence as proof that the production analysis pipeline already uses it.

## Required future negative evidence

After prerequisite gates: switch during extraction, before first send, during retry backoff, with both Watch handlers active, and during local failure/cancellation. Verify no later cloud dispatch; accurately distinguish already-dispatched requests that cannot be recalled. No automatic cloud fallback or cloud credential read on the local path. Resource downloads use a separate manifest-only channel and cannot receive content, source names or paths. Cache, temporary files and diagnostics require their own context/data-lifetime checks.

No product source, settings, credentials, network requests or runtime state were changed for this inventory.
