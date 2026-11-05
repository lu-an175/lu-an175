# -*- coding: utf-8 -*-
"""在当前目录生成一个 .docx 格式的 Word 文件"""
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import datetime
import os

doc = Document()

# 标题
title = doc.add_heading("示例 Word 文档", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER

# 正文段落
doc.add_paragraph("这是一个由 python-docx 自动生成的 .docx 格式 Word 文档。")

doc.add_heading("一、说明", level=1)
doc.add_paragraph("本文件用于演示在本地批量生成 Word 文档的能力。")

doc.add_heading("二、特性", level=1)
for item in ["支持中文字符", "支持标题层级", "支持段落与列表", "兼容 Microsoft Word / WPS"]:
    doc.add_paragraph(item, style="List Bullet")

doc.add_heading("三、生成信息", level=1)
p = doc.add_paragraph()
p.add_run("生成时间：").bold = True
p.add_run(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

out_path = os.path.join(os.getcwd(), "示例文档.docx")
doc.save(out_path)
print("已生成:", out_path)
