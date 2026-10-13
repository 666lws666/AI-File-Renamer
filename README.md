# 序匣（Xuxia）

序匣是一款 Windows 桌面文件命名与归档工具。你可以独立选择「AI 智能命名 / 按模板命名」和「云端 AI / 本地隐私」。程序提取有上限的文本、图片、扫描页或视频关键帧，生成建议；只有你应用后才修改文件，并支持撤销。

## 直接使用

正式 Windows 版本位于：

```text
dist\Xuxia\Xuxia.exe
```

完整离线说明书：

```text
序匣用户手册.html
```

双击说明书即可在浏览器中离线阅读，其中可以切换简体中文、繁体中文（香港）和英文。请保留完整的 `dist\Xuxia\` 文件夹，不能只复制 EXE。同目录已有「序匣」快捷方式时也可以点击它启动。

第一次使用：

1. 先用文件的副本试用，选择文件名输出语言；它与界面语言是两个独立选择。
2. 不想先挑模板时选「AI 智能命名」；需要固定字段时选「按模板命名」。
3. **云端 AI**：在设置中配置并测试一个 Provider。处理时必要的提取内容会发送给它。
4. **本地隐私**：明确选择本地模式，下载或导入固定 Qwen3.5-4B 资源，等待校验和真实模型自检成功。不需要安装 Python 或自己启动模型服务。
5. 添加文件，核对建议并按需编辑，再应用；需要恢复时撤销。监控文件夹建议先用「先审核」。

本地不可用时不会自动切回云端；开始切换本地后阻止后续云端命名提交，但已经发送的请求不能撤回。隐私边界是「序匣不会上传文件内容或命名请求」，不涵盖其他软件或系统云同步。

本机交付另外提供 `dist\本地模型离线资源\资源\`，可从设置中的离线导入入口选择这个文件夹。资源大小、来源、哈希和操作说明见该包的「先读我.txt」。它不是已启用的模型，也不应手工运行或解压其中的引擎 ZIP。

## 当前产品能力

- **批量重命名**：导入文件或文件夹，以全宽任务卡片审阅建议名，支持内联修改、筛选、单项或批量应用、失败重试和撤销。
- **AI 智能命名**：根据内容概括具体主题，在一个批次内保持语言和表达格式大致一致；不存在的日期、机构或版本不应凭空补齐，依据不足时明确拒绝或要求审核。
- **受管理本地隐私模式**：首期固定 Qwen3.5-4B 指令模型、Q4_K_M 与 F16 视觉资源、Windows CPU 引擎；模型首次按用户同意下载或离线导入，不把 GGUF 权重直接塞进 EXE。
- **监控文件夹**：支持 Review First 和 Auto Apply 两种流程，具有稳定等待、回流防护、资源暂停和重启恢复。
- **模板与受控词表**：组合日期、标题、主题、类型、项目等字段；预设词条可由用户编辑，也可审核 AI 建议的新词条。
- **单一当前 Provider**：内置 DeepSeek、Qwen、MiMo、智谱、Kimi 预设，并支持自定义 OpenAI-compatible Provider。产品不会同时强迫用户配置两家服务。
- **能力边界可见**：云端 Provider 会标明文本、视觉和结构化输出能力，云端视觉分析以其能力及用户同意为前提；本地模式使用自己的受管理模型，不依赖云端 Provider 的视觉能力。
- **本地多模态预处理**：图片会按上限缩放；扫描 PDF 仅渲染受限页数；视频只在本地提取 4/6/8 张关键帧并按图片分析，绝不上传完整视频。
- **安全凭据与文件操作**：云端 API Key 保存在 Windows Credential Manager，本地模式不需要 Key；应用前执行路径、扩展名、内容及文件身份检查，每个文件独立记录 Apply/Undo 结果。当前跨盘自动移动禁用，目录链接拒绝，歧义恢复证据不自动清空。
- **非货币资源护栏**：限制并发、重试、文件大小、PDF 页数、视频帧数，并提供非货币用量记录。当前受管生产命名路径不读写建议缓存，不以新增私密内容磁盘缓存充当完成。

序匣不显示 API 价格、费用估算、币种或金额预算。云端服务的实际计费由对应 Provider 负责。

## 开发与验证

### 环境

- Windows 10/11
- Python 3.14（当前发布候选验证环境）
- PySide6 / Qt Quick

### 安装依赖并启动

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.\run.bat
```

`run.bat` 和 `python -m src.main` 均进入正式 QML 运行时；仓库不再保留旧 Qt Widgets 产品入口。

### 测试

```powershell
python -m pytest tests --ignore=tests/screenshots -q -rs
python -m pytest tests/screenshots/test_m1_visuals.py tests/screenshots/test_screenshot_infra.py -q -rs
python acceptance_test.py
```

先构建当前 Windows 产物，再执行包含打包检查的完整测试。原生跨卷负测需要独立卷的临时夹具；部分固定运行引擎诊断需要相应公共资源。测试未运行或资源缺失不能视为通过。

截图测试默认只比较已提交 Golden，不会自动更新。上述命令运行全部正式截图测试，不递归执行忽略目录中的历史 QA 脚本。除非获得受控视觉验收授权，不要设置 `UPDATE_GOLDENS` 或 `UPDATE_SCREENSHOT_GOLDEN`。模拟 API、逻辑测试和像素比较不替代真实模型的内容质量核对。

### Windows 打包

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -PythonPath .venv\Scripts\python.exe
```

产物输出到 `dist\Xuxia\`。打包后的正式入口仍为 `Xuxia.exe`。

## 目录概览

- `src/ui_qml/`：正式 Qt Quick 界面
- `src/controllers/`：Batch、Watch、Templates、Preferences 控制器
- `src/core/`：文件任务、Apply/Undo、模板、词表、缓存与安全边界
- `src/providers/`：Provider 协议、预设、连接测试和适配器
- `src/services/media/`：图片、扫描 PDF 和视频关键帧本地预处理
- `src/services/local_ai/`：固定资源管理、受限运行链路与本地推理
- `tests/`：单元、集成、QML、截图及打包测试
- `docs/`：产品规格、设计、实施和验收记录

产品规格与详细设计分别见 `docs/PRODUCT_SPEC.md` 和 `docs/XUXIA_DETAILED_DESIGN.md`。

当前本地合并、真实 EXE 验收及已知限制见 [本地隐私交付收口报告](docs/reports/2026-10-13-frozen-local-handoff.md)。AI 名称仍须审核；当前机器的合成样本通过不保证任意文件、其他硬件或真实云端服务全部通过。
