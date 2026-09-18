"""表格文件解析（AI 助手的「挂载文件」）单测。

这一层是纯函数（不碰数据库、不碰 FastAPI），所以单测直接喂字节。
重点测的是**真实文件里那些脏东西**：GBK 编码、Excel 的日期序列号、公式缓存、
空行、行数截断——这些都是"读出来看着像对的、其实错了"的来源。
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.services.sheet_parser import (
    MAX_BYTES,
    SheetParseError,
    parse_upload,
)


def _xlsx_bytes(build) -> bytes:
    wb = Workbook()
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ xlsx

def test_xlsx_basic_rows_and_types():
    def build(wb):
        ws = wb.active
        ws.title = "商品清单"
        ws.append(["商品名", "单位", "单价", "库存"])
        ws.append(["红富士苹果", "箱", 45.5, 120])
        ws.append(["海南香蕉", "件", 3, 0])

    out = parse_upload("商品.xlsx", _xlsx_bytes(build))
    assert out.kind == "xlsx"
    assert len(out.tables) == 1
    t = out.tables[0]
    assert t.name == "商品清单"
    assert t.rows[0] == ["商品名", "单位", "单价", "库存"]
    assert t.rows[1] == ["红富士苹果", "箱", "45.5", "120"]
    # 整数浮点不许显示成 3.0（Excel 里是 3，读出来也得是 3）
    assert t.rows[2][2] == "3"
    assert t.row_count == 3
    assert t.truncated is False


def test_xlsx_date_cell_is_not_a_serial_number():
    """Excel 的日期存的是序列号，靠样式还原。读出来必须是 2026-09-17，不能是 46252。"""

    def build(wb):
        from datetime import date

        ws = wb.active
        ws.append(["日期", "单号"])
        ws.append([date(2026, 9, 17), "SO-1"])

    t = parse_upload("d.xlsx", _xlsx_bytes(build)).tables[0]
    assert t.rows[1][0] == "2026-09-17"


def test_xlsx_skips_blank_rows_and_trims_blank_cols():
    def build(wb):
        ws = wb.active
        ws.append(["a", "b", None])
        ws.append([None, None, None])
        ws.append(["c", "d", None])

    t = parse_upload("x.xlsx", _xlsx_bytes(build)).tables[0]
    assert t.rows == [["a", "b"], ["c", "d"]]
    assert t.row_count == 2
    assert t.col_count == 2


def test_xlsx_multiple_sheets_and_empty_sheet_warning():
    def build(wb):
        ws = wb.active
        ws.title = "第一张"
        ws.append(["a"])
        ws2 = wb.create_sheet("空的")
        ws3 = wb.create_sheet("第三张")
        ws3.append(["b"])

    out = parse_upload("m.xlsx", _xlsx_bytes(build))
    assert [t.name for t in out.tables] == ["第一张", "第三张"]
    assert any("空的" in w for w in out.warnings)


def test_xlsx_truncation_is_flagged_and_real_count_kept():
    def build(wb):
        ws = wb.active
        for i in range(10):
            ws.append([f"第{i}行"])

    out = parse_upload("t.xlsx", _xlsx_bytes(build), max_rows=3)
    t = out.tables[0]
    assert len(t.rows) == 3
    assert t.row_count == 10
    assert t.truncated is True


def test_broken_xlsx_gives_actionable_message():
    with pytest.raises(SheetParseError) as e:
        parse_upload("坏文件.xlsx", b"this is not a zip at all")
    assert "另存为" in str(e.value)


def test_formula_only_workbook_says_what_to_do():
    """公式没有缓存值 → 一格都读不到。此时必须教用户"选择性粘贴为数值"，而不是返回空表。"""

    def build(wb):
        ws = wb.active
        ws.append(["=SUM(1,2)"])

    wb = Workbook()
    build(wb)
    # 直接用 openpyxl 存出来的是**没有缓存值**的公式（data_only 读回来是 None）
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(SheetParseError) as e:
        parse_upload("公式.xlsx", buf.getvalue())
    assert "选择性粘贴" in str(e.value)


# ------------------------------------------------------------------ csv / txt

def test_csv_utf8_bom():
    data = "商品名,单价\n红富士苹果,45.5\n".encode("utf-8-sig")
    out = parse_upload("a.csv", data)
    assert out.tables[0].rows == [["商品名", "单价"], ["红富士苹果", "45.5"]]
    assert out.warnings == []


def test_csv_gbk_is_decoded_with_a_warning():
    """Windows 的 Excel「另存为 CSV」写的是 GBK。按 UTF-8 硬读会得到一片乱码，
    而模型对乱码照样能一本正经地分析——所以必须退 GBK 并告诉用户。"""
    data = "商品名,单价\n红富士苹果,45.5\n".encode("gb18030")
    out = parse_upload("b.csv", data)
    assert out.tables[0].rows[1][0] == "红富士苹果"
    assert any("GBK" in w for w in out.warnings)


def test_tsv_by_extension():
    data = "名称\t数量\n苹果\t3\n".encode("utf-8")
    out = parse_upload("c.tsv", data)
    assert out.tables[0].rows == [["名称", "数量"], ["苹果", "3"]]


def test_plain_txt_is_one_cell_per_line():
    data = "红富士苹果\n海南香蕉\n".encode("utf-8")
    out = parse_upload("名单.txt", data)
    assert out.tables[0].rows == [["红富士苹果"], ["海南香蕉"]]


def test_csv_truncation_warning_mentions_total():
    data = ("a,b\n" + "".join(f"{i},{i}\n" for i in range(20))).encode("utf-8")
    out = parse_upload("d.csv", data, max_rows=5)
    assert out.tables[0].truncated is True
    assert out.tables[0].row_count == 21
    assert any("21 行" in w for w in out.warnings)


# ------------------------------------------------------------------ 拒绝

def test_legacy_xls_is_rejected_with_instruction():
    with pytest.raises(SheetParseError) as e:
        parse_upload("老表.xls", b"\xd0\xcf\x11\xe0 anything")
    assert ".xlsx" in str(e.value)


def test_unknown_extension_is_rejected():
    with pytest.raises(SheetParseError) as e:
        parse_upload("图.png", b"\x89PNG\r\n\x1a\n")
    assert "支持" in str(e.value)


def test_empty_file_is_rejected():
    with pytest.raises(SheetParseError):
        parse_upload("空.csv", b"")


def test_oversize_is_rejected_before_parsing():
    with pytest.raises(SheetParseError) as e:
        parse_upload("大.csv", b"a" * (MAX_BYTES + 1))
    assert "上限" in str(e.value)


def test_whitespace_only_text_is_rejected():
    with pytest.raises(SheetParseError):
        parse_upload("空.txt", "   \n\n  ".encode("utf-8"))
