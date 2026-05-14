"""人效计算工具 — Flask 主应用"""
from datetime import datetime
import os
import sys
from flask import Flask, render_template, request, redirect, url_for, flash
import models
from lark_reader import fetch_and_parse, create_spreadsheet, create_sheet, write_to_sheet, resolve_url as resolve_feishu_url
from feishu_auth import save_app_config, has_app_config, get_token, mark_config_validated, get_app_config_status


def resource_path(relative_path):
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, relative_path)


app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static"),
)
app.secret_key = "efficiency-app-secret-key"


def _format_ts(ts):
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _sheet_title(base_title):
    return base_title[:80]


def _create_unique_sheet(token, base_title):
    title = _sheet_title(base_title)
    try:
        return create_sheet(token, title), title
    except RuntimeError as exc:
        if "code=90210" not in str(exc) and "already exist" not in str(exc):
            raise

    suffix = datetime.now().strftime("%H%M%S")
    title = _sheet_title(f"{base_title}_{suffix}")
    return create_sheet(token, title), title


@app.route("/")
def index():
    snapshots = models.list_snapshots()
    return render_template("index.html", snapshots=snapshots, has_feishu_config=has_app_config())


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        app_id = request.form.get("app_id", "").strip()
        app_secret = request.form.get("app_secret", "").strip()

        if not app_id or not app_secret:
            flash("请输入 App ID 和 App Secret", "error")
            return redirect(url_for("settings"))

        save_app_config(app_id, app_secret)
        try:
            get_token()
        except Exception as e:
            flash(f"凭证已保存，但验证失败: {e}", "error")
            return redirect(url_for("settings"))

        mark_config_validated()
        flash("飞书应用凭证已保存并验证通过", "success")
        return redirect(url_for("index"))

    status = get_app_config_status()
    status["last_validated_display"] = _format_ts(status["last_validated_at"])
    return render_template("settings.html", status=status)


@app.route("/fetch", methods=["POST"])
def fetch():
    url = request.form.get("url", "").strip()
    if not url:
        flash("请输入飞书表格链接", "error")
        return redirect(url_for("index"))

    try:
        title, details, warnings = fetch_and_parse(url, include_warnings=True)
    except Exception as e:
        flash(f"读取表格失败: {e}", "error")
        return redirect(url_for("index"))

    if not details:
        flash("未找到任何作业数据", "warning")
        return redirect(url_for("index"))

    snapshot_id = models.create_snapshot(url, title)
    models.save_snapshot_details(snapshot_id, details)

    flash(f"抓取成功：{title}，共 {len(details)} 条记录", "success")
    if warnings:
        flash("部分子表未计入：" + "；".join(warnings[:5]), "warning")
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


@app.route("/workers")
def workers():
    worker_list = models.list_workers()
    snapshots = models.list_snapshots()
    suggestions = []
    if snapshots:
        latest = snapshots[0]
        agg = models.get_snapshot_worker_agg(latest["id"])
        existing = {w["worker_name"] for w in worker_list}
        suggestions = [r["worker_name"] for r in agg if r["worker_name"] not in existing]
    return render_template("workers.html", workers=worker_list, suggestions=suggestions)


@app.route("/workers/add", methods=["POST"])
def workers_add():
    name = request.form.get("name", "").strip()
    company = request.form.get("company", "").strip()
    if name:
        if not models.add_worker(name, company):
            flash(f"「{name}」已在名单中", "warning")
    return redirect(url_for("workers"))


@app.route("/workers/update/<int:worker_id>", methods=["POST"])
def workers_update(worker_id):
    company = request.form.get("company", "").strip()
    hours = request.form.get("hours", "").strip()
    if "company" in request.form:
        models.update_worker_company(worker_id, company)
    if "hours" in request.form:
        try:
            h = float(hours)
            if h > 0:
                models.update_worker_hours(worker_id, h)
            else:
                flash("工时必须大于 0", "warning")
        except (ValueError, TypeError):
            flash("工时格式不正确", "warning")
    return redirect(url_for("workers"))


@app.route("/workers/delete/<int:worker_id>", methods=["POST"])
def workers_delete(worker_id):
    models.remove_worker(worker_id)
    return redirect(url_for("workers"))


@app.route("/hours")
def hours_page():
    workers = models.list_workers()
    return render_template("hours.html", workers=workers)


