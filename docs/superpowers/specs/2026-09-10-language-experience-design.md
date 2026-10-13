# Language experience — approved scope

Product Owner approved Hong Kong Traditional Chinese and cancel rollback, then requested a filename-language prompt and autonomous completion while offline. Continue in the current checkout as previously requested; no parallel writer owns existing product files.

## Interface language

Support zh-CN, en-US and zh-HK (persisted aliases zh_CN, en_US, zh_HK). Language preview is immediate. Save commits it; cancel/discard restores the latest successfully saved language, including after Save followed by another edit. Failed saves keep the draft and preview. Existing user configuration is not rewritten merely by opening Preferences. A dedicated zh_HK.json catalog covers all existing keys and format placeholders using Hong Kong wording (檔案、資料夾、設定、影片). Built-in template display names/descriptions have HK labels; user-created/edited names, vocabulary and filenames are never automatically converted.

## Filename output language

Interface and filename languages are independent. Before files/folders/dropped URLs enter the Batch analysis queue, show a confirmation dialog with the selected template and filename-language choice. Default is Follow template (with the effective language displayed). Explicit choices: Simplified Chinese, Traditional Chinese (Hong Kong), English, Japanese and Spanish. Confirm starts analysis; cancel performs no import or AI call. The selection affects this import and subsequent imports in the current session, without modifying the template or existing suggestions/files. Pending task requests capture template/language at enqueue time; later choices cannot change an already queued operation. Retry retains the task's recorded choices. Watch continues to use its template's output language; HK is also offered in Template Editor.

ProviderRequest.locale must be derived from the selected filename language/template, never AppConfig.language. Values zh/en/ja/es map to zh-CN/en-US/ja-JP/es-ES; zh-HK stays zh-HK. Provider structured-field instruction remains authoritative; no post-hoc whole-filename translation is attempted. Extension/identifier safety remains unchanged.

## Verification and non-goals

Test resource key/placeholder parity, alias/save/cancel/reopen behavior, user text preservation, import cancellation, per-task language isolation and actual fake Provider request locale. Native Windows screenshots in ignored qa-current/language-experience only, at 1000x700 and 900x640, with fake credentials and local fixtures. Existing 38 M1/other Golden files remain untouched; new dialog is invisible in old cases and has dedicated dynamic tests. No price features, real APIs/credentials, push or release. Rebuild EXE, inspect packaged locale/dialog resources and isolated smoke; update offline manual.
