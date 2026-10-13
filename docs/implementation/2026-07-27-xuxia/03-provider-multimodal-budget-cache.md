# M3: Provider, Multimodal, Budget & Cache Implementation Plan

> 本计划供 Claude Code 在 Product Owner 明确批准后逐任务执行。当前编写计划不构成实施授权。

**Goal:** 实现可替换 Provider 架构、单一当前 Provider 路由、多模态预处理（图片/扫描件/视频）、经济/均衡/高质量模式、预算 fail-closed、本地多上下文哈希缓存和用量记录。隔离或安全淘汰旧 OpenAI/Claude Provider。

**Architecture:** `src/core/provider_manager.py` 管理 Provider Profile；`src/core/capability_router.py` 检测能力并路由；`src/providers/` 下每个 Provider 实现统一协议。预算/缓存/用量为独立服务模块。

**Tech Stack:** keyring, httpx, Pillow, PyMuPDF, opencv-python (关键帧), pytest

**Authority:** XUXIA_DETAILED_DESIGN §15 Provider, §16 Quality Modes, §17 Image/Scan/Video, §18 Budget, §19 Cache, §20 Privacy, §26 Security.

**Prerequisites:** M2 全部通过。

**Global Constraints:** 单一当前 Provider；不跨供应商隐式调用；OpenAI/Anthropic 不作为品牌预设；Key 仅存 Credential Manager；预算 fail-closed。

---

## Task 1: Provider Official Capability Verification

**Purpose:** 在任何 preset、Base URL、model、capability、adapter 实现之前核验五个首期 Provider。只使用各 Provider 官方开发者文档。无法确认的 Provider 必须停止，不得标记为"可用"或编造数据。

**Files:**
- Create: `docs/implementation/reports/M3_PROVIDER_CAPABILITY_VERIFICATION.md`（未来执行 M3 时创建）
- Test: `tests/unit/test_provider_verification.py`

**Interfaces:**
- Produces: `ProviderVerificationResult(provider, base_url, auth_method, openai_compat_level, text_capable, json_capable, vision_capable, model_list_method, timeout_semantics, rate_limit_semantics, error_semantics, usage_field, price_verifiable, verification_date, official_sources)` — 每个 Provider 一份

**Steps:**
- [ ] 对 DeepSeek/Qwen/MiMo/智谱/Kimi 逐一执行官方文档核验
- [ ] 逐项记录：官方 Base URL、鉴权方式、OpenAI-compatible 程度、文本能力、JSON/structured output 能力、视觉能力、模型列表获取方式、timeout/rate-limit/error 语义、usage 字段文档、核验日期、官方来源链接
- [ ] 无法从官方资料确认协议或能力的 Provider → M3 在该 Provider 上停止，不得标记为可用，报告 Product Owner 决策
- [ ] 不得使用非官方来源
- [ ] 不得把 Claude Code 当前模型当作序匣产品模型
- [ ] 运行: `pytest tests/unit/test_provider_verification.py -v`

**Verification:** 五 Provider 均有核验记录；未通过者被标记为不可用。

**Failure/Stop:** 任一 Provider 官方资料不可得 → 该 Provider 停止，不得后续实现 preset/adapter。

**Commit:** `docs: add M3 provider capability verification`

---

## Task 2: Safe Provider Protocol & Prepared Payload Types

**Purpose:** 定义安全的 ProviderRequest/Response 协议。ProviderRequest 不接受 raw files、路径、file handle、完整视频或未经预处理的原始二进制。visual_payload 只能由本地预处理服务生成。

**Files:**
- Create: `src/core/provider_protocol.py`, `src/core/provider_profile.py`
- Test: `tests/unit/test_provider_protocol.py`