@app.route("/hours", methods=["POST"])
def hours_save():
    invalid = []
    for w in models.list_workers():
        wid = str(w["id"])
        val = request.form.get(f"hours_{wid}")
        if val:
            try:
                h = float(val)
                if h > 0:
                    models.update_worker_hours(w["id"], h)
                else:
                    invalid.append(w["worker_name"])
            except (ValueError, TypeError):
                invalid.append(w["worker_name"])
    if invalid:
        flash("以下人员工时未更新，请输入大于 0 的数字：" + "、".join(invalid), "warning")
    else:
        flash("工时已更新", "success")
    return redirect(url_for("hours_page"))


@app.route("/dashboard")
def dashboard():
    snapshots = models.list_snapshots()
    from_id = request.args.get("from_id")
    to_id = request.args.get("to_id")

    # Auto-select latest two snapshots
    if not from_id and not to_id and len(snapshots) >= 2:
        from_id = str(snapshots[1]["id"])
        to_id = str(snapshots[0]["id"])

    result = None
    from_label = ""
    to_label = ""
    if from_id and to_id:
        from_id = int(from_id)
        to_id = int(to_id)
        from_agg = {r["worker_name"]: r["completed"] for r in models.get_snapshot_worker_agg(from_id)}
        to_agg = {r["worker_name"]: r["completed"] for r in models.get_snapshot_worker_agg(to_id)}
        info_map = models.get_worker_info_map()

        from_snap, _ = models.get_snapshot(from_id)
        to_snap, _ = models.get_snapshot(to_id)
        from_label = from_snap["label"] or f"快照{from_id}"
        to_label = to_snap["label"] or f"快照{to_id}"

        result = []
        for name, info in info_map.items():
            prev = from_agg.get(name, 0)
            curr = to_agg.get(name, 0)
            diff = curr - prev
            result.append({
                "worker_name": name,
                "company": info["company"],
                "from_count": prev,
                "to_count": curr,
                "work_done": diff,
                "work_hours": info["hours"],
            })

    return render_template("dashboard.html", snapshots=snapshots,
                           from_id=from_id, to_id=to_id, result=result,
                           from_label=from_label, to_label=to_label)


@app.route("/dashboard/export", methods=["POST"])
def dashboard_export():
    from_id = int(request.form.get("from_id"))
    to_id = int(request.form.get("to_id"))
    dest_url = request.form.get("dest_url", "").strip()

    from_agg = {r["worker_name"]: r["completed"] for r in models.get_snapshot_worker_agg(from_id)}
    to_agg = {r["worker_name"]: r["completed"] for r in models.get_snapshot_worker_agg(to_id)}
    info_map = models.get_worker_info_map()

    rows = [["作业人员", "公司", "作业增量", "工时（小时）", "人效"]]
    for name, info in info_map.items():
        diff = to_agg.get(name, 0) - from_agg.get(name, 0)
        hours = info["hours"]
        eff = diff / hours if hours > 0 else 0
        rows.append([name, info["company"], str(diff), str(hours), f"{eff:.2f}"])

    from_snap, _ = models.get_snapshot(from_id)
    to_snap, _ = models.get_snapshot(to_id)
    from_label = from_snap["label"] or f"快照{from_id}"
    to_label = to_snap["label"] or f"快照{to_id}"
    date_label = to_snap["fetched_at"][:10]

    try:
        if dest_url:
            dest_token, _ = resolve_feishu_url(dest_url)
            base_title = f"人效看板_{date_label}_{from_label}vs{to_label}"
            sheet_id, sheet_title = _create_unique_sheet(dest_token, base_title)
            if not sheet_id:
                flash("创建子表失败，请确认链接有效且有编辑权限", "error")
                return redirect(url_for("dashboard", from_id=from_id, to_id=to_id))
            write_to_sheet(dest_token, sheet_id, rows)
            ss_url = dest_url
        else:
            result = create_spreadsheet(_sheet_title(f"人效看板_{date_label}_{from_label}vs{to_label}"))
            token = result["token"]
            sheet_id = result.get("sheet_id", "")
            ss_url = result["url"]
            write_to_sheet(token, sheet_id, rows)
    except Exception as e:
        flash(f"导出失败: {e}", "error")
        return redirect(url_for("dashboard", from_id=from_id, to_id=to_id))

    flash(f"已导出到: {ss_url}", "success")
    return redirect(url_for("dashboard", from_id=from_id, to_id=to_id))


@app.route("/history")
def history():
    records = models.list_efficiency_records()
    return render_template("history.html", records=records)


if __name__ == "__main__":
    import os, socket, sys, webbrowser, threading

    def _pick_port(preferred_port):
        port = preferred_port
        while True:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                try:
                    sock.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    port += 1

    models.init_db()
    port = _pick_port(int(os.environ.get("PORT", "5000")))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1" and not getattr(sys, "frozen", False)
    if getattr(sys, "frozen", False):
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="127.0.0.1", port=port, debug=debug)
