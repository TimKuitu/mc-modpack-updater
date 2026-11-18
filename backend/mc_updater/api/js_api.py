from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any

import webview

from mc_updater.clients.curseforge import CurseForgeClient
from mc_updater.clients.http_client import RateLimitedHttpClient
from mc_updater.clients.loader_meta import LoaderMetaClient
from mc_updater.clients.modrinth import ModrinthClient
from mc_updater.core.config import ConfigManager, get_app_data_dir
from mc_updater.core.hashing import compute_file_hashes
from mc_updater.core.models import (
    AppSettings,
    CompatStatus,
    DownloadReport,
    LoaderType,
    ModUpgradePlan,
    PackAnalysisResult,
    ProgressEvent,
    UpgradeAnalysisResult,
)
from mc_updater.downloader.download_manager import download_upgrade_plans
from mc_updater.exporter.backup_exporter import export_config_backup_zip
from mc_updater.exporter.mrpack_exporter import export_pcl2_mrpack
from mc_updater.parsers.input_detector import DetectedInput, detect_and_prepare_input
from mc_updater.parsers.mod_identifier import identify_pack_mods
from mc_updater.resolver.dependency_resolver import resolve_dependencies_and_conflicts
from mc_updater.resolver.upgrade_matcher import match_pack_upgrades


