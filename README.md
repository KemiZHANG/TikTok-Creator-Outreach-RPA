# TikTok Creator Outreach RPA

<p align="center">
  <a href="#中文">中文</a>
  ·
  <a href="#english">English</a>
</p>

---

## 中文

一个基于 Python 的 Windows 桌面流程自动化项目，用于演示跨境电商达人运营场景中的 RPA 工作流设计。项目通过屏幕图像识别、OCR、SQLite 去重、Excel 导出、日志与异常恢复等机制，把重复性的达人触达流程封装成可配置、可观测、可恢复的本地自动化工具。

> 说明：本仓库是作品集展示版，不包含真实达人数据、运行日志、失败截图、联系方式表格或本机私有配置。使用者需要遵守目标平台规则，并仅在获得授权的业务场景中使用自动化能力。

### 项目亮点

- 使用 `pyautogui` 实现 Windows 桌面级 RPA 操作，包括点击、滚动、文件选择和文本粘贴。
- 使用 OpenCV 模板匹配识别关键 UI 状态，并在模板识别失败时退回配置化坐标。
- 使用 Tesseract OCR 读取达人名称、简介联系方式和浏览器异常页面文本。
- 使用 SQLite 记录已处理达人，避免重复触达。
- 使用正则规则从 OCR 文本中提取邮箱和商务电话，并导出到 Excel。
- 提供重试、超时、日志、失败截图、ESC 中断和浏览器崩溃恢复机制。
- 通过 `config.json` 管理坐标、模板、超时、重试和 OCR 参数，便于在不同机器上校准。

### 技术栈

- Python
- PyAutoGUI
- OpenCV
- Tesseract OCR / pytesseract
- SQLite
- openpyxl
- pyperclip

### 项目结构

```text
.
├── main.py                 # 基础自动化流程
├── main2.py                # 增强版：去重、联系方式采集、崩溃恢复
├── utils.py                # 通用点击、识别、日志、截图、恢复工具
├── ocr_utils.py            # OCR 截图、预处理和文本读取
├── creator_db.py           # 达人去重数据库
├── contact_export.py       # 联系方式提取、去重和 Excel 导出
├── capture_points.py       # 坐标采集辅助脚本
├── scroll_test.py          # 滚动参数测试脚本
├── config.example.json     # 可公开的示例配置
├── requirements.txt
├── images/                 # 本地模板图目录，公开版不包含实际截图
└── logs/                   # 运行日志和调试截图目录，公开版仅保留占位文件
```

### 工作流概览

1. 从达人列表页进入当前达人详情页。
2. OCR 读取达人名称，并查询 SQLite 去重库。
3. 按需 OCR 读取简介区域，提取邮箱和商务电话。
4. 打开聊天窗口，完成图片和文本发送流程。
5. 成功后写入达人去重库和联系方式文件。
6. 关闭详情页，回到列表页并滚动到下一位达人。
7. 如果遇到页面异常或浏览器崩溃，保存截图并尝试刷新恢复。

### 稳定性设计

- 关键动作均带有等待、重试和状态确认。
- UI 模板识别失败时会使用后备坐标继续执行。
- 文件选择窗口会检查是否真正打开和关闭。
- 图片发送确认弹窗会补点一次，避免弹窗残留影响后续流程。
- 崩溃恢复会结合模板识别和 OCR 关键词确认页面状态。
- 所有失败都会写入日志，并保存调试截图，方便复盘。

### 本地运行

安装依赖：

```powershell
pip install -r requirements.txt
```

准备配置：

```powershell
Copy-Item config.example.json config.json
```

然后根据自己的屏幕分辨率、浏览器缩放比例和页面布局，更新 `config.json` 中的坐标、OCR 区域和模板图名称。

运行基础版：

```powershell
python main.py
```

运行增强版：

```powershell
python main2.py
```

增强版启动时会询问：

- 是否清理达人去重数据库
- 是否抓取邮箱与商务电话
- 崩溃恢复后是否重建筛选条件
- 本次消息内容
- 滚动距离
- 本次运行人数

### 模板图与 OCR

项目依赖本地模板图进行 UI 匹配。请在 `images/` 下放入自己截图得到的模板图，例如：

- `private_chat_btn.png`
- `send_photo_btn.png`
- `send_message_marker.png`
- `ok_btn.png`
- `browser_crash_marker.png`
- `find_creators_marker.png`
- `reload_btn.png`

OCR 依赖 Tesseract 程序本体。Windows 用户可以将 `tesseract.exe` 加入 PATH，或在 `config.json` 的 `ocr.tesseract_cmd` 中填写完整路径。

### 数据与隐私

以下文件不会提交到公开仓库：

- `config.json`
- `*.db`
- `*.xlsx`
- `logs/` 下的运行日志和截图
- `images/*.png` 本地模板截图
- `__pycache__/`

这样可以避免泄露真实达人信息、联系方式、页面截图、本机路径和运行数据。

### 适合作品集展示的能力点

这个项目可以体现：

