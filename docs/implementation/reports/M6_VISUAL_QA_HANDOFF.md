# M6 Visual QA Handoff — Screenshot Verification Checklist

> **Status: PENDING Codex visual review.** This document lists every
> state / scenario that requires screenshot verification.  No visual
> assertion has been run yet; none is claimed passing.

---

## Preferences Page — zh_CN

- [ ] `prefs_zh_top` — 页面顶部（标题 + General 卡片上部可见）
- [ ] `prefs_zh_scrolled` — 滚动至页面底部（Diagnostics 卡片可见）

## Preferences Page — en_US

- [ ] `prefs_en_top` — Page top with English locale
- [ ] `prefs_en_scrolled` — Scrolled to bottom, English

## General Settings Card

- [ ] `general_valid` — All fields at default values
- [ ] `general_invalid` — Max file size set to 0 or 1000 (out of range), error visible

## Provider Settings Card

- [ ] `provider_five_presets` — Five preset providers displayed (DeepSeek, Qwen, MiMo, Zhipu, Kimi)
- [ ] `provider_qwen_recommended` — Qwen shows "推荐" badge
- [ ] `provider_deepseek_no_vision` — DeepSeek has no vision capability chip, only text + JSON
- [ ] `provider_mimo_json_unverified` — MiMo structured JSON shows "未验证"
- [ ] `provider_custom_form` — Custom provider form open (name, baseUrl, model, apiKey fields)
- [ ] `provider_key_configured` — Key is saved (shows "已配置") but apiKey field is empty
- [ ] `provider_key_not_configured` — No key saved (shows "未配置")
- [ ] `provider_test_success` — Connection test result: success ("连接成功")
- [ ] `provider_test_failure` — Connection test result: failure ("连接失败")

## Quality Card

- [ ] `quality_modes` — Three radio buttons visible (经济/均衡/高质量) with descriptions

## Resource Limits Card

- [ ] `resource_limits` — All spinners with valid ranges visible

## Privacy Card

- [ ] `privacy_toggles` — Three toggles + video keyframe notice text visible
- [ ] `privacy_video_notice` — Video notice explicitly states "完整视频文件不会上传"

## Cache Card

- [ ] `cache_defaults` — Enabled toggle, capacity, TTL, current usage, clear button
- [ ] `cache_clear_success` — After clear: "缓存已清理" feedback
- [ ] `cache_clear_failure` — Clear failure: "缓存清理失败" feedback

## Usage Card

- [ ] `usage_empty` — No data: "暂无使用数据" empty state
- [ ] `usage_with_data` — Mock data visible: requests, tokens, etc.

## Diagnostics Card

- [ ] `diag_default` — Export button + description; if service not connected: "诊断服务尚未连接"

## Save / Cancel

- [ ] `save_success` — After successful save: dirty=false, feedback shown
- [ ] `save_failure` — Save error state: dirty=true, error text visible, page stays open

## Unsaved Changes Dialog

- [ ] `unsaved_dialog` — Three-option dialog: Save and Leave / Discard / Continue Editing

---

**Total scenarios**: 25
**Screenshot/Golden verification**: Not yet executed — delegated to Codex