class AsyncRunner:
    """后台守护线程运行独立 asyncio 事件循环，避免阻塞 pywebview 主 GUI 线程。"""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mc-updater-async")
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coro(self, coro: Any) -> Any:
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return fut.result()

    def submit_coro(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


class JsApi:
    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._runner = AsyncRunner()
        self._cfg_mgr = ConfigManager()
        self._settings: AppSettings = self._cfg_mgr.load()
        self._http = RateLimitedHttpClient(settings=self._settings)
        self._modrinth = ModrinthClient(self._http)
        self._curseforge = CurseForgeClient(self._http, api_key=self._settings.curseforge_api_key)
        self._loader_meta = LoaderMetaClient(self._http)

        # 当前会话状态
        self._detected: DetectedInput | None = None
        self._pack_result: PackAnalysisResult | None = None
        self._upgrade_result: UpgradeAnalysisResult | None = None
        self._download_report: DownloadReport | None = None
        self._download_dir: Path = get_app_data_dir() / "downloads"

        # 进度推送（100ms 节流）
        self._last_progress_ts = 0.0
        self._task_state: dict[str, Any] = {
            "running": False,
            "stage": "idle",
            "current": 0,
            "total": 0,
            "message": "",
            "error": "",
            "report": None,
        }

    def attach_window(self, window: webview.Window) -> None:
        self._window = window

    def _emit_progress(self, event: ProgressEvent, force: bool = False) -> None:
        now = time.monotonic()
        self._task_state.update(
            {
                "stage": event.stage,
                "current": event.current,
                "total": event.total,
                "message": event.message,
            }
        )
        if not force and (now - self._last_progress_ts) < 0.1:
            return
        self._last_progress_ts = now
        if self._window:
            payload = json.dumps(event.model_dump(), ensure_ascii=False)
            try:
                self._window.evaluate_js(f"window.__mcUpdaterOnProgress && window.__mcUpdaterOnProgress({payload})")
            except Exception:
                pass

    @staticmethod
    def _ok(data: Any = None) -> dict[str, Any]:
        return {"ok": True, "data": data}

    @staticmethod
    def _err(msg: str) -> dict[str, Any]:
        return {"ok": False, "error": msg}

    # --- 设置 ---
    def get_settings(self) -> dict[str, Any]:
        return self._ok(self._settings.model_dump())

    def save_settings(self, raw: dict[str, Any]) -> dict[str, Any]:
        try:
            self._settings = AppSettings.model_validate(raw)
            self._cfg_mgr.save(self._settings)
            self._http.update_settings(self._settings)
            self._curseforge.api_key = self._settings.curseforge_api_key
            return self._ok(self._settings.model_dump())
        except Exception as exc:
            return self._err(str(exc))

    # --- 对话框 ---
    def pick_pack_file(self) -> dict[str, Any]:
        if not self._window:
            return self._err("窗口未就绪")
        res = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=("Minecraft 整合包 (*.mrpack;*.zip)", "所有文件 (*.*)"),
        )
        if res and len(res) > 0:
            return self._ok(res[0])
        return self._ok(None)

    def pick_pcl2_folder(self) -> dict[str, Any]:
        if not self._window:
            return self._err("窗口未就绪")
        res = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if res and len(res) > 0:
            return self._ok(res[0])
        return self._ok(None)

    def pick_save_mrpack(self, default_name: str = "upgraded-pack.mrpack") -> dict[str, Any]:
        if not self._window:
            return self._err("窗口未就绪")
        res = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=default_name,
            file_types=("Modrinth 整合包 (*.mrpack)",),
        )
        if res:
            path = res[0] if isinstance(res, (list, tuple)) else str(res)
            if not path.lower().endswith(".mrpack"):
                path += ".mrpack"
            return self._ok(path)
        return self._ok(None)

    def pick_save_backup_zip(self, default_name: str = "原配置备份.zip") -> dict[str, Any]:
        if not self._window:
            return self._err("窗口未就绪")
        res = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=default_name,
            file_types=("ZIP 压缩包 (*.zip)",),
        )
        if res:
            path = res[0] if isinstance(res, (list, tuple)) else str(res)
            if not path.lower().endswith(".zip"):
                path += ".zip"
            return self._ok(path)
        return self._ok(None)

    # --- 步骤 1：读取整合包 ---
    def analyze_input(self, path: str, allow_shared_fallback: bool = False) -> dict[str, Any]:
        try:
            detected = detect_and_prepare_input(path, allow_shared_fallback=allow_shared_fallback)
            self._detected = detected
            if detected.needs_shared_confirmation:
                # 先返回需要用户确认非隔离共享目录的状态
                partial = PackAnalysisResult(
                    source_path=detected.source_path,
                    source_type=detected.source_type,
                    pack_name=detected.pack_name,
                    mc_version=detected.mc_version,
                    loader=detected.loader,
                    loader_version=detected.loader_version,
                    isolation_mode="unknown",
                    needs_shared_confirmation=True,
                    shared_mods_path=detected.shared_mods_path,
                    warnings=detected.warnings,
                )
                return self._ok(partial.model_dump())

            async def _run() -> PackAnalysisResult:
                return await identify_pack_mods(detected, self._modrinth, self._curseforge)

            result = self._runner.run_coro(_run())
            self._pack_result = result
            self._upgrade_result = None
            self._download_report = None
            return self._ok(result.model_dump())
        except Exception as exc:
            return self._err(str(exc))

    # --- 步骤 2：目标版本与兼容性分析 ---
    def get_game_versions(self, force_refresh: bool = False) -> dict[str, Any]:
        try:
            versions = self._runner.run_coro(self._modrinth.get_game_versions(force_refresh=force_refresh))
            return self._ok([v.model_dump() for v in versions])
        except Exception as exc:
            return self._err(str(exc))

    def get_recommended_loader(self, mc_version: str, loader_str: str) -> dict[str, Any]:
        try:
            loader = LoaderType(loader_str)
            ver = self._runner.run_coro(self._loader_meta.get_recommended_loader_version(mc_version, loader))
            return self._ok(ver)
        except Exception as exc:
            return self._err(str(exc))

    def check_upgrades(
        self,
        target_mc: str,
        target_loader_str: str,
        target_loader_version: str = "",
        prefer_beta: bool = False,
    ) -> dict[str, Any]:
        if not self._pack_result:
            return self._err("请先导入并识别整合包")
        try:
            target_loader = LoaderType(target_loader_str)

            async def _run() -> UpgradeAnalysisResult:
                plans = await match_pack_upgrades(
                    self._pack_result.mods,  # type: ignore[union-attr]
                    target_mc=target_mc,
                    target_loader=target_loader,
                    modrinth=self._modrinth,
                    curseforge=self._curseforge,
                    prefer_beta=prefer_beta,
                )
                full_plans, dep_warns, conf_warns = await resolve_dependencies_and_conflicts(
                    plans,
                    target_mc=target_mc,
                    target_loader=target_loader,
                    modrinth=self._modrinth,
                    curseforge=self._curseforge,
                )
                loader_ver = target_loader_version
                if not loader_ver:
                    loader_ver = await self._loader_meta.get_recommended_loader_version(target_mc, target_loader)

                counts = _compute_summary_counts(full_plans)
                return UpgradeAnalysisResult(
                    target_mc_version=target_mc,
                    target_loader=target_loader,
                    target_loader_version=loader_ver,
                    plans=full_plans,
                    summary_counts=counts,
                    dependency_warnings=dep_warns,
                    conflict_warnings=conf_warns,
                )

            res = self._runner.run_coro(_run())
            self._upgrade_result = res
            return self._ok(res.model_dump())
        except Exception as exc:
            return self._err(str(exc))

    def update_plan_action(
        self,
        uid: str,
        action: str,
        candidate_version_id: str | None = None,
        manual_jar_path: str | None = None,
    ) -> dict[str, Any]:
        if not self._upgrade_result:
            return self._err("尚未生成升级分析结果")
        plan = next((p for p in self._upgrade_result.plans if p.uid == uid), None)
        if not plan:
            return self._err("未找到指定 Mod 计划")

        if action == "skip":
            plan.user_action = "skip"
            plan.status = CompatStatus.SKIPPED
        elif action == "keep_original":
            plan.user_action = "keep_original"
            plan.status = CompatStatus.KEEP_ORIGINAL
        elif action == "select_candidate" and candidate_version_id:
            cand = next((c for c in plan.candidates if c.version_id == candidate_version_id), None)
            if not cand:
                return self._err("未找到指定候选版本")
            plan.selected_candidate = cand
            plan.user_action = "select_candidate"
            if not cand.allow_distribution or not cand.download_url:
                plan.status = CompatStatus.MANUAL_REQUIRED
            else:
                plan.status = CompatStatus.UPGRADABLE if cand.release_type == "release" else CompatStatus.BETA_ONLY
        elif action == "manual_jar" and manual_jar_path:
            p = Path(manual_jar_path)
            if not p.is_file():
                return self._err("选择的 jar 文件不存在")
            hashes = compute_file_hashes(p)
            cand = plan.selected_candidate
            verified = True
            if cand and cand.sha1 and hashes.sha1.lower() != cand.sha1.lower():
                verified = False
            plan.manual_jar_path = str(p)
            plan.manual_verified = verified
            plan.user_action = "manual_jar"
            plan.status = CompatStatus.UPGRADABLE
            plan.note = "已手动导入校验通过" if verified else "已手动导入（哈希与平台记录不一致，仍可打包）"
        else:
            return self._err("无效的操作参数")

        self._upgrade_result.summary_counts = _compute_summary_counts(self._upgrade_result.plans)
        return self._ok(self._upgrade_result.model_dump())

    def pick_manual_jar_for_mod(self, uid: str) -> dict[str, Any]:
        if not self._window:
            return self._err("窗口未就绪")
        res = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=("Minecraft Mod (*.jar)",),
        )
        if not res:
            return self._ok(None)
        return self.update_plan_action(uid, "manual_jar", manual_jar_path=res[0])

    def open_url_in_browser(self, url: str) -> dict[str, Any]:
        if url.startswith("http://") or url.startswith("https://"):
            webbrowser.open(url)
            return self._ok(True)
        return self._err("非法 URL")

    # --- 步骤 3：并发下载与校验 ---
    def start_download(self, skip_modrinth_files: bool = False) -> dict[str, Any]:
        if not self._upgrade_result:
            return self._err("尚未生成升级分析结果")
        if self._task_state.get("running"):
            return self._err("已有下载任务正在进行中")

        task_id = str(uuid.uuid4())
        session_dl_dir = self._download_dir / task_id[:8]
        plans = list(self._upgrade_result.plans)
        settings = self._settings

        self._task_state = {
            "running": True,
            "stage": "downloading",
            "current": 0,
            "total": len(plans),
            "message": "准备开始下载...",
            "error": "",
            "report": None,
        }

        async def _job() -> None:
            try:
                report = await download_upgrade_plans(
                    plans,
                    session_dl_dir,
                    settings,
                    skip_modrinth_files=skip_modrinth_files,
                    on_progress=lambda cur, tot, msg: self._emit_progress(
                        ProgressEvent(task_id=task_id, stage="downloading", current=cur, total=tot, message=msg)
                    ),
                )
                self._download_report = report
                self._task_state.update(
                    {
                        "running": False,
                        "stage": "done",
                        "current": 1,
                        "total": 1,
                        "message": "下载与校验完成",
                        "report": report.model_dump(),
                    }
                )
                self._emit_progress(
                    ProgressEvent(
                        task_id=task_id,
                        stage="done",
                        current=1,
                        total=1,
                        message="下载与校验完成",
                        detail={"report": report.model_dump()},
                    ),
                    force=True,
                )
            except Exception as exc:
                self._task_state.update(
                    {"running": False, "stage": "error", "error": str(exc), "message": f"下载失败：{exc}"}
                )
                self._emit_progress(
                    ProgressEvent(task_id=task_id, stage="error", message=str(exc)),
                    force=True,
                )

        self._runner.submit_coro(_job())
        return self._ok({"task_id": task_id})

    def get_task_state(self) -> dict[str, Any]:
        return self._ok(self._task_state)

    # --- 步骤 4：导出 .mrpack 与原配置备份 ---
    def export_mrpack(
        self,
        output_path: str,
        pack_name: str,
        version_id: str,
        selected_config_paths: list[str],
    ) -> dict[str, Any]:
        if not self._pack_result or not self._upgrade_result:
            return self._err("请先完成整合包识别与升级匹配")
        try:
            selected_set = set(selected_config_paths)
            for item in self._pack_result.config_items:
                item.selected = item.rel_path in selected_set

            game_dir = self._detected.game_dir if self._detected else None
            report = self._download_report or DownloadReport()
            res = export_pcl2_mrpack(
                pack_name=pack_name or self._pack_result.pack_name,
                version_id=version_id or "1.0.0",
                target_mc=self._upgrade_result.target_mc_version,
                target_loader=self._upgrade_result.target_loader,
                target_loader_version=self._upgrade_result.target_loader_version,
                plans=self._upgrade_result.plans,
                download_report=report,
                game_dir=game_dir,
                config_items=self._pack_result.config_items,
                output_path=output_path,
            )
            return self._ok(res.model_dump())
        except Exception as exc:
            return self._err(str(exc))

    def export_backup_zip(self, output_path: str, selected_config_paths: list[str]) -> dict[str, Any]:
        if not self._pack_result:
            return self._err("请先导入整合包")
        try:
            selected_set = set(selected_config_paths)
            for item in self._pack_result.config_items:
                item.selected = item.rel_path in selected_set
            game_dir = self._detected.game_dir if self._detected else None
            path_str, size, count = export_config_backup_zip(game_dir, self._pack_result.config_items, output_path)
            return self._ok({"output_path": path_str, "file_size": size, "file_count": count})
        except Exception as exc:
            return self._err(str(exc))

    def reveal_in_explorer(self, path: str) -> dict[str, Any]:
        import subprocess
        import sys

        p = Path(path)
        if not p.exists():
            return self._err("文件不存在")
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(p)])
        return self._ok(True)


def _compute_summary_counts(plans: list[ModUpgradePlan]) -> dict[str, int]:
    counts = {
        "total": len(plans),
        "upgradable": 0,
        "beta_only": 0,
        "manual_required": 0,
        "unavailable": 0,
        "keep_original": 0,
        "skipped": 0,
        "auto_deps": 0,
    }
    for p in plans:
        if p.status.value in counts:
            counts[p.status.value] += 1
        if p.is_auto_dependency:
            counts["auto_deps"] += 1
    return counts