- 把真实运营流程抽象成自动化状态机的能力
- 使用 OCR 和图像识别解决非结构化 UI 自动化问题
- 为不稳定页面设计重试、恢复和观测机制
- 用 SQLite 和 Excel 管理轻量业务数据
- 在真实约束下迭代工具稳定性的工程意识

---

## English

A Python-based Windows desktop automation project that demonstrates RPA workflow design for creator outreach operations in a cross-border e-commerce context. The project combines screen image recognition, OCR, SQLite deduplication, Excel export, logging, and exception recovery to turn a repetitive outreach workflow into a configurable, observable, and recoverable local automation tool.

> Note: This repository is a portfolio-friendly version. It does not include real creator data, runtime logs, failure screenshots, contact spreadsheets, or private local configuration. Users should follow the target platform's rules and only use automation in authorized business scenarios.

### Highlights

- Uses `pyautogui` for Windows desktop-level RPA actions, including clicking, scrolling, file selection, and text pasting.
- Uses OpenCV template matching to identify key UI states, with configurable coordinate fallbacks when template recognition fails.
- Uses Tesseract OCR to read creator names, profile contact text, and browser error page text.
- Uses SQLite to track processed creators and avoid duplicate outreach.
- Extracts email addresses and business phone numbers from OCR text, then exports them to Excel.
- Provides retry control, timeouts, logging, failure screenshots, ESC interruption, and browser crash recovery.
- Uses `config.json` to manage coordinates, templates, timeouts, retries, and OCR parameters for machine-specific calibration.

### Tech Stack

- Python
- PyAutoGUI
- OpenCV
- Tesseract OCR / pytesseract
- SQLite
- openpyxl
- pyperclip

### Project Structure

```text
.
├── main.py                 # Base automation workflow
├── main2.py                # Enhanced version: deduplication, contact extraction, crash recovery
├── utils.py                # Shared clicking, recognition, logging, screenshot, and recovery utilities
├── ocr_utils.py            # OCR screenshots, preprocessing, and text reading
├── creator_db.py           # Creator deduplication database helpers
├── contact_export.py       # Contact extraction, deduplication, and Excel export
├── capture_points.py       # Coordinate capture helper
├── scroll_test.py          # Scroll parameter testing helper
├── config.example.json     # Public example configuration
├── requirements.txt
├── images/                 # Local template image folder; actual screenshots are not included
└── logs/                   # Runtime logs and debug screenshots; only a placeholder is included
```

### Workflow Overview

1. Open the current creator's detail page from the creator list.
2. Read the creator name through OCR and check it against the SQLite deduplication database.
3. Optionally read the profile area through OCR and extract emails or business phone numbers.
4. Open the chat window and complete the image and text sending workflow.
5. After success, write the creator name and extracted contact data to local storage.
6. Close the detail page, return to the list, and scroll to the next creator.
7. If a page exception or browser crash occurs, save a screenshot and attempt recovery.

### Reliability Design

- Critical actions include waiting, retrying, and state confirmation.
- UI template recognition can fall back to configured coordinates.
- The file picker flow checks whether the dialog actually opens and closes.
- The image confirmation popup is clicked again if it remains visible after the first click.
- Crash recovery combines template matching and OCR keyword detection.
- Failures are logged with screenshots for later debugging.

### Local Setup

Install dependencies:

```powershell
pip install -r requirements.txt
```

Prepare the local configuration:

```powershell
Copy-Item config.example.json config.json
```

Then update `config.json` based on your screen resolution, browser zoom level, page layout, OCR regions, and template image names.

Run the base version:

```powershell
python main.py
```

Run the enhanced version:

```powershell
python main2.py
```

The enhanced version asks for:

- Whether to clear the creator deduplication database
- Whether to collect emails and business phone numbers
- Whether to rebuild filters after crash recovery
- Message content for the current run
- Scroll distance
- Number of creators to process

### Template Images and OCR

This project depends on local template images for UI matching. Place your own screenshots in the `images/` folder, for example:

- `private_chat_btn.png`
- `send_photo_btn.png`
- `send_message_marker.png`
- `ok_btn.png`
- `browser_crash_marker.png`
- `find_creators_marker.png`
- `reload_btn.png`

OCR requires the Tesseract executable. On Windows, you can either add `tesseract.exe` to PATH or set the full path in `ocr.tesseract_cmd` inside `config.json`.

### Data and Privacy

The following files are intentionally excluded from the public repository:

- `config.json`
- `*.db`
- `*.xlsx`
- Runtime logs and screenshots under `logs/`
- Local template screenshots under `images/*.png`
- `__pycache__/`

This prevents leaking real creator data, contact details, page screenshots, local paths, and runtime artifacts.

### Portfolio Value

This project demonstrates:

- Modeling a real operations workflow as an automation state machine
- Using OCR and image recognition to handle non-structured UI automation
- Designing retries, recovery, and observability for unstable web interfaces
- Managing lightweight business data with SQLite and Excel
- Iterating a practical tool under real-world constraints
