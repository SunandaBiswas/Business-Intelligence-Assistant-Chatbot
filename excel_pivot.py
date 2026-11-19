"""
Builds Excel reports in the style departments and executives receive: a title bar, a bordered table with a
header row, a Grand Total row and a Grand Total column, in the colours of a chosen palette.

Three ways to deliver the numbers (MODES):
  Values only         every cell is a plain number
  Totals as formulas  cells are numbers; Grand Total row/column are formulas (=SUM, =MIN, =MAX)
  Full formulas       every cell is a SUMIFS / COUNTIFS / AVERAGEIFS / MINIFS / MAXIFS formula over a data
                      sheet that holds the underlying rows, so the workbook is live and auditable

Look (style): {"palette": report_style palette, "banding": bool, "gridlines": bool, "colour_scale": bool}
A "block" is one table:  make_block(...) -> dict.  build_workbook([block, ...], mode, style=...) -> .xlsx bytes.
"""
import io

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

import report_style as rs

MODES = ("Values only", "Totals as formulas", "Full formulas")
MODE_HELP = ("Values only: plain numbers. Totals as formulas: numbers, with Grand Total row and column as "
             "formulas. Full formulas: every cell is a SUMIFS/COUNTIFS-style formula over a data sheet "
             "included in the file (Min and Max need Excel 2019 or Microsoft 365).")
_IFS = {"Average": "AVERAGEIFS", "Min": "_xlfn.MINIFS", "Max": "_xlfn.MAXIFS"}   # _xlfn. = newer Excel functions


# ------------------------------------------------------------------ blocks
def make_block(title, row_label, wide, agg="Sum", value_label="", row_tot=None, col_tot=None, grand=None,
               show_totals=True, has_cols=True, data=None, data_sheet=None, include_data=False, note=None):
    """One report table. `wide` = rows x columns numbers. For Min/Max/Average pass the true totals."""
    if agg in ("Sum", "Count"):
        row_tot, col_tot = wide.sum(axis=1), wide.sum(axis=0)
        grand = float(wide.to_numpy().sum())
    return {"title": title, "row_label": row_label, "wide": wide, "agg": agg, "value_label": value_label,
            "row_tot": row_tot, "col_tot": col_tot, "grand": grand, "show_totals": show_totals,
            "has_cols": has_cols, "data": data, "data_sheet": data_sheet, "include_data": include_data,
            "note": note, "num_fmt": "#,##0.00" if agg == "Average" else "#,##0"}


def preview_frame(b):
    """The table as it appears in the Excel file (for showing on screen)."""
    out = b["wide"].copy()
    if not b["has_cols"]:
        out.columns = [b["value_label"] or "Total"]
    elif b["show_totals"]:
        out["Grand Total"] = b["row_tot"]
    if b["show_totals"]:
        total = list(b["col_tot"].reindex(b["wide"].columns)) if b["has_cols"] else [b["grand"]]
        if b["has_cols"]:
            total.append(b["grand"])
        out.loc["Grand Total"] = total
    out.index.name = b["row_label"]
    return out


# ------------------------------------------------------------------ data sheet (for full formulas)
def write_data_sheet(wb, name, df, row_label, col_label, value_label, style):
    ws = wb.create_sheet(name[:31])
    pal = style["palette"]
    ws.append([row_label, col_label, value_label])
    for r in df.itertuples(index=False):
        ws.append([r.row_key, r.col_key, None if pd.isna(r.value) else float(r.value)])
    for c in ws[1]:
        c.font = Font(bold=True, color=pal["head_fg"] if pal["head_bg"] else "000000")
        if pal["head_bg"]:
            c.fill = PatternFill("solid", fgColor=pal["head_bg"])
    for letter, width in (("A", 28), ("B", 20), ("C", 18)):
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = "A2"
    last = max(len(df) + 1, 2)
    ws.auto_filter.ref = f"A1:C{last}"
    q = f"'{ws.title}'!"
    return {"rows": f"{q}$A$2:$A${last}", "cols": f"{q}$B$2:$B${last}", "vals": f"{q}$C$2:$C${last}"}


# ------------------------------------------------------------------ formula helpers
def _crit(cell, escape):
    """Criterion for SUMIFS & co. Wildcard characters in a name are escaped so they match literally."""
    if not escape:
        return cell
    return f'SUBSTITUTE(SUBSTITUTE(SUBSTITUTE({cell},"~","~~"),"*","~*"),"?","~?")'


