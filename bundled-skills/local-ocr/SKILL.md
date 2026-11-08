<!-- 配套技能卡 · 已脱敏副本 · 版权归各自作者 -->

---
name: local-ocr
display_name: 本地离线OCR识别
display_name_en: "Local Offline OCR"
description: "本地离线 OCR 识别（RapidOCR，中英文）。当用户要求「识别图片/PDF/扫描件里的文字」「提取合同/发票/证件/截图文字」「批量 OCR 一个文件夹」「把扫描 PDF 转成可复制文本」时使用。完全本地运行、不联网、不上传、无次数限制。首次使用需一键部署环境（约 3-5 分钟，之后永久离线可用）。Use when the user needs to extract text from images, scanned PDFs or screenshots without uploading data to any cloud service."
description_zh: "基于 RapidOCR 的本地离线文字识别技能，支持 PNG/JPG/BMP/TIF/WEBP/PDF，中英文与数字，全部在本机完成、不联网、不上传任何文件。PDF 自动分流：有文字层直接提取（快且准），扫描件按指定 DPI 渲染后OCR。支持单文件与整目录批量，输出带坐标与置信度的文本。首次使用需运行setup.py 一键部署独立虚拟环境（自动探测 WorkBuddy 自带 Python 或系统 Python，走清华源安装，约 320MB），部署完成后永久离线可用。"
description_en: "Offline text recognition based on RapidOCR, supporting PNG/JPG/BMP/TIF/WEBP/PDF with Simplified Chinese, English and digits, all processed locally with no network access and no file uploads. PDFs are handled on two paths: pages with a text layer are extracted directly for speed and accuracy, while scanned pages are rendered at the given DPI before OCR. Works on single files or whole directories, emitting text with bounding boxes and confidence scores. First use requires running setup.py to provision an isolated virtual environment (auto-detects WorkBuddy bundled or system Python, installs from the Tsinghua mirror, about 320MB); after that it works permanently offline."
category: 文档处理
version: 1.0.0
author: 河南数智教育
agent_created: true
---

# local-ocr — 本地离线文字识别

用 RapidOCR 在本地把图片 / 扫描 PDF 转成文本。适合合同、发票、证件、截图、扫描件。

## 硬性前置规则

1. **先读 `venv_path.txt`**（skill 目录下，由 `scripts/setup.py` 在部署成功时自动生成）。
   它记录了可用解释器的绝对路径。
   - 文件存在且路径有效 → 直接用里面的路径调用脚本。
   - 文件不存在或路径已失效 → 先执行下方「首次部署」，再继续。
2. 不要向系统 Python 或 WorkBuddy 托管 Python 直接 `pip install`，必须用 skill 自带的 venv。

## 首次部署（只需一次）

```bash
# 用任意可用 Python 跑 setup，它会自动找 WorkBuddy 自带 Python（优先）或系统 Python
python <skill_dir>/scripts/setup.py

# C 盘紧张时可把环境放到别的盘（约 320MB）
python <skill_dir>/scripts/setup.py --venv-dir "E:\ai\ocr_venv"
```

脚本自动完成：建 `.venv` → 清华源装依赖（失败回退官方源）→ 写 `venv_path.txt` → 跑自检。
看到 `SETUP DONE` 即可。体积约 320 MB，需联网一次。

## 使用（部署后）

```bash
<venv_path.txt 里的 python> <skill_dir>/scripts/ocr.py "<文件或文件夹路径>"
```

常用参数：

| 参数 | 作用 |
|---|---|
| `--out 文件.txt` | 合并输出到指定文件（默认：源文件旁生成同名 `.ocr.txt`） |
| `--box` | 额外输出置信度和坐标 |
| `--dpi 400` | 扫描 PDF 渲染精度，默认 300（模糊件可调高） |

示例：

```bash
python scripts/ocr.py "D:\scan\合同.pdf"
python scripts/ocr.py "D:\scan" --out "D:\all.txt"
python scripts/ocr.py "D:\a.png" --box
```

## 输出与交付

- 结果默认写到源文件同目录的 `.ocr.txt`，同时在终端打印行数。
- 识别完成后，**直接把文本内容整理进回复**给用户，不要只说"已保存到文件"。
- PDF 会自动分两条路：有文字层直接提取（快且准）；无文字层（扫描件）按 dpi 渲染后 OCR。

## 能力边界（必须如实告知用户）

- 支持 PNG/JPG/BMP/TIF/WEBP/PDF，中文简体 + 英文 + 数字，模型随包自带。
- **手写体识别率差**，工整手写勉强可用。
- **不还原表格结构**，只能拿到文字；需要表格结构请换 PaddleOCR PP-Structure。
- **金额、日期、证件号等关键数字必须人工复核**——形近字有误识风险（如 `28日`→`218日`）。
- 单页 CPU 约 1-3 秒，无需显卡。

## 排错

| 现象 | 处理 |
|---|---|
| 报没找到 Python | 装 Python 3.9-3.13（不要用 3.14），或确保已装 WorkBuddy |
| 装包网络失败 | 重跑 `setup.py`，已下载的包会缓存；公司网络需先设 `HTTPS_PROXY` |
| 识别结果为空 | 提高 `--dpi`；确认图片不是纯空白页 |
| 报 `no file found` | 路径要用 Windows 风格（`E:\a.png`），Git Bash 的 `/e/a.png` Python 不认 |