**Interfaces:**
- Produces: `ProviderCapabilities(text, vision, structured_json)`
- Produces: `ProviderProfile(id, name, adapter, base_url, model, capabilities, timeout, retry, enabled)`
- Produces: `ProviderRequest(request_id, task_id, extracted_text: str|None, metadata: dict, visual_payloads: tuple[PreparedVisualPayload,...], requested_schema, quality_mode, locale, model, timeout, correlation_id)` — 不接受 source_path/open file handle/任意原始二进制/完整视频
- Produces: `PreparedVisualPayload(kind: resized_image|rendered_scan_page|video_keyframe, mime_type, data: bytes, content_digest, width, height, source_index, preprocessing_version)` — 只能由本地预处理服务生成
- Produces: `ProviderResponse(fields, usage, latency, model_used)`

**Steps:**
- [ ] 编写 test_provider_request_no_source_path() — 构造不接受 source_path
- [ ] 编写 test_provider_request_no_file_handle() — 不接受 open file handle
- [ ] 编写 test_visual_payload_only_from_preprocessor() — 只能由预处理服务生成
- [ ] 编写 test_request_rejects_raw_video() — 拒绝完整视频
- [ ] 编写 test_request_rejects_unprocessed_image() — 拒绝未缩放原始图片
- [ ] 编写 test_profile_serialization_no_key() — 序列化不含 api_key
- [ ] 实现 ProviderCapabilities, ProviderProfile, ProviderRequest, ProviderResponse, PreparedVisualPayload
- [ ] 运行: `pytest tests/unit/test_provider_protocol.py -v`

**Verification:** 所有安全约束类型测试通过。

**Commit:** `feat: add safe Provider protocol and payload types`

---

## Task 3: RetryPolicy & RetryExecutor

**Purpose:** 为 Provider Adapter 提供统一、有界、可测试的重试执行器。位于 Adapter 实现之前。

**Files:**
- Create: `src/services/retry_policy.py`, `tests/unit/services/test_retry_policy.py`

**Interfaces:**
- Produces: `RetryPolicy(max_retries, backoff_base, backoff_max, retryable_codes)`
- Produces: `RetryDecision(should_retry, delay_seconds, reason)`
- Produces: `RetryExecutor.execute(operation, policy, cancellation_token) → Result`
- 结构化 AppError 映射到 retryable/non-retryable

**Steps:**
- [ ] 编写 test_401_403_not_retryable() — 认证错误不重试
- [ ] 编写 test_model_not_found_not_retryable() — 模型不存在不重试
- [ ] 编写 test_429_respects_retry_after() — 遵守 Retry-After header 或有界退避
- [ ] 编写 test_timeout_retryable() — timeout 可重试
- [ ] 编写 test_network_error_retryable() — 网络错误可重试
- [ ] 编写 test_5xx_retryable() — 5xx 可重试
- [ ] 编写 test_malformed_json_limited_retry() — JSON 解析失败有限重试
- [ ] 编写 test_max_retries_exhausted() — 最大次数耗尽后返回失败
- [ ] 编写 test_cancellation_stops_immediately() — 取消立即停止
- [ ] 编写 test_no_cross_provider_retry() — 不在重试中切换 Provider
- [ ] 编写 test_no_silent_model_switch() — 不静默切换模型
- [ ] 编写 test_usage_recorded_per_attempt() — 每次尝试记录 usage
- [ ] 注入 clock/sleeper — 测试不得真实 sleep
- [ ] 运行: `pytest tests/unit/services/test_retry_policy.py -v`

**Verification:** 所有重试/不重试场景正确，无真实等待。

**Commit:** `feat: add RetryPolicy and RetryExecutor`

---

## Task 4: Provider Manager & Single Active Provider

**Purpose:** 管理多 Provider Profile 和当前激活 Provider。

**Files:**
- Create: `src/core/provider_manager.py`, `tests/unit/test_provider_manager.py`
- Modify: `src/config.py` — 添加 Provider 配置节

**Steps:**
- [ ] 编写 test_add_profile_persists_metadata_no_key() — JSON 保存不含 Key
- [ ] 编写 test_set_active_switches_provider() — 切换后 get_active 返回新 Provider
- [ ] 编写 test_key_saved_to_credential_manager() — Key 进 Credential Manager
- [ ] 编写 test_legacy_airenamer_migration() — 检测旧 AIRenamer 凭据并迁移
- [ ] 编写 test_remove_profile_cleans_credential() — 删除 profile 同时删除凭据
- [ ] 实现 ProviderManager
- [ ] 运行: `pytest tests/unit/test_provider_manager.py -v`

