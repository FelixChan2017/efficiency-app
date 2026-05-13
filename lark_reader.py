"""Read and parse Feishu spreadsheets via lark-cli."""
import json
import os
import subprocess
import re


LARK_CLI = "lark-cli.cmd"

# Force UTF-8 for subprocess on Windows
_ENV = os.environ.copy()
_ENV["PYTHONUTF8"] = "1"
_ENV["PYTHONIOENCODING"] = "utf-8"


def _run(*args, **kwargs):
    cmd_parts = [LARK_CLI, *args]
    for k, v in kwargs.items():
        if k == "as_user":
            if v:
                cmd_parts.extend(["--as", "user"])
            continue
        flag = k.replace("_", "-")
        # Fix trailing hyphen from Python reserved word suffixes
        if flag.endswith("-"):
            flag = flag[:-1]
        if v is True:
            cmd_parts.append(f"--{flag}")
        elif v is not False and v is not None:
            cmd_parts.extend([f"--{flag}", str(v)])
    result = subprocess.run(
        cmd_parts, capture_output=True, timeout=120,
        encoding="utf-8", errors="replace", env=_ENV
    )
    if result.returncode != 0:
        err = result.stderr.strip() if result.stderr else result.stdout.strip()
        raise RuntimeError(f"lark-cli error: {err}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout


def resolve_url(url):
    """Resolve a Feishu URL to spreadsheet token. Handles wiki and direct sheet URLs."""
    if "/wiki/" in url:
        wiki_token = url.rstrip("/").split("/")[-1]
        wiki_token = re.sub(r"\?.*", "", wiki_token)
        result = _run("wiki", "spaces", "get_node",
                      params=json.dumps({"token": wiki_token}),
                      as_user=True)
        data = result.get("data", {})
        node = data.get("node", {})
        obj_token = node.get("obj_token", "")
        obj_type = node.get("obj_type", "")
        title = node.get("title", "")
        if obj_type == "sheet":
            return obj_token, title
        raise RuntimeError(f"Wiki node is not a spreadsheet (obj_type={obj_type})")

    result = _run("sheets", "+info", url=url, as_user=True)
    data = result.get("data", {})
    ss = data.get("spreadsheet", {})
    if ss:
        # Handle nested "spreadsheet" key within data.spreadsheet
        inner = ss.get("spreadsheet", ss)
        token = inner.get("spreadsheet_token") or inner.get("token", "")
        title = inner.get("title", "")
        return token, title

    result = result.get("data", {}).get("sheets", {})
    if result:
        raise RuntimeError("Cannot extract token from URL. Try a spreadsheet URL directly.")

    raise RuntimeError("Cannot resolve spreadsheet from URL")


def get_spreadsheet_info(token):
    """Get list of sheets from a spreadsheet token."""
    result = _run("sheets", "+info", spreadsheet_token=token, as_user=True)
    data = result.get("data", {}).get("sheets", {})
    sheets = []
    for s in data.get("sheets", []):
        sheets.append({
            "sheet_id": s.get("sheet_id", ""),
            "title": s.get("title", ""),
            "row_count": s.get("grid_properties", {}).get("row_count", 0),
            "column_count": s.get("grid_properties", {}).get("column_count", 0),
            "merges": s.get("merges", []),
        })
    return sheets


def read_sheet_data(token, sheet_id):
    """Read all cell values from a sheet. Returns 2D list."""
    result = _run("sheets", "+read",
                  spreadsheet_token=token,
                  sheet_id=sheet_id,
                  range="A1:CA500",
                  as_user=True)
    vr = result.get("data", {}).get("valueRange", {})
    return vr.get("values", []), result


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

    # Find columns by header keywords
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

    worker_stats = {}  # {name: {"一轮": [completed, total], "二轮": [completed, total]}}

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
            rows, _ = read_sheet_data(token, sheet_id)
        except Exception:
            continue

        if not rows:
            continue

        for worker_name, rd, completed, total in parse_sheet(rows, merges):
            all_details.append((sheet_title, worker_name, rd, completed, total))

    return title, all_details


def create_spreadsheet(title):
    """Create a new Feishu spreadsheet and return its token, URL, and default sheet_id."""
    result = _run("sheets", "+create", title=title, as_user=True)
    data = result.get("data", {})
    token = data.get("spreadsheet_token", "")
    url = data.get("url", "")
    # Get first sheet ID via get_spreadsheet_info
    sheets_info = get_spreadsheet_info(token)
    sheet_id = sheets_info[0]["sheet_id"] if sheets_info else ""
    return {"token": token, "url": url, "sheet_id": sheet_id}


def create_sheet(token, title):
    """Add a new sheet to an existing spreadsheet. Returns sheet_id."""
    result = _run("sheets", "+create-sheet",
                  spreadsheet_token=token,
                  title=title,
                  as_user=True)
    return result.get("data", {}).get("sheet", {}).get("sheet_id", "")


def write_to_sheet(token, sheet_id, values):
    """
    Write values to a Feishu spreadsheet.
    values is a 2D list: [[row1col1, row1col2, ...], [row2col1, ...]]
    """
    rows = []
    for row in values:
        rows.append([str(cell) if cell is not None else "" for cell in row])

    num_rows = len(rows)
    num_cols = max(len(r) for r in rows) if rows else 1
    end_col = _col_letter(num_cols - 1)
    cell_range = f"A1:{end_col}{num_rows}"

    values_json = json.dumps(rows, ensure_ascii=False)
    _run("sheets", "+write",
         spreadsheet_token=token,
         sheet_id=sheet_id,
         range_=cell_range,
         values=values_json,
         as_user=True)
    return True


def _col_letter(idx):
    """0 -> A, 25 -> Z, 26 -> AA, etc."""
    result = ""
    n = idx
    while True:
        result = chr(ord("A") + n % 26) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result