def _ifs(agg, vals, pairs):
    if agg == "Sum":
        return f"SUMIFS({vals},{pairs})"
    if agg == "Count":
        return f"COUNTIFS({pairs})"
    return f'IF(COUNTIFS({pairs})=0,"",{_IFS[agg]}({vals},{pairs}))'


def _number(v):
    return None if v is None or pd.isna(v) else float(v)


# ------------------------------------------------------------------ one table on a sheet
def add_block(ws, top, left, b, mode, ref=None, style=None):
    """Write one table with its top-left corner at (top, left). Returns the first free row below it."""
    style = style or rs.classic_style()
    pal = style["palette"]
    classic = pal.get("classic", False)
    wide, agg = b["wide"], b["agg"]
    rows, cols = list(wide.index), list(wide.columns)
    has_cols, show_totals = b["has_cols"], b["show_totals"]
    row_total_col = show_totals and has_cols
    full = mode == "Full formulas" and ref is not None
    formula_totals = mode != "Values only" and (full or mode == "Totals as formulas")
    fmt = b["num_fmt"]

    c_first = left + 1
    c_last = left + len(cols)
    c_tot = c_last + 1 if row_total_col else None
    c_end = c_tot or c_last
    r_title, r_head, r_first = top, top + 1, top + 2
    r_last = r_first + len(rows) - 1
    r_total = r_last + 1 if show_totals else None
    r_end = r_total or r_last
    L = get_column_letter
    esc_r = any(isinstance(k, str) and any(ch in k for ch in "*?~") for k in rows)
    esc_c = any(isinstance(k, str) and any(ch in k for ch in "*?~") for k in cols)

    # title bar, header row
    ws.merge_cells(start_row=r_title, start_column=left, end_row=r_title, end_column=c_end)
    ws.cell(r_title, left, b["title"])
    ws.cell(r_head, left, b["row_label"])
    for j, ck in enumerate(cols):
        ws.cell(r_head, c_first + j, ck if has_cols else (b["value_label"] or "Total"))
    if row_total_col:
        ws.cell(r_head, c_tot, "Grand Total")

    def vals_pair(rcrit=None, ccrit=None):
        parts = ([f"{ref['rows']},{rcrit}"] if rcrit else []) + ([f"{ref['cols']},{ccrit}"] if ccrit else [])
        return ",".join(parts)

    # body
    for i, rk in enumerate(rows):
        r = r_first + i
        ws.cell(r, left, rk)
        rcrit = _crit(f"${L(left)}{r}", esc_r)
        for j in range(len(cols)):
            c = c_first + j
            if full:
                ccrit = _crit(f"{L(c)}${r_head}", esc_c) if has_cols else None
                ws.cell(r, c, "=" + _ifs(agg, ref["vals"], vals_pair(rcrit, ccrit)))
            else:
                ws.cell(r, c, _number(wide.iat[i, j]))
        if row_total_col:
            rng = f"{L(c_first)}{r}:{L(c_last)}{r}"
            if agg in ("Sum", "Count") and formula_totals:
                ws.cell(r, c_tot, f"=SUM({rng})")
            elif full:
                ws.cell(r, c_tot, "=" + _ifs(agg, ref["vals"], vals_pair(rcrit)))
            elif formula_totals and agg in ("Min", "Max"):
                ws.cell(r, c_tot, f"={agg.upper()}({rng})")
            else:
                ws.cell(r, c_tot, _number(b["row_tot"].loc[rk]))

    # Grand Total row
    if show_totals:
        ws.cell(r_total, left, "Grand Total")
        for j, ck in enumerate(cols):
            c = c_first + j
            rng = f"{L(c)}{r_first}:{L(c)}{r_last}"
            if agg in ("Sum", "Count") and formula_totals:
                ws.cell(r_total, c, f"=SUM({rng})")
            elif full and has_cols:
                ccrit = _crit(f"{L(c)}${r_head}", esc_c)
                ws.cell(r_total, c, "=" + _ifs(agg, ref["vals"], vals_pair(None, ccrit)))
            elif formula_totals and agg in ("Min", "Max"):
                ws.cell(r_total, c, f"={agg.upper()}({rng})")
            elif has_cols:
                ws.cell(r_total, c, _number(b["col_tot"].loc[ck]))
            else:
                ws.cell(r_total, c, _number(b["grand"]))
        if row_total_col:                                          # bottom-right corner
            col_rng = f"{L(c_tot)}{r_first}:{L(c_tot)}{r_last}"
            all_rng = f"{L(c_first)}{r_first}:{L(c_last)}{r_last}"
            if agg in ("Sum", "Count") and formula_totals:
                ws.cell(r_total, c_tot, f"=SUM({col_rng})")
            elif full and agg == "Average":
                ws.cell(r_total, c_tot, f'=IF(COUNT({ref["vals"]})=0,"",AVERAGE({ref["vals"]}))')
            elif full:
                ws.cell(r_total, c_tot, f"={agg.upper()}({ref['vals']})")
            elif formula_totals and agg in ("Min", "Max"):
                ws.cell(r_total, c_tot, f"={agg.upper()}({all_rng})")
            else:
                ws.cell(r_total, c_tot, _number(b["grand"]))

    # ---- look: palette colours, borders, banding
    side = Side(style="thin", color=pal["border"])
    outline = Side(style="medium", color=pal["outline"])
    band_on = style.get("banding", True) and pal.get("band") and not classic
    body_text = "000000" if classic else rs.TEXT
    for r in range(r_title, r_end + 1):
        for c in range(left, c_end + 1):
            cell = ws.cell(r, c)
            cell.border = Border(left=outline if c == left else side, right=outline if c == c_end else side,
                                 top=outline if r == r_title else side, bottom=outline if r == r_end else side)
            in_total = r == r_total or c == c_tot
            if r == r_title:
                cell.font = Font(bold=True, size=11 if classic else 14, color=pal["title_fg"])
                cell.fill = PatternFill("solid", fgColor=pal["title_bg"])
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif r == r_head:
                cell.font = Font(bold=True, color=pal["head_fg"])
                if pal["head_bg"]:
                    cell.fill = PatternFill("solid", fgColor=pal["head_bg"])
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.font = Font(bold=in_total, color=pal["total_fg"] if in_total else body_text)
                if in_total and pal["total_bg"]:
                    cell.fill = PatternFill("solid", fgColor=pal["total_bg"])
                elif band_on and r <= r_last and (r - r_first) % 2 == 1:
                    cell.fill = PatternFill("solid", fgColor=pal["band"])
                if c == left:
                    cell.alignment = Alignment(horizontal="left", vertical="center", indent=0 if classic else 1)
                else:
                    cell.alignment = Alignment(horizontal="right", vertical="center", indent=0 if classic else 1)
                    cell.number_format = fmt
    if not classic:
        ws.row_dimensions[r_title].height = 30
        ws.row_dimensions[r_head].height = 22
        for r in range(r_first, r_end + 1):
            ws.row_dimensions[r].height = 19
    if style.get("colour_scale") and rows and cols:
        ws.conditional_formatting.add(
            f"{L(c_first)}{r_first}:{L(c_last)}{r_last}",
            ColorScaleRule(start_type="min", start_color=pal["scale_lo"], end_type="max", end_color=pal["scale_hi"]))

    label_width = max([len(str(b["row_label"])), 11] + [len(str(k)) for k in rows]) + 5
    first = ws.column_dimensions[L(left)]
    first.width = min(max(first.width or 0, label_width), 60)
    for c in range(c_first, c_end + 1):
        head = str(ws.cell(r_head, c).value or "")
        cd = ws.column_dimensions[L(c)]
        cd.width = max(cd.width or 0, 16, len(head) + 4)

    if b.get("note"):
        note = ws.cell(r_end + 1, left, b["note"])
        note.font = Font(italic=True, size=9, color="7F7F7F")
        return r_end + 4
    return r_end + 3


# ------------------------------------------------------------------ the workbook
def build_workbook(blocks, mode, sheet_name="Report", style=None):
    """Blocks stacked on one sheet (like the department report), plus data sheets when needed."""
    style = style or rs.classic_style()
    pal = style["palette"]
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.column_dimensions["A"].width = 3
    ws.sheet_view.showGridLines = bool(style.get("gridlines", True))
    top = 2
    for i, b in enumerate(blocks, start=1):
        ref = None
        wants_data = b["data"] is not None and (mode == "Full formulas" or b["include_data"])
        if wants_data:
            ref = write_data_sheet(wb, b["data_sheet"] or (f"Data_{i}" if len(blocks) > 1 else "Data"),
                                   b["data"], b["row_label"], "Column" if b["has_cols"] else "Group",
                                   b["value_label"] or "Value", style)
        top = add_block(ws, top, 2, b, mode, ref, style)
    # print-ready: landscape, one page wide, centred; coloured sheet tab
    ws.page_setup.orientation = "landscape"
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_options.horizontalCentered = True
    if pal["head_bg"]:
        ws.sheet_properties.tabColor = pal["head_bg"]
    wb.calculation.fullCalcOnLoad = True                      # Excel calculates every formula when opened
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