**Verification:** 多 Profile 管理、切换、凭据迁移和删除功能正常。

**Commit:** `feat: add ProviderManager with single active provider`

---

## Task 5: Five Provider Presets & Custom Provider

**Purpose:** 五首期预设 + Custom Provider。不提供 OpenAI/Anthropic 品牌预设。

**Files:**
- Create: `src/core/provider_presets.py`, `tests/unit/test_provider_presets.py`

**Steps:**
- [ ] 编写 test_five_presets_loadable() — DeepSeek/Qwen/MiMo/智谱/Kimi
- [ ] 编写 test_qwen_marked_recommended_not_forced() — Qwen 推荐标记非强制
- [ ] 编写 test_no_openai_anthropic_preset() — 不含 OpenAI/Anthropic
- [ ] 编写 test_custom_provider_config() — 用户填写后创建
- [ ] 编写 test_preset_defaults_from_verification() — 默认值来自 Task 1 核验
- [ ] 实现 provider_presets.py
- [ ] 运行: `pytest tests/unit/test_provider_presets.py -v`

**Verification:** 五预设 + Custom 可加载；无 OpenAI/Anthropic；Qwen 推荐非强制。

**Commit:** `feat: add five first-phase provider presets and custom provider`

---

## Task 6: Legacy OpenAI/Claude Provider Isolation

**Purpose:** 保留但不暴露旧 Provider 为首期预设。

**Files:**
- Modify: `src/providers/factory.py` — 标记 _LEGACY
- Test: `tests/unit/test_legacy_provider_isolation.py`

**Steps:**
- [ ] 编写 test_legacy_not_in_presets() — 预设不含 OpenAI/Claude
- [ ] 编写 test_legacy_still_importable() — 旧代码不破坏
- [ ] 编写 test_legacy_not_in_ui() — UI 预设下拉不含
- [ ] 实现隔离标记

**Verification:** 旧 Provider 可导入但不出现在预设；UI 下拉不含 OpenAI/Claude。

**Commit:** `refactor: isolate legacy OpenAI/Claude providers`

---

## Task 7: OpenAICompatibleAdapter & Five-Preset Contract Path

**Purpose:** 一个通用 OpenAICompatibleAdapter + 五个预设的完整合约路径。不允许只实现 DeepSeek/Qwen 而把 MiMo/智谱/Kimi 标为可用。

**Files:**
- Create: `src/providers/openai_compatible.py`, `src/providers/presets.py`
- Test: `tests/providers/contracts/test_deepseek_contract.py`
- Test: `tests/providers/contracts/test_qwen_contract.py`
- Test: `tests/providers/contracts/test_mimo_contract.py`
- Test: `tests/providers/contracts/test_zhipu_contract.py`
- Test: `tests/providers/contracts/test_kimi_contract.py`
- Test: `tests/providers/contracts/test_custom_provider_contract.py`

**Steps:**
- [ ] 实现 OpenAICompatibleAdapter：通用请求映射、响应解析、鉴权、错误映射、usage 解析
- [ ] 五预设分别配置经 Task 1 核验的映射
- [ ] 每个预设：请求合约测试、响应解析测试、错误映射测试
- [ ] Custom Provider 合约测试
- [ ] 若 Task 1 发现某 Provider 协议不能由通用 Adapter 表达 → 增加专用 Adapter（Stop/Gate，不得跳过）
- [ ] 不为 OpenAI/Anthropic 创建品牌预设
- [ ] 调用 Task 3 RetryExecutor
- [ ] 单一当前 Provider，不跨供应商
- [ ] 运行: `pytest tests/providers/contracts/ -v`

**Verification:** 五 Provider + Custom 合约测试全部通过；通用 Adapter 正确映射所有已核验配置。

