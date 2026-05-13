"""人效计算工具 — Flask 主应用"""
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
import models
from lark_reader import fetch_and_parse, create_spreadsheet, create_sheet, write_to_sheet, resolve_url as resolve_feishu_url
from paths import APPDIR

app = Flask(__name__)
app.secret_key = "efficiency-app-secret-key"


@app.route("/")
def index():
    snapshots = models.list_snapshots()
    return render_template("index.html", snapshots=snapshots)


@app.route("/fetch", methods=["POST"])
def fetch():
    url = request.form.get("url", "").strip()
    if not url:
        flash("请输入飞书表格链接", "error")
        return redirect(url_for("index"))

    try:
        title, details = fetch_and_parse(url)
    except Exception as e:
        flash(f"读取表格失败: {e}", "error")
        return redirect(url_for("index"))

    if not details:
        flash("未找到任何作业数据", "warning")
        return redirect(url_for("index"))

    snapshot_id = models.create_snapshot(url, title)
    models.save_snapshot_details(snapshot_id, details)

    flash(f"抓取成功：{title}，共 {len(details)} 条记录", "success")
    return redirect(url_for("snapshot_detail", snapshot_id=snapshot_id))


@app.route("/snapshot/<int:snapshot_id>")
def snapshot_detail(snapshot_id):
    snap, details = models.get_snapshot(snapshot_id)
    if not snap:
        flash("快照不存在", "error")
        return redirect(url_for("index"))

    # Group by sheet
    sheets = {}
    for d in details:
        st = d["sheet_title"]
        if st not in sheets:
            sheets[st] = []
        sheets[st].append(d)

    return render_template("snapshot.html", snap=snap, sheets=sheets)


@app.route("/delete/<int:snapshot_id>", methods=["POST"])
def delete_snapshot(snapshot_id):
    models.delete_snapshot(snapshot_id)
    flash("快照已删除", "info")
    return redirect(url_for("index"))


@app.route("/update-label/<int:snapshot_id>", methods=["POST"])
def update_label(snapshot_id):
    label = request.form.get("label", "").strip()
    models.update_snapshot_label(snapshot_id, label)
    return redirect(url_for("index"))


@app.route("/compare")
def compare():
    snapshots = models.list_snapshots()
    from_id = request.args.get("from")
    to_id = request.args.get("to")

    result = None
    if from_id and to_id:
        from_id = int(from_id)
        to_id = int(to_id)
        from_details = models.get_snapshot_details_by_sheet(from_id)
        to_details = models.get_snapshot_details_by_sheet(to_id)

        # Aggregate by (sheet, worker): sum completed across rounds
        from_index = {}
        for r in from_details:
            key = (r["sheet_title"], r["worker_name"])
            from_index[key] = from_index.get(key, 0) + r["completed_count"]

        to_index = {}
        for r in to_details:
            key = (r["sheet_title"], r["worker_name"])
            to_index[key] = to_index.get(key, 0) + r["completed_count"]

        sheets_order = []
        seen_sheets = set()
        result = []
        for (sheet, worker), to_count in to_index.items():
            prev = from_index.get((sheet, worker), 0)
            diff = to_count - prev
            if diff > 0:
                if sheet not in seen_sheets:
                    seen_sheets.add(sheet)
                    sheets_order.append(sheet)
                result.append({
                    "sheet_title": sheet,
                    "worker_name": worker,
                    "from_count": prev,
                    "to_count": to_count,
                    "work_done": diff,
                    "work_hours": "",
                    "efficiency": "",
                })

    return render_template("compare.html", snapshots=snapshots,
                           from_id=from_id, to_id=to_id, result=result,
                           sheets_order=sheets_order if result else [])


@app.route("/save-efficiency", methods=["POST"])
def save_efficiency():
    from_id = request.form.get("from_id")
    to_id = request.form.get("to_id")

    records = []
    i = 0
    while True:
        worker = request.form.get(f"worker_{i}")
        if worker is None:
            break
        sheet = request.form.get(f"sheet_{i}", "")
        work_done = request.form.get(f"work_done_{i}")
        work_hours = request.form.get(f"work_hours_{i}")

        if work_done and work_hours:
            try:
                done = int(work_done)
                hours = float(work_hours)
                if done > 0 and hours > 0:
                    records.append((int(from_id), int(to_id), worker, done, hours, sheet))
            except (ValueError, TypeError):
                pass
        i += 1

    if records:
        models.save_efficiency_records(records)
        flash(f"已保存 {len(records)} 条人效记录", "success")

    return redirect(url_for("history"))


@app.route("/export-to-feishu", methods=["POST"])
def export_to_feishu():
    from_id = int(request.form.get("from_id"))
    to_id = int(request.form.get("to_id"))
    dest_url = request.form.get("dest_url", "").strip()

    from_snap, _ = models.get_snapshot(from_id)
    to_snap, _ = models.get_snapshot(to_id)

    from_details = models.get_snapshot_details_by_sheet(from_id)
    to_details = models.get_snapshot_details_by_sheet(to_id)

    from_index = {}
    for r in from_details:
        key = (r["sheet_title"], r["worker_name"])
        from_index[key] = from_index.get(key, 0) + r["completed_count"]

    to_index = {}
    for r in to_details:
        key = (r["sheet_title"], r["worker_name"])
        to_index[key] = to_index.get(key, 0) + r["completed_count"]

    rows = [["Sheet", "作业人员", "起始完成量", "结束完成量", "作业增量", "工时（小时）", "人效"]]
    for (sheet, worker), to_count in to_index.items():
        prev = from_index.get((sheet, worker), 0)
        diff = to_count - prev
        if diff > 0:
            rows.append([sheet, worker, str(prev), str(to_count), str(diff), "", ""])

    if len(rows) <= 1:
        flash("没有任何差异数据可导出", "warning")
        return redirect(f"/compare?from={from_id}&to={to_id}")

    from_label = from_snap["label"] or f"快照{from_id}"
    to_label = to_snap["label"] or f"快照{to_id}"
    date_label = to_snap["fetched_at"][:10]

    try:
        if dest_url:
            # Write to existing spreadsheet
            dest_token, _ = resolve_feishu_url(dest_url)
            sheet_title = f"人效对比_{date_label}_{from_label}vs{to_label}"
            sheet_id = create_sheet(dest_token, sheet_title)
            if not sheet_id:
                flash("创建子表失败，请确认链接有效且有编辑权限", "error")
                return redirect(f"/compare?from={from_id}&to={to_id}")
            write_to_sheet(dest_token, sheet_id, rows)
            ss_url = dest_url
        else:
            # Create new spreadsheet
            result = create_spreadsheet(f"人效对比_{date_label}_{from_label}vs{to_label}")
            token = result["token"]
            sheet_id = result.get("sheet_id", "")
            ss_url = result["url"]
            write_to_sheet(token, sheet_id, rows)
    except Exception as e:
        flash(f"导出失败: {e}", "error")
        return redirect(f"/compare?from={from_id}&to={to_id}")

    flash(f"已导出到: {ss_url}", "success")
    return redirect(f"/compare?from={from_id}&to={to_id}")


@app.route("/history")
def history():
    records = models.list_efficiency_records()
    return render_template("history.html", records=records)


if __name__ == "__main__":
    models.init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
