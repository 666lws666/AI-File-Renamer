# 精简版主目录整合与重新打包验证

日期：2026-10-13。按用户明确授权，将已审查的精简候选合并回 `feature/xuxia-m0-foundation`，主目录重新构建并验证。本文记录本地部署结果；GitHub 同步必须另以实际 push 及远端查询确认，不能用本地通过代替远端完成。

## 合并与回滚

- 主分支从 `1155cbaa6656dadd9aac2a6e358ee3d8c4d175cf` 快进到 `14bd523db5cb3ae3e548be7cafc3d0c6fd17d3d0`，无合并冲突、无额外合并提交。
- 原安装目录完整保存在 `tests/screenshots/qa-current/local-privacy/simplification-install-20261013/previous-Xuxia/`，3323 文件 / 672,529,128 字节。旧 EXE SHA-256 为 `6b5c64f7984bf91fc10a81fc96c2cc94293321edc6b43b4ff0a8914d5b044331`，备份核对一致。
- 用户配置、本地模型资源、其他历史工作区及现有 `序匣.lnk` 均未修改。
- 本报告及候选历史页提示在验证之后单独提交，不改变经过验证的应用源码。

## 主目录新产物

通过既有 `scripts/build_windows.ps1` 在主目录做干净 Windows 构建，不复制候选 EXE 来代替重新构建。

- 路径：`dist/Xuxia/Xuxia.exe`。
- SHA-256：`ebd824de415e1f7fc5b5fa1838e11072cb60b5231cb43a1db26f980ac8e599fb`。
- EXE 大小：11,558,522 字节。
- 安装目录：3323 文件 / 672,525,473 字节，含原有三语言手册及资源。
- 实际构建源码 tree：`b831bd8cae97ba85b4f2681949f6c3a883d492da`。
- 新包哈希由本次构建后重新计算，不使用旧包或独立候选包哈希作为预期值。

## 合并后完整 Gate

运行环境：Windows、Python 3.14.5、PySide6/Qt 6.12.0。测试配置及用户数据隔离，真实网络与凭据访问阻断。原始日志保存于 `tests/screenshots/qa-current/local-privacy/simplification-install-20261013/`。

| 门禁 | 真实摘要 | 日志 |
| --- | --- | --- |
| 主目录干净构建 | exit 0，两个既有可选依赖警告 | build.log |
| 完整非截图 pytest | 6306 passed, 3 skipped, 4 warnings；return 0 | full.log |
| 完整正式截图（两个 Git 登记文件） | 54 passed, 1 skipped, 86 warnings；return 0 | screenshots.log |
| 专项 packaging | 33 passed, 3 warnings；return 0 | packaging.log |
| acceptance | 176/176 passed，0 failed；return 0 | acceptance.log |
| 快捷方式目标 EXE 隔离启动 | 实际进程 exit 0，QML warning 0 | shortcut-target-smoke/report.json |

所有 pytest/acceptance 的 forbidden access attempts 为 0，退出线程证据仅有 MainThread。专项 packaging 已包含于非截图套件，不重复累计。

三个非截图 skip 为已有文件符号链接权限不可用；截图唯一 skip 是关闭更新模式时按设计跳过的更新模式测试。没有新增 skip/xfail、排除失败用例或更新 Golden。既有 Pydantic、PyPDF2、Pillow 弃用警告，以及 Qt 可选 DLL/tzdata 构建警告如实保留，不宣称零警告。

## 现有快捷方式

从原 `序匣.lnk` 只读取得目标 `D:\文件AI-AGENT\dist\Xuxia\Xuxia.exe`、工作目录 `D:\文件AI-AGENT\dist\Xuxia` 及空参数，均与更新前相同。重建后的新 EXE 已位于这个目标位置，无需重建快捷方式。

用该目标与工作目录加隔离 smoke 参数启动，并显式等待真实进程退出。报告为 status ok、QML warnings 0、ephemeral 凭据后端；图片预处理、PDF 渲染、视频关键帧和诊断导出均 ok。Windows 凭据后端仅检查 import，不读取真实凭据。stderr 为空，进程已退出。

此证据是快捷方式解析后的目标 EXE 启动验证，不声称在用户真实配置中做过鼠标双击或云端调用，也未修改快捷方式的实际参数。

## GitHub 同步边界

公开仓库沿用已有源码快照历史：以经核验的远端 master 为父提交，生成与本次已验证主分支完全相同的源码树，非强制快进更新 master。内部完整开发历史保留在本地，不整条推送到公开仓库。

推送前重新检查参考品牌、疑似密钥及私有证据/工作区/安装包路径；只上传跟踪源码，不上传未跟踪快捷方式、QA/备份、模型缓存、build/dist 或用户设置。不创建 GitHub Release。本地构建验证不冒充真实云端 API 或模型语义质量重新验收。
