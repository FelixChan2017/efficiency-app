"""Read and parse Feishu spreadsheets via direct REST API."""
from feishu_api import (
    resolve_url as _resolve_url,
    get_spreadsheet_info as _get_spreadsheet_info,
    read_sheet_data as _read_sheet_data,
    create_spreadsheet as _create_spreadsheet,
    create_sheet as _create_sheet,
    write_to_sheet as _write_to_sheet,
)


def resolve_url(url):
    return _resolve_url(url)


def get_spreadsheet_info(token):
    return _get_spreadsheet_info(token)


def read_sheet_data(token, sheet_id):
    return _read_sheet_data(token, sheet_id)


def create_spreadsheet(title):
    return _create_spreadsheet(title)


def create_sheet(token, title):
    return _create_sheet(token, title)


def write_to_sheet(token, sheet_id, values):
    return _write_to_sheet(token, sheet_id, values)


def _to_text(cell):
    """Convert a cell value (possibly complex type) to plain text."""
    if cell is None:
        return None
    if isinstance(cell, str):
        return cell
    if isinstance(cell, (int, float)):
        return str(cell)
    if isinstance(cell, list):
        parts = []
        for item in cell:
            if isinstance(item, dict):
                t = item.get("text", "")
                if t:
                    parts.append(t)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts) if parts else None
    if isinstance(cell, dict):
        return cell.get("text", None)
    return str(cell)


def _find_column(rows, keywords, max_col=80):
    """Find column index whose header contains any of the given keywords."""
    if not rows:
        return None
    header = rows[0]
    for i, cell in enumerate(header[:max_col]):
        text = (_to_text(cell) or "").strip()
        for kw in keywords:
            if kw in text:
                return i
    return None


def parse_sheet(rows, merges):
    """
    Parse a sheet to count completed assignments per worker.

    For each 6-row merged block in the worker columns:
    - Worker name in the merged cell → 1 task assigned
    - "是" in completion merged cell → completed

    Returns list of (worker_name, round, completed, total).
    """
    if not rows or len(rows) < 2:
        return []

    r1_worker_col = _find_column(rows, ["一轮-领取人", "一轮作业人员"])
    r1_done_col = _find_column(rows, ["一轮是否评估完成", "一轮是否完成"])
    r2_worker_col = _find_column(rows, ["二轮-领取人", "二轮作业人员"])
    r2_done_col = _find_column(rows, ["二轮是否评估完成", "二轮是否完成"])

    if not r1_worker_col and not r2_worker_col:
        return []

    # Build merge lookup: {(row, col): (start_row, end_row, start_col, end_col)}
    merge_at = {}
    for m in merges:
        sr = m.get("start_row_index", m.get("startRowIndex", 0))
        er = m.get("end_row_index", m.get("endRowIndex", 0))
        sc = m.get("start_column_index", m.get("startColumnIndex", 0))
        ec = m.get("end_column_index", m.get("endColumnIndex", 0))
        for r in range(sr, er + 1):
            for c in range(sc, ec + 1):
                merge_at[(r, c)] = (sr, er, sc, ec)

    # Collect all unique merge blocks from worker columns
    blocks = set()
    for (r, c), (sr, er, sc, ec) in merge_at.items():
        if er - sr < 2:
            continue
        if r1_worker_col is not None and sc <= r1_worker_col <= ec:
            blocks.add(("一轮", sr, er, sc, ec))
        if r2_worker_col is not None and sc <= r2_worker_col <= ec:
            blocks.add(("二轮", sr, er, sc, ec))

    worker_stats = {}

    for round_name, sr, er, sc, ec in blocks:
        worker_name = None
        if round_name == "一轮" and r1_worker_col is not None:
            worker_name = _to_text(_safe_get(rows, sr, r1_worker_col))
            done_col = r1_done_col
        elif round_name == "二轮" and r2_worker_col is not None:
            worker_name = _to_text(_safe_get(rows, sr, r2_worker_col))
            done_col = r2_done_col
        else:
            continue

        if not worker_name or not worker_name.strip():
            continue

        name = worker_name.strip()
        if name not in worker_stats:
            worker_stats[name] = {"一轮": [0, 0], "二轮": [0, 0]}

        worker_stats[name][round_name][1] += 1

        if done_col is not None:
            done_val = _to_text(_safe_get(rows, sr, done_col))
            if done_val and "是" in done_val:
                worker_stats[name][round_name][0] += 1

    results = []
    for name, rounds in worker_stats.items():
        for rd, (completed, total) in rounds.items():
            if total > 0:
                results.append((name, rd, completed, total))

    return results


def _safe_get(rows, row, col):
    try:
        if row < len(rows) and col < len(rows[row]):
            return rows[row][col]
    except (IndexError, KeyError):
        pass
    return None


def fetch_and_parse(url):
    """
    Fetch spreadsheet from URL and parse all sheets.
    Returns (spreadsheet_title, [(sheet_title, worker_name, round, completed, total), ...])
    """
    token, title = resolve_url(url)
    sheets = get_spreadsheet_info(token)
    all_details = []

    for sheet in sheets:
        sheet_id = sheet["sheet_id"]
        sheet_title = sheet["title"]
        merges = sheet.get("merges", [])

        if not sheet_id:
            continue

        try:
            rows = read_sheet_data(token, sheet_id)
        except Exception:
            continue

        if not rows:
            continue

        for worker_name, rd, completed, total in parse_sheet(rows, merges):
            all_details.append((sheet_title, worker_name, rd, completed, total))

    return title, all_details