**Commit:** `feat: add OpenAICompatibleAdapter with five-preset contract path`

---

## Task 8: Connection Test & Capability Detection

**Purpose:** 连接测试分层结果和能力自动检测。

**Files:**
- Create: `src/core/connection_test.py`, `tests/unit/test_connection_test.py`

**Steps:**
- [ ] 编写 test_connection_success() — 200 → success
- [ ] 编写 test_connection_401() — 401 → auth_error
- [ ] 编写 test_connection_timeout() — timeout → network_error
- [ ] 编写 test_capability_text_only() — 模型无视觉 → vision=false
- [ ] 实现 ConnectionTest, CapabilityDetector

**Verification:** 连接测试分层结果正确；能力检测准确。

**Commit:** `feat: add connection test and capability detection`

---

## Task 9: Quality Mode Within Current Provider

**Purpose:** 在当前 Provider 内实现经济/均衡/高质量。

**Files:**
- Create: `src/core/quality_router.py`, `tests/unit/test_quality_router.py`

**Steps:**
- [ ] 编写 test_economy_stricter_limits() — 经济模式限制更严
- [ ] 编写 test_balanced_is_default() — 默认均衡
- [ ] 编写 test_quality_allows_higher() — 高质量更高上限
- [ ] 编写 test_single_model_honest_label() — 单模型诚实标注
- [ ] 编写 test_no_cross_provider() — 不跨 Provider
- [ ] 实现 QualityRouter

**Verification:** 三模式在当前 Provider 内正确路由；不跨供应商。

**Commit:** `feat: add quality mode within active provider`

---

## Task 10: Low-Confidence Retry Within Current Provider

**Purpose:** 低置信度在当前 Provider 内自动升级重试。

**Files:**
- Create: `src/core/confidence.py`, `tests/unit/test_confidence_retry.py`

**Steps:**
- [ ] 编写 test_low_confidence_triggers_retry() — 全部 unknown → 重试
- [ ] 编写 test_retry_stays_in_provider() — 不跨 Provider
- [ ] 编写 test_exhausted_reports_failure() — 重试耗尽标记失败
- [ ] 编写 test_high_confidence_skips() — 高置信度不重试
- [ ] 实现 ConfidenceEvaluator

**Verification:** 低置信度在当前 Provider 内重试；不跨供应商；高置信度跳过。

**Commit:** `feat: add low-confidence retry within provider`

---

## Task 11: Image Preprocessing

**Purpose:** 图片本地缩放和压缩。

**Files:**
- Create: `src/services/media/image_preprocessor.py`, `tests/unit/media/test_image_preprocessor.py`

**Steps:**
- [ ] 编写 test_resize_max_long_edge() / test_resize_max_pixels() / test_compress_max_bytes() / test_format_conversion()
- [ ] 编写 test_limits_from_config() — 配置驱动
- [ ] 实现 ImagePreprocessor → PreparedVisualPayload
- [ ] 运行: `pytest tests/unit/media/test_image_preprocessor.py -v`

**Verification:** 缩放/压缩/格式转换正确；配置驱动限制。

**Commit:** `feat: add image preprocessing`

---

## Task 12: Scanned PDF Page Renderer (PyMuPDF)

**Purpose:** 使用 PyMuPDF 将扫描 PDF 受限页面渲染为内存图像。

**Files:**
- Create: `src/services/media/pdf_renderer.py`, `tests/unit/media/test_pdf_renderer.py`
- Create: `tests/fixtures/pdf/` — 测试 fixture 目录
- Modify: `requirements.txt` — 未来 M3 实施时增加并锁定经环境验证的 PyMuPDF 版本

