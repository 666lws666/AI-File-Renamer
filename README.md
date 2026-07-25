# AI File Renamer — 文件智能重命名工具

基于云端 AI（DeepSeek / OpenAI / Claude）的 Windows 桌面应用，自动分析文件内容并生成清晰、可搜索、规范化的文件名。

## 功能

- **AI 智能重命名**：读取文件实际内容（PDF、Word、Excel、PPT、TXT、图片等），调用 AI API 生成描述性文件名
- **批量处理**：一次扫描整个文件夹，预览 AI 建议后批量应用
- **一键撤销**：所有重命名操作记录到日志，支持撤销
- **命名模板**：自定义文件名格式（日期、标题、标签、类型等变量）
- **文件夹监控**：监控指定文件夹，新文件自动 AI 处理
- **自动归类**：重命名后按日期/类型/项目自动归入子文件夹

## 支持的格式

| 类型 | 格式 |
|------|------|
| 文档 | PDF, DOCX, PPTX, XLSX, TXT, MD, CSV, HTML |
| 图片 | JPG, PNG, GIF, BMP, WebP, TIFF, AVIF |
| 视频 | MP4, MOV, MKV, AVI, WebM, WMV |

## 快速开始

### 环境要求
- Windows 10/11
- Python 3.11+

### 安装

```powershell
# 克隆项目
git clone https://github.com/666lws666/AI-File-Renamer.git
cd AI-File-Renamer

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 配置 AI API Key

1. 获取 API Key（任选一个）：
   - [DeepSeek](https://platform.deepseek.com)（推荐，便宜）
   - [OpenAI](https://platform.openai.com)
   - [Anthropic Claude](https://console.anthropic.com)
2. 启动应用：`python -m src.main`
3. 在设置中填入 API Key

### 使用

1. 点击「添加文件夹」选择要处理的文件夹
2. 点击「扫描并AI分析」
3. 预览 AI 建议的文件名，可双击编辑
4. 点击「应用重命名」
5. 如需恢复，点击「撤销上次」

## 技术栈

- **GUI**: PySide6 (Qt)
- **AI**: DeepSeek / OpenAI / Claude API
- **文件处理**: PyPDF2, python-docx, openpyxl, python-pptx, Pillow
- **监控**: watchdog

## 许可

MIT License
