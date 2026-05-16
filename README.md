# 软考学习资料库

这个仓库把下载到的软考 PDF 资料整理成一个静态 HTML 阅读库，入口是 `study-html/index.html`。

## 目录说明

- `01、官方教材+一本通（最新第三版）/`：教材、一本通、考点资料。
- `02、历年真题（2016-2024年）/`：历年选择题和案例分析真题。
- `03、机考讲解及模拟/`：机考说明和模拟资料。
- `04、 2025年软考实名认证操作流程及常见问题说明/`：报名、认证相关资料。
- `05、学前必看 - 软考基本介绍讲解及考试时间/`：入门说明。
- `study-html/`：生成后的 HTML 阅读库。
- `tools/build_pdf_library.py`：从 PDF 重建 HTML 阅读库的脚本。
- `tools/audit_study_html.py`：检查 HTML 输出完整性的脚本。

## 重建 HTML

```bash
python -m pip install -r requirements.txt
python tools/build_pdf_library.py
# 如本机已安装 Tesseract 和中文语言包，可对扫描页追加 OCR 文本：
python tools/build_pdf_library.py --ocr --ocr-lang chi_sim+eng
# 只处理前 N 个 PDF 做冒烟测试：
python tools/build_pdf_library.py --limit 3
```

生成逻辑：

1. 对有可用文字层的 PDF 页面，抽取文字并修复 PDF 常见的硬换行，让句子更接近正常阅读段落。
2. 对文字很少或没有文字层的页面，渲染为高清页面图，保留原始版式。
3. 如果扫描页仍能抽到少量 PDF 内置文字，会折叠显示在页面下方，方便后续 OCR 或人工校对。
4. 使用 `--ocr` 时，会调用本机 `tesseract` 对扫描页做中文/英文 OCR，并把“待校对”的 OCR 文本和原始页面图放在同一页。
5. 首页会标记包含图像页的资料为“需要OCR/校对”，便于后续集中处理。
6. 每次构建会写出 `study-html/quality-report.json`，记录扫描页、OCR 页和需要后续处理的页面。

## 质量检查

```bash
python tools/audit_study_html.py
# 只查看报告、不因缺失页面图返回失败：
python tools/audit_study_html.py --allow-missing-images
```

该脚本会统计文档数、页数、图像引用数、缺失图片数、空搜索文本文件数和 `quality-report.json` 中的页面问题数等。若存在缺失页面图，默认会以非 0 状态退出，提醒需要重新生成或补齐资源。
