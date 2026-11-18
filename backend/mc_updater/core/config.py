from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from .models import AppSettings


def get_app_data_dir() -> Path:
    import tempfile

    override = os.environ.get("MC_UPDATER_DATA_DIR")
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p

    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    p = Path(appdata) / "MCModpackUpdater"
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "MCModpackUpdater"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def get_cache_dir() -> Path:
    p = get_app_data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


# --- Windows DPAPI 加密封装 ---

class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi_protect(plaintext: str) -> str:
    if not plaintext:
        return ""
    if sys.platform != "win32":
        return "b64:" + base64.b64encode(plaintext.encode("utf-8")).decode("ascii")
    try:
        raw = plaintext.encode("utf-8")
        in_blob = _DataBlob(len(raw), ctypes.create_string_buffer(raw, len(raw)))
        out_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if not crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0x01, ctypes.byref(out_blob)):
            raise OSError("CryptProtectData failed")
        try:
            encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return "b64:" + base64.b64encode(plaintext.encode("utf-8")).decode("ascii")


def _dpapi_unprotect(cipher: str) -> str:
    if not cipher:
        return ""
    if cipher.startswith("b64:"):
        return base64.b64decode(cipher[4:]).decode("utf-8", errors="ignore")
    if not cipher.startswith("dpapi:"):
        return cipher
    if sys.platform != "win32":
        return ""
    try:
        raw = base64.b64decode(cipher[6:])
        in_blob = _DataBlob(len(raw), ctypes.create_string_buffer(raw, len(raw)))
        out_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0x01, ctypes.byref(out_blob)):
            return ""
        try:
            plain = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return plain.decode("utf-8", errors="ignore")
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return ""


class ConfigManager:
    def __init__(self) -> None:
        self.config_path = get_app_data_dir() / "config.json"

    def load(self) -> AppSettings:
        if not self.config_path.exists():
            return AppSettings()
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            if "curseforge_api_key_enc" in raw:
                raw["curseforge_api_key"] = _dpapi_unprotect(raw.pop("curseforge_api_key_enc", ""))
            return AppSettings.model_validate(raw)
        except Exception:
            return AppSettings()

    def save(self, settings: AppSettings) -> AppSettings:
        data = settings.model_dump()
        key = data.pop("curseforge_api_key", "")
        data["curseforge_api_key_enc"] = _dpapi_protect(key)
        self.config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return settings


def detect_windows_system_proxy() -> str | None:
    """探测系统代理：优先环境变量，其次 Windows 注册表 WinINet 代理。"""
    for env_key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = os.environ.get(env_key)
        if val:
            return val

    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            ) as key:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if enabled:
                    server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    if server:
                        # 处理 "http=127.0.0.1:7890;https=127.0.0.1:7890" 或纯 "127.0.0.1:7890"
                        if "=" in server:
                            parts = dict(item.split("=", 1) for item in server.split(";") if "=" in item)
                            chosen = parts.get("https") or parts.get("http") or next(iter(parts.values()), "")
                        else:
                            chosen = server
                        if chosen:
                            return chosen if "://" in chosen else f"http://{chosen}"
        except Exception:
            pass

    proxies = urllib.request.getproxies()
    return proxies.get("https") or proxies.get("http")


class FileCache:
    """简单的 JSON 文件缓存，带 TTL（秒）。"""

    def __init__(self, namespace: str) -> None:
        self.base_dir = get_cache_dir() / namespace
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str, ttl_seconds: int = 3600) -> Any | None:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        path = self.base_dir / f"{safe}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - payload.get("ts", 0) > ttl_seconds:
                return None
            return payload.get("data")
        except Exception:
            return None

    def set(self, key: str, data: Any) -> None:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        path = self.base_dir / f"{safe}.json"
        try:
            path.write_text(
                json.dumps({"ts": time.time(), "data": data}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
