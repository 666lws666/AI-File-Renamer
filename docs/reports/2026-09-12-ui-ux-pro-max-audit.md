# UI/UX Pro Max 安装与序匣首轮审查

日期：2026-09-12。
项目基线：feature/xuxia-m0-foundation，HEAD 5af6cc4。
状态：技能已安装、现状审查完成；以下界面修改方案待 Product Owner 确认，尚未改产品代码。

## 技能安装验证

- 来源：nextlevelbuilder/ui-ux-pro-max-skill，路径 .claude/skills/ui-ux-pro-max。
- 使用 Codex skill-installer 官方辅助脚本安装完整目录，包含 SKILL.md、scripts、data、references。
- 安装目录为 Codex 用户技能目录下 ui-ux-pro-max；下一轮对话可自动发现。
- 安装时 SKILL.md SHA-256：EA087C341BFB5B23195C7302027268EDE86DA802554C18A5C4896A6017B439F9。
- 主代理完整阅读 SKILL.md、quick-reference.md、pro-rules.md。
- 三次本地搜索均成功，每次返回 3 条：desktop tool empty state onboarding；visible labels helper text；focus not obscured（均使用显式 ux domain）。
- 采用相关语义原则，不照搬 Web ARIA/CSS、手机触控尺寸或手机导航；技能没有 Qt Quick/QML 专用技术栈。
- 没有运行 design-system --persist/--force，没有用自动生成设计覆盖现有规格。

## 原生证据

运行既有 scripts/capture_beginner_ui_polish_native.py，分别使用 zh-CN 和 en-US。
每个语言捕获 20 张，共 40 张，Windows QPA，两个运行结果均为 captures=20、warnings=0。

脚本使用临时 AppConfig/config_file、FakeCredentialStore、无网络 connection_test_service、usage_recorder=None。
未访问真实 API/Key/Credential Manager；未写真实用户配置。

逻辑窗口尺寸为 1000×700 和 900×640。当前 Windows 125% 缩放下，PNG 实际像素分别为 1250×875、1125×800，不能将逻辑尺寸当作 PNG 分辨率。

截图和哈希清单位于被忽略的 tests/screenshots/qa-current/beginner-ui-polish/。
实看代表证据：batch-900.png、batch-900-en.png、settings-900.png。
这不是完整键盘无障碍或香港繁体复验，不声称所有页面通过全部 UX 规则。

## 已存在的优点：保留，不重做

- Batch 空态已有“添加文件 → 查看建议 → 应用更改”三步说明。
- 已说明添加和分析不改变原文件；按钮有完整“添加文件／添加文件夹”文本。
- CJK 字体可读，窗口外轮廓可辨认。
- 模板、文件名语言、AI 能力和文件安全流程已有可运行基础。

## 有证据的改进点

| ID | 现状与证据 | 对用户的影响 | 处理建议 |
| --- | --- | --- | --- |
| UX-01 | NavBar.qml 五入口仅 Image + ToolTip；实际截图没有可见导航文字 | 新用户必须试点或悬停辨认入口 | 图标配常驻短标签，保留原五入口 |
| UX-02 | BatchToolbar.qml compactActions 在窄窗口或英文启用；应用、停止、清空显示 IconOnly | 关键操作再次依赖悬停解释 | 两尺寸和三语言均显示动作文字 |
| UX-03 | 工具栏控件大量使用 10–11px 文本、28px 高度；英文搜索框实际只显示 Search f... | 为单行排布牺牲阅读和输入提示 | 配置与任务操作拆成两行，优先保留标签和可点击空间 |
| UX-04 | 模板选择只有当前名称；数量显示 0/0；目标目录按钮只表示设置入口 | 用户不易判断这是模板、选择数量还是处理进度，以及文件最终位置 | 明确模板标签；数量给出语义；目标位置有常驻说明 |
| UX-05 | settings-900.png 的数字步进器仍为 Basic 灰色方块，与 AppButton 风格不同 | 同类控件视觉语言不统一 | 下一轮统一设置控件，不混入本轮 Batch 改动 |

技能搜索最直接支持 UX-01/02 的可发现性、UX-03/04 的标签与信息层级。
焦点遮挡规则用于后续验收；本轮未用静态源码推断“键盘测试已通过”。

## 三种方向

A. 保持 48px 纯图标导航和单行工具栏，只改字号/间距。
改动小，但有限宽度仍迫使关键动作变为图标，难彻底解决 UX-01/02/03。

B. 首页易用性升级（推荐）。
保留浅色、深色主按钮、全宽任务卡片及五个入口；导航改为图标+短标签；工具栏拆分两行。
代价是比现有导航多占约 32 个逻辑像素宽、工具栏多占约一行高度，换来清晰操作和稳定文字。
这是对原先“48px 图标侧栏、严格单行工具栏”设计约束的明确变更，需确认后实施。

C. 全应用重新设计。
覆盖设置、监控、模板、配色和组件，范围大、回归广；本轮不推荐。

## 推荐 B 的实现边界（待批准）

1. 导航宽度拟为 80 逻辑像素。五入口不增不减，显示图标和短标签；英文使用简短导航名称，中文与香港繁体对应翻译。保留选中状态、状态徽标，补键盘焦点和激活验证。
2. Batch 上行放命名模板、添加文件、添加文件夹和目标目录；下行放选择/计数、搜索、状态筛选及应用/停止/清空。保留控件 objectName、controller 方法和业务状态来源。
3. 关键动作常驻文字，不通过窄窗口转为图标来节约宽度。目标目录明确区分原目录重命名与移动到已选目录；长路径可以截断，但必须有查看全文的方式。
4. 保留现有空态三步说明，避免另加强制教程。文件名语言仍沿已验收导入确认流程，不新增自动改名路径。
5. 只改相关 QML、必要的显示文案/设计 token 和测试，不改变 Provider、凭据、Watch、RenamePlan/Apply/Undo、持久化或 AI 请求。
6. 本轮不重绘设置页；UX-05 保留为下一轮明确项目。

## 验收边界

- 中文、香港繁体、英文；1000×700、900×640 逻辑尺寸；记录 Windows 实际缩放与 PNG 像素。
- 覆盖空态/混合任务、搜索与筛选、选中批次、应用进度、导航真实点击、Tab/Enter/Space 焦点行为。
- 无文字裁切、关键动作隐藏、操作覆盖；QML warning=0；不只验证 objectName 存在。
- 正式 Golden 不自动更新。如设计使基准发生预期变化，列出精确变化清单并另取更新授权，不伪称全绿。
- 原生截图只写 qa-current；使用隔离配置和假服务，不调用真实 API，不访问真实凭据。
- 通过定向、完整非截图、截图回归及打包 smoke 后再交付新版；不 push、不公开发布。
- 本次仅新增这份审查文件；现有用户快捷方式保持原状。产品代码尚未修改。
