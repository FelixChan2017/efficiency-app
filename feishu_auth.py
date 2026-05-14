"""Feishu auth — tenant access token via App ID + App Secret."""
import json
import os
import time
import requests
from paths import APPDIR

CONFIG_PATH = os.path.join(APPDIR, "feishu_config.json")
TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"


def _read_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _write_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def save_app_config(app_id, app_secret):
    _write_config({"app_id": app_id, "app_secret": app_secret})


def has_app_config():
    cfg = _read_config()
    return bool(cfg.get("app_id") and cfg.get("app_secret"))


def mark_config_validated():
    cfg = _read_config()
    cfg["last_validated_at"] = int(time.time())
    _write_config(cfg)


def get_app_config_status():
    cfg = _read_config()
    return {
        "configured": bool(cfg.get("app_id") and cfg.get("app_secret")),
        "app_id": cfg.get("app_id", ""),
        "last_validated_at": cfg.get("last_validated_at"),
    }


def get_token():
    """Get a valid tenant access token, refreshing if needed."""
    cfg = _read_config()
    token = cfg.get("token")
    expires = cfg.get("token_expires_at", 0)

    if token and time.time() < expires - 300:
        return token

    app_id = cfg.get("app_id")
    app_secret = cfg.get("app_secret")
    if not app_id or not app_secret:
        raise RuntimeError("请先配置飞书应用凭证（App ID 和 App Secret）")

    resp = requests.post(TOKEN_URL, json={
        "app_id": app_id,
        "app_secret": app_secret,
    }, timeout=15)

    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取token失败: {data.get('msg')}")

    cfg["token"] = data["tenant_access_token"]
    cfg["token_expires_at"] = time.time() + data["expire"]
    _write_config(cfg)
    return cfg["token"]
