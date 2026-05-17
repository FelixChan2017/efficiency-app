"""Feishu API wrappers — direct REST calls, no lark-cli dependency."""
import re
import requests
from feishu_auth import get_token

BASE = "https://open.feishu.cn/open-apis"


def _headers():
    return {"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"}


def _json_or_error(resp, action):
    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"{action}失败: 飞书返回了非 JSON 响应（HTTP {resp.status_code}）") from exc

    if data.get("code") != 0:
        msg = data.get("msg") or data.get("message") or "未知错误"
        raise RuntimeError(f"{action}失败: {msg}（code={data.get('code')}）")

    return data


def resolve_url(url):
    """Resolve Feishu URL to (spreadsheet_token, title)."""
    if "/wiki/" in url:
        wiki_token = url.rstrip("/").split("/")[-1]
        wiki_token = re.sub(r"\?.*", "", wiki_token)
        resp = requests.get(
            f"{BASE}/wiki/v2/spaces/get_node",
            params={"token": wiki_token},
            headers=_headers(),
            timeout=30,
        )
        data = _json_or_error(resp, "解析知识库链接").get("data", {}).get("node", {})
        obj_token = data.get("obj_token", "")
        obj_type = data.get("obj_type", "")
        title = data.get("title", "")
        if obj_type == "sheet":
            return obj_token, title
        raise RuntimeError(f"Wiki节点不是表格 (obj_type={obj_type})")

    m = re.search(r"/sheets/([a-zA-Z0-9_-]+)", url)
    if m:
        token = m.group(1)
        resp = requests.get(
            f"{BASE}/sheets/v3/spreadsheets/{token}",
            headers=_headers(),
            timeout=30,
        )
        d = _json_or_error(resp, "读取表格信息").get("data", {}).get("spreadsheet", {})
        return token, d.get("title", "")

    raise RuntimeError("无法从URL解析表格token")


def get_spreadsheet_info(token):
    """Get sheet list with merges. Returns [{sheet_id, title, row_count, column_count, merges}]."""
    resp = requests.get(
        f"{BASE}/sheets/v3/spreadsheets/{token}/sheets/query",
        headers=_headers(),
        timeout=30,
    )
    sheets = _json_or_error(resp, "读取子表列表").get("data", {}).get("sheets", [])
    result = []
    for s in sheets:
        props = s.get("grid_properties", {})
        result.append({
            "sheet_id": s.get("sheet_id", ""),
            "title": s.get("title", ""),
            "row_count": props.get("row_count", 0),
            "column_count": props.get("column_count", 0),
            "merges": s.get("merges", []),
        })
    return result


def read_sheet_data(token, sheet_id):
    """Read cell values from a sheet via v2 API. Returns 2D list."""
    resp = requests.get(
        f"{BASE}/sheets/v2/spreadsheets/{token}/values/{sheet_id}!A1:CA500",
        headers=_headers(),
        timeout=30,
    )
    vr = _json_or_error(resp, "读取子表数据").get("data", {}).get("valueRange", {})
    return vr.get("values", [])


def create_spreadsheet(title):
    """Create new spreadsheet. Returns {token, url, sheet_id}."""
    resp = requests.post(
        f"{BASE}/sheets/v3/spreadsheets",
        headers=_headers(),
        json={"title": title},
        timeout=30,
    )
    d = _json_or_error(resp, "创建表格").get("data", {}).get("spreadsheet", {})
    token = d.get("spreadsheet_token", "")
    url = d.get("url", "")
    info = get_spreadsheet_info(token)
    sheet_id = info[0]["sheet_id"] if info else ""
    return {"token": token, "url": url, "sheet_id": sheet_id}


def create_sheet(token, title):
    """Add a new sheet to existing spreadsheet via v2 API. Returns sheet_id."""
    resp = requests.post(
        f"{BASE}/sheets/v2/spreadsheets/{token}/sheets_batch_update",
        headers=_headers(),
        json={
            "requests": [{
                "addSheet": {"properties": {"title": title}}
            }]
        },
        timeout=30,
    )
    data = _json_or_error(resp, "创建子表").get("data", {})
    replies = data.get("replies", [])
    if replies:
        props = replies[0].get("addSheet", {}).get("properties", {})
        sheet_id = props.get("sheet_id") or props.get("sheetId")
        if sheet_id:
            return sheet_id

    sheet = data.get("sheet", {})
    sheet_id = sheet.get("sheet_id") or sheet.get("sheetId")
    if sheet_id:
        return sheet_id

    raise RuntimeError("创建子表失败: 飞书返回成功，但响应中没有 sheet_id")


def write_to_sheet(token, sheet_id, values):
    """Write 2D list to sheet via v2 API."""
    rows = []
    for row in values:
        rows.append([str(cell) if cell is not None else "" for cell in row])

    num_rows = len(rows)
    num_cols = max(len(r) for r in rows) if rows else 1
    end_col = _col_letter(num_cols - 1)
    cell_range = f"{sheet_id}!A1:{end_col}{num_rows}"

    resp = requests.put(
        f"{BASE}/sheets/v2/spreadsheets/{token}/values",
        headers=_headers(),
        json={"valueRange": {"range": cell_range, "values": rows}},
        timeout=30,
    )
    _json_or_error(resp, "写入表格")

    verify_rows = read_sheet_data(token, sheet_id)
    if not verify_rows or not verify_rows[0]:
        raise RuntimeError("写入表格失败: 写入接口返回成功，但目标子表回读为空")
    expected_header = rows[0][0] if rows and rows[0] else ""
    actual_header = str(verify_rows[0][0]) if verify_rows[0][0] is not None else ""
    if expected_header and actual_header != expected_header:
        raise RuntimeError("写入表格失败: 目标子表内容校验未通过")


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
