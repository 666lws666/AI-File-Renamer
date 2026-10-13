# DeepSeek V4.1 Flash 更新验证记录

日期：2026-09-10。Windows 11 原生环境，项目 Python 3.14.5、PyInstaller 6.21.0。

## 范围与结论

本次适配及本地发布产物验证通过。功能提交为 `31810cd`，基线为 `a255d4eb6f76c9aef8eb3d4a66ffd833c7ee0810`；`bc959bf` 记录已批准规格和实施计划。未调用真实 API，因此不声称已验证用户账户权限或真实服务端推理质量。

- 新建 DeepSeek 配置推荐 `deepseek-flash`，显示“Flash V4.1：文本和图片（推荐）”。
- 两个旧名称 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 保留为官方兼容别名。
- V4 Pro 在本次日期快照仍为文本型号；未知名称不继承 Flash 能力。
- 简体中文、英文、香港繁体文案及离线用户手册已同步。
- 旧设置、型号、Key 不自动重写。用户需编辑模型、测试连接、保存后启用新能力；已有 Key 无需在表单重复输入。

## 官方依据

核验日期均为 2026-09-10：

- [DeepSeek 更新日志](https://api-docs.deepseek.com/updates/)：V4.1 Flash 发布、canonical 模型名及兼容名称；V4 Pro 公告切换时间为 2026-09-14 北京时间 12:00，不能提前视为已发生。
- [图像理解 API](https://api-docs.deepseek.com/guides/vision/)：用户消息使用 text 与 image_url 内容块。应用继续使用本地预处理后的内联图像。
- [模型能力表](https://api-docs.deepseek.com/quick_start/pricing/)：本次仅据此核实图像与 JSON 输出能力；不引入费用功能，不保留旧型号价格为当前已核验价格。

## 安全与兼容

预设、请求图像校验及连接结果能力检测共同使用精确型号解析器。自定义网关不因同名获得官方能力；官方端点约束保留。连接成功不等于自动探测出视觉能力。

现有边界未放宽：最多 8 张预处理图像、单张 10 MiB、合计 32 MiB、1600 万像素及 DeepSeek 8192 边长限制。图片重新编码后作为 user 消息 data URL 发送；扫描件发送本地渲染页，视频只发送约 4–8 个本地关键帧。没有新增完整 PDF、完整视频、源路径或外部图像 URL 上传路径。

## 测试驱动与问题处置

1. 新型号与旧别名测试先出现预期 RED（15 failed / 17 passed），实施后相关初始集合为 32 passed；扩展 Provider、QML、i18n 集合为 190 passed。
2. 完整回归暴露连接检测仍按品牌继承能力。补充 Pro/未知型号负测得到 3 failed / 9 passed，再改用精确型号解析器；相关连接、设置、用量与手册回归为 206 passed。
3. 手册新增外链不符合既有完全离线约定，已移除，官方来源集中在本记录；未放松离线测试。
4. 旧默认型号断言调整到 canonical 名称。两项 working-tree 与 HEAD 一致性检查保持原样，形成实现 checkpoint 后为 19 passed，未跳过它们。
5. 独立只读审查及补充复审未发现确定 P0/P1。审查不代替下列实际运行结果。

## 最终原始结果

全部命令由项目 .venv 在 Windows 下执行，所有最终进程退出码为 0：

| 命令 | 原始摘要 |
| --- | --- |
| `.venv\Scripts\python.exe -m pytest tests --ignore=tests/screenshots -q` | 1738 passed, 1 skipped, 3 warnings in 98.61s |
| `.venv\Scripts\python.exe -m pytest tests/screenshots -q` | 54 passed, 1 skipped, 86 warnings in 93.18s |
| `.venv\Scripts\python.exe acceptance_test.py` | Passed: 186/186; Failed: 0/186; Rate: 100.0% |
| `.venv\Scripts\python.exe -m pytest tests/packaging -q` | 23 passed, 3 warnings in 10.42s |
| `powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -SkipClean -PythonPath .venv/Scripts/python.exe` | Build complete; exit 0 |
| `git diff --check` | exit 0 |
| `git diff a255d4e --name-only -- tests/screenshots/golden` | 无输出 |

截图更新模式关闭。跳过项为既有 Windows symlink 平台条件及截图更新模式测试；没有新增 skip 或排除失败测试。3 项 warnings 为已有 Pydantic 类 Config 弃用警告；截图 86 项为已有 Pillow getdata 弃用警告。构建另有未使用 Qt labs assetdownloader 插件和 tzdata hidden-import 提示，真实打包 smoke 与产品资源检查均通过。

打包测试包含隔离 EXE 启动、临时用户目录、临时凭据后端、零 QML warning、图片/PDF/视频处理与诊断资源、三语言支持、手册资产逐字节一致及产物开发机路径/用户状态扫描。23 项属于完整非截图集合，不重复累加为独立总数。

## 原生界面证据

脚本：`scripts/capture_deepseek_vision_native.py`。

使用 Windows QPA、临时配置、假凭据和假连接服务；真实鼠标/键盘切换模型，未保存用户设置。三语言 × 两尺寸 × 五捕获状态，共 30 PNG；manifest 记录 SHA、尺寸，QML warnings=[]。

证据位于被忽略的 `tests/screenshots/qa-current/deepseek-v41/`，未提交图片、未更新正式 Golden。已实际检查最小窗口中文、香港繁体和英文截图，以及模型下拉与 Pro 降级显示：CJK 可读、四选项可区分、说明换行未横向裁切。

## 当前 Windows 产物

- 路径：`dist/Xuxia/Xuxia.exe`
- EXE 字节数：10,951,018
- SHA-256：`7DA0B77DDA842F956D0FF7868EE5B6D4D43244838A8D01DBF3330C5B10726016`
- onedir 完整目录：3,081 个文件，567,784,014 bytes。
- 运行时依赖位于同目录，不能只复制 EXE。
- 离线手册：项目根及发布目录中的 `序匣用户手册.html`。

## 非阻断 backlog

- P2：旧已保存 text-only Flash 的列表能力展示来自最新 catalog，但实际请求按保存能力保守执行；未重测保存时可能“显示支持图片但请求仍拒绝”。手册和本次提示已说明重测保存路径；后续可增加专门的“需要重新验证”展示，不能自动扩权。
- P3：进一步补充完整旧 profile 从加载到候选重测保存的升级用例，以及未知型号全部能力位断言。
- 既有 Pydantic/Pillow 弃用警告与未使用打包 hook 提示留待依赖维护。

未 push、未创建 release、未访问真实 Credential Manager。保留原有未跟踪 `序匣.lnk`，不删除、不改写、不提交。
