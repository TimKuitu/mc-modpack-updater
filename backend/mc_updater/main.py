from __future__ import annotations

import ctypes
import json
import os
import sys
import webbrowser
from pathlib import Path

import webview
from webview.dom import DOMEventHandler

from mc_updater.api.js_api import JsApi


def check_webview2_installed() -> bool:
    """启动前检测 Windows WebView2 Runtime 是否安装。"""
    if sys.platform != "win32":
        return True
    import winreg

    client_guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    subkeys = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{client_guid}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{client_guid}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{client_guid}"),
    ]
    for root, subkey in subkeys:
        try:
            with winreg.OpenKey(root, subkey) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
                if pv and str(pv).strip() != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def show_webview2_missing_dialog() -> None:
    if sys.platform != "win32":
        return
    msg = (
        "未检测到 Microsoft Edge WebView2 运行时，界面无法正常显示。\n\n"
        "是否立即打开微软官方下载页面安装 Evergreen 运行时（约 1.7MB）？"
    )
    res = ctypes.windll.user32.MessageBoxW(0, msg, "MC 整合包升级助手 - 缺少组件", 0x04 | 0x30)
    if res == 6:  # IDYES
        webbrowser.open("https://developer.microsoft.com/microsoft-edge/webview2/")


def resolve_ui_url() -> str:
    if os.environ.get("MC_UPDATER_DEV_URL"):
        return os.environ["MC_UPDATER_DEV_URL"]

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent

    index_html = base / "ui_dist" / "index.html"
    if index_html.is_file():
        return str(index_html)
    return "http://localhost:5173"


def _bind_drag_and_drop(window: webview.Window) -> None:
    def on_drop(e: dict) -> None:
        files = (e.get("dataTransfer") or {}).get("files") or []
        for f in files:
            full_path = f.get("pywebviewFullPath")
            if full_path:
                payload = json.dumps(str(full_path), ensure_ascii=False)
                window.evaluate_js(
                    f"window.__mcUpdaterOnFileDrop && window.__mcUpdaterOnFileDrop({payload})"
                )
                break

    try:
        doc = window.dom.document
        doc.events.dragenter += DOMEventHandler(lambda e: None, True, True)
        doc.events.dragover += DOMEventHandler(lambda e: None, True, True)
        doc.events.drop += DOMEventHandler(on_drop, True, True)
    except Exception:
        pass


def main() -> None:
    if not check_webview2_installed():
        show_webview2_missing_dialog()
        return

    api = JsApi()
    url = resolve_ui_url()

    window = webview.create_window(
        title="MC 整合包升级助手",
        url=url,
        js_api=api,
        width=1180,
        height=780,
        min_size=(960, 640),
        background_color="#0b101b",
    )
    api.attach_window(window)
    window.events.loaded += lambda: _bind_drag_and_drop(window)

    # 冒烟测试模式：窗口加载完成后自动退出
    if os.environ.get("MC_UPDATER_SMOKE_TEST") == "1":
        def _smoke_close() -> None:
            import time
            time.sleep(1.5)
            window.destroy()

        window.events.loaded += lambda: __import__("threading").Thread(target=_smoke_close, daemon=True).start()

    webview.start(gui="edgechromium", debug=os.environ.get("MC_UPDATER_DEBUG") == "1")


if __name__ == "__main__":
    main()
