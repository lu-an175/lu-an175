# -*- coding: utf-8 -*-
"""在当前目录生成一个示例 Word 文档。"""
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# 标题
title = doc.add_heading("示例文档", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER

# 副标题/说明
sub = doc.add_paragraph("本文档由 python-docx 自动生成，用于演示 Word 文件的基本结构与常用排版。")
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
sub.runs[0].font.size = Pt(10.5)
sub.runs[0].font.color.rgb = RGBColor(0x66, 0x66, 0x66)

doc.add_paragraph()

# 一级标题
doc.add_heading("一、文档概述", level=1)
doc.add_paragraph(
    "这是一个示例 Word 文档，包含标题、正文段落、项目符号列表以及表格，"
    "可用于验证文档生成工具链是否正常工作。"
)

# 二级标题
doc.add_heading("二、功能要点", level=1)
for item in [
    "支持多级标题（Heading 0~9）",
    "支持正文段落与加粗、斜体等字符格式",
    "支持项目符号与编号列表",
    "支持表格、图片与页眉页脚",
]:
    doc.add_paragraph(item, style="List Bullet")

# 表格
doc.add_heading("三、信息表", level=1)
table = doc.add_table(rows=1, cols=3)
table.style = "Light Grid Accent 1"
hdr = table.rows[0].cells
hdr[0].text = "项目"
hdr[1].text = "说明"
hdr[2].text = "状态"

rows = [
    ("文件名", "示例文档.docx", "已完成"),
    ("格式", ".docx (Office Open XML)", "正常"),
    ("生成方式", "python-docx", "正常"),
]
for r in rows:
    cells = table.add_row().cells
    for i, val in enumerate(r):
        cells[i].text = val

doc.add_paragraph()
doc.add_paragraph("—— 文档结束 ——").alignment = WD_ALIGN_PARAGRAPH.CENTER

out = "示例文档.docx"
doc.save(out)
print("已生成:", out)