**Steps:**
- [ ] 编写 test_text_pdf_page_rendered() — 真实文字 PDF 页面渲染
- [ ] 编写 test_scan_pdf_page_rendered() — 真实扫描 PDF 渲染
- [ ] 编写 test_multi_page_limit() — 多页限制
- [ ] 编写 test_encrypted_pdf_handled() — 加密 PDF 返回结构化错误
- [ ] 编写 test_corrupt_pdf_handled() — 损坏 PDF 返回结构化错误
- [ ] 编写 test_oversized_page_handled() — 超大页面受控
- [ ] 编写 test_render_exception_structured_error() — 渲染异常 → AppError
- [ ] 编写 test_output_dimensions_limited() — 输出尺寸受限
- [ ] 编写 test_output_payload_no_source_path() — 不含源路径
- [ ] 编写 test_output_payload_no_full_pdf() — 不含完整 PDF
- [ ] 实现 import fitz；打开 PDF；渲染受限页面为 pixmap；转换为 PreparedVisualPayload
- [ ] 渲染后限制宽、高、像素总量和内存
- [ ] 不上传原 PDF
- [ ] 运行: `pytest tests/unit/media/test_pdf_renderer.py -v`

**Verification:** 渲染输出非空、MIME 正确、尺寸受限、页面索引正确、无原 PDF 数据。

**Commit:** `feat: add PyMuPDF scanned PDF page renderer`

---

## Task 13: Video Keyframe Extraction

**Purpose:** 本地抽取约 4–8 个代表性关键帧。

**Files:**
- Create: `src/services/media/keyframe_extractor.py`, `tests/unit/media/test_keyframe_extractor.py`

**Steps:**
- [ ] 编写 test_extract_representative_frames() — 4–8 帧
- [ ] 编写 test_frame_count_respects_config() — 配置上限
- [ ] 编写 test_quality_mode_affects_count() — 质量模式影响帧数
- [ ] 编写 test_extraction_failure_graceful() — 抽帧失败不崩溃
- [ ] 编写 test_full_video_not_uploaded() — 只发送帧
- [ ] 实现 KeyframeExtractor → PreparedVisualPayload

**Verification:** 4–8 代表性关键帧；配置/质量模式约束；不上传完整视频。

**Commit:** `feat: add video keyframe extraction`

---

## Task 14: Capability Degradation

**Purpose:** Provider 无视觉能力时明确降级。

**Files:**
- Create: `src/core/degradation.py`, `tests/unit/test_degradation.py`

**Steps:**
- [ ] 编写 test_vision_unavailable_image_degrades() / test_vision_unavailable_video_degrades() / test_degraded_task_shows_indicator() / test_text_still_works()
- [ ] 实现 DegradationHandler

**Verification:** 无视觉能力时正确降级；文本不受影响；UI 显示降级 Chip。

**Commit:** `feat: add capability degradation`

---

## Task 15: ResourceGuard（替代已取消的金额预算）

**Purpose:** 以非货币语义限制并发、队列、文件大小、页面/帧数和失败重试。

**Files:**
- Create/Modify: `src/core/watch_resource_guard.py`, `tests/unit/test_watch_resource_guard.py`

**Steps:**
- [x] 实现全局与每 Watch 的待处理、并发和文件大小上限
- [x] 实现失败退避、冷却、手动暂停与安全恢复
- [x] 支持 Review First / Auto Apply 多来源 pending 计数累加
- [x] 达到上限时 fail-closed，并返回稳定 reason code

**Verification:** 资源超限阻止新工作；不会被表述或实现为金额预算。

**Commit:** `feat: replace monetary budget with watch resource guard`

---

## Task 16: Usage Recorder

**Purpose:** 用量记录。

**Files:**
- Create: `src/core/usage.py`, `tests/unit/test_usage.py`

**Steps:**
- [ ] 编写 test_record_api_call() / test_daily_monthly_aggregation() / test_group_by_provider_model_type() / test_cache_hit_separate() / test_no_key_no_body()
- [ ] 实现 UsageRecorder

**Verification:** 用量记录完整；缓存命中独立统计；不含 Key/正文。

**Commit:** `feat: add usage recording`

---

## Task 17: Cost Estimator（已取消，不进入产品）

**Product Owner 决策:** 序匣不展示价格、币种、费用估算、账单或金额预算。历史实验模块、价格资源和测试在 M8 发布收口时删除；不得重新接入 UI 或运行时。

