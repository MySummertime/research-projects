"""论文表格导出：CSV（供 Excel 排版）+ Markdown（三线表，供正文直接取用）。"""

from __future__ import annotations

import csv
import os


def write_csv(path: str, header: list, rows: list) -> str:
	"""写出 utf-8-sig 编码的 CSV。"""
	os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
	with open(path, "w", newline="", encoding="utf-8-sig") as handle:
		writer = csv.writer(handle)
		writer.writerow(header)
		writer.writerows(rows)
	return path


def to_markdown(header: list, rows: list, align: str = "c") -> str:
	"""把表头与数据行渲染为 Markdown 三线表。"""
	sep = {"c": ":---:", "l": ":---", "r": "---:"}[align]
	lines = ["| " + " | ".join(str(h) for h in header) + " |"]
	lines.append("|" + "|".join([sep] * len(header)) + "|")
	for row in rows:
		lines.append("| " + " | ".join("" if cell is None else str(cell) for cell in row) + " |")
	return "\n".join(lines)


def write_table(base_path: str, header: list, rows: list, title: str = "", align: str = "c") -> list:
	"""同时写出 CSV 与 Markdown 两种格式，返回生成的文件路径。"""
	base, _ = os.path.splitext(base_path)
	csv_path = write_csv(f"{base}.csv", header, rows)
	md_path = f"{base}.md"
	with open(md_path, "w", encoding="utf-8") as handle:
		if title:
			handle.write(f"**{title}**\n\n")
		handle.write(to_markdown(header, rows, align=align))
		handle.write("\n")
	return [csv_path, md_path]