**Verification:** 发布源码中不存在 `CostEstimator`、`BudgetManager` 或 Provider 价格资源；UsageRecorder 仅记录非货币调用统计。

---

## Task 18: Cache Manager

**Purpose:** 本地多上下文哈希缓存。

**Files:**
- Create: `src/core/cache_manager.py`, `tests/unit/test_cache_manager.py`

**Steps:**
- [ ] 编写 test_cache_hit_same_context() / test_cache_miss_changed_template() / test_cache_miss_changed_model() / test_invalidation_reason_logged() / test_cleanup_by_size() / test_no_api_key()
- [ ] 实现 CacheManager 多上下文缓存键

**Verification:** 命中/未命中/失效全路径；上下文变化正确失效；不含 Key。

**Commit:** `feat: add multi-context content hash cache`

---

## Task 19: M3 Integrated Provider Contract & Security Gate

**Purpose:** M3 全部 Provider 能力的集成验证和安全栅栏。

**Files:**
- Test: `tests/providers/contracts/` — 全部合约测试
- Test: `tests/unit/test_provider_verification.py`
- Test: `tests/unit/test_provider_protocol.py`
- Test: `tests/unit/services/test_retry_policy.py`
- Test: `tests/unit/test_watch_resource_guard.py`
- Test: `tests/unit/test_usage.py`
- Test: `tests/unit/test_cache_manager.py`

**Steps:**
- [ ] 验证五 Provider 预设都有 adapter path
- [ ] 五份合约测试 + Custom 合约测试全部通过
- [ ] Task 1 核验报告覆盖五家
- [ ] ProviderRequest 不能接收原始文件/路径/file handle/完整视频
- [ ] 单一当前 Provider，不跨供应商
- [ ] RetryExecutor 在 adapter 中生效；401/403 不重试；429/timeout/5xx 有界重试
- [ ] Provider 无视觉能力明确降级
- [ ] 图片缩放、PDF PyMuPDF 渲染、视频 4–8 帧、不上传完整视频
- [x] ResourceGuard 达到安全上限时 fail-closed；UsageRecorder 仅记录非货币统计
- [ ] 缓存上下文完整
- [ ] API Key 不进入 JSON/日志/诊断
- [ ] legacy baseline 214 + M3 全部新增测试通过

**Verification:** 全 Provider 合约 + 安全栅栏通过。

**Commit:** `test: add M3 integrated provider contract and security gate`

## M3 Gate Report Checklist

- [ ] 5 个首期预设 + Custom Provider 可用
- [ ] 单一当前 Provider 路由正确
- [ ] 旧 OpenAI/Claude 已隔离不出现在预设
- [ ] 图片/扫描件/视频预处理功能正常
- [ ] 经济/均衡/高质量模式在当前 Provider 内工作
- [x] ResourceGuard 达到安全上限时 fail-closed；UsageRecorder 仅记录非货币统计（超标阻止 + 不静默降级）
- [ ] 缓存命中/未命中/失效全路径
- [ ] 用量记录区分缓存与 API 调用
- [ ] Key 仅存 Credential Manager
- [ ] legacy baseline 214 + 本阶段全部新增测试通过

**自动化测试命令:**
```bash
pytest tests/unit/test_provider_*.py tests/unit/test_quality_*.py tests/unit/test_confidence_*.py tests/unit/test_image_*.py tests/unit/test_keyframe_*.py tests/unit/test_page_*.py tests/unit/test_degradation.py tests/unit/test_budget.py tests/unit/test_usage.py tests/unit/test_cost_*.py tests/unit/test_cache_*.py tests/unit/test_model_*.py -v
pytest tests/integration/test_deepseek_adapter.py tests/integration/test_qwen_adapter.py -v
pytest tests/
python acceptance_test.py
```

**Product Owner 批准栏:**
- [ ] M3 审查通过
- [ ] 批准进入后续依赖 M3 的阶段

> **未批准不得进入依赖 M3 的后续阶段。**
