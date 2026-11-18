from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlparse

import httpx

from mc_updater.clients.http_client import USER_AGENT, build_proxy_url
from mc_updater.core.hashing import compute_file_hashes
from mc_updater.core.models import (
    AppSettings,
    CandidateVersion,
    CompatStatus,
    DownloadReport,
    FileHashes,
    ModDownloadItemState,
    ModDownloadStatus,
    ModPlatform,
    ModUpgradePlan,
)

MRPACK_ALLOWED_DOMAINS = {
    "cdn.modrinth.com",
    "github.com",
    "raw.githubusercontent.com",
    "gitlab.com",
}


def is_whitelisted_mrpack_url(url: str | None) -> bool:
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host in MRPACK_ALLOWED_DOMAINS


def _rewrite_download_url(url: str, use_mcim: bool) -> list[str]:
    if use_mcim and "cdn.modrinth.com" in url:
        return [url.replace("https://cdn.modrinth.com", "https://mod.mcimirror.top"), url]
    return [url]


class CancelSignal(Protocol):
    def is_set(self) -> bool: ...


def _is_existing_file_valid(final_path: Path, cand: CandidateVersion) -> FileHashes | None:
    """校验本地已存在的目标文件是否与候选版本哈希/大小一致，一致则可直接复用。"""
    if not final_path.is_file():
        return None
    try:
        hashes = compute_file_hashes(final_path)
    except OSError:
        return None

    if cand.sha512 and hashes.sha512.lower() != cand.sha512.lower():
        return None
    if cand.sha1 and hashes.sha1.lower() != cand.sha1.lower():
        return None
    if cand.md5 and hashes.md5.lower() != cand.md5.lower():
        return None
    if not (cand.sha512 or cand.sha1 or cand.md5):
        if cand.file_size > 0 and hashes.file_size != cand.file_size:
            return None
        if hashes.file_size <= 0:
            return None
    return hashes


async def download_upgrade_plans(
    plans: list[ModUpgradePlan],
    dest_dir: Path,
    settings: AppSettings,
    *,
    skip_modrinth_files: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
    on_item_update: Callable[[ModDownloadItemState], None] | None = None,
    cancel_event: CancelSignal | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> DownloadReport:
    """并发流式下载选中的 Mod 并校验 SHA-512 / SHA-1 / MD5，支持中断保留与已下载复用。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    report = DownloadReport()

    def _notify_item(state: ModDownloadItemState) -> None:
        if on_item_update:
            on_item_update(state)

    to_download: list[ModUpgradePlan] = []
    reused_count = 0

    for p in plans:
        if p.user_action == "manual_jar" and p.manual_jar_path and Path(p.manual_jar_path).is_file():
            hashes = compute_file_hashes(p.manual_jar_path)
            report.downloaded_files[p.uid] = p.manual_jar_path
            report.verified_hashes[p.uid] = hashes
            st = ModDownloadItemState(
                uid=p.uid,
                status=ModDownloadStatus.DOWNLOADED,
                file_path=p.manual_jar_path,
                downloaded_bytes=hashes.file_size,
                total_bytes=hashes.file_size,
            )
            report.item_states[p.uid] = st
            _notify_item(st)
            continue

        if p.user_action == "keep_original" or p.status == CompatStatus.KEEP_ORIGINAL:
            st = ModDownloadItemState(uid=p.uid, status=ModDownloadStatus.KEEP_ORIGINAL)
            report.item_states[p.uid] = st
            _notify_item(st)
            continue

        if p.user_action == "skip" or p.status in (
            CompatStatus.SKIPPED,
            CompatStatus.UNAVAILABLE,
            CompatStatus.MANUAL_REQUIRED,
        ):
            st = ModDownloadItemState(uid=p.uid, status=ModDownloadStatus.SKIPPED)
            report.item_states[p.uid] = st
            _notify_item(st)
            continue

        cand = p.selected_candidate
        if not cand or not cand.download_url:
            st = ModDownloadItemState(uid=p.uid, status=ModDownloadStatus.SKIPPED)
            report.item_states[p.uid] = st
            _notify_item(st)
            continue

        if (
            skip_modrinth_files
            and cand.platform == ModPlatform.MODRINTH
            and is_whitelisted_mrpack_url(cand.download_url)
            and cand.sha1
            and cand.sha512
        ):
            report.skipped_modrinth_count += 1
            st = ModDownloadItemState(
                uid=p.uid,
                status=ModDownloadStatus.SKIPPED_FAST,
                total_bytes=cand.file_size or 0,
            )
            report.item_states[p.uid] = st
            _notify_item(st)
            continue

        target_name = cand.filename
        if p.mod.disabled and not target_name.endswith(".disabled"):
            target_name += ".disabled"
        final_path = dest_dir / target_name

        existing_hashes = _is_existing_file_valid(final_path, cand)
        if existing_hashes is not None:
            report.downloaded_files[p.uid] = str(final_path)
            report.verified_hashes[p.uid] = existing_hashes
            reused_count += 1
            st = ModDownloadItemState(
                uid=p.uid,
                status=ModDownloadStatus.DOWNLOADED,
                file_path=str(final_path),
                downloaded_bytes=existing_hashes.file_size,
                total_bytes=existing_hashes.file_size,
            )
            report.item_states[p.uid] = st
            _notify_item(st)
            continue

        st = ModDownloadItemState(
            uid=p.uid,
            status=ModDownloadStatus.PENDING,
            total_bytes=cand.file_size or 0,
        )
        report.item_states[p.uid] = st
        _notify_item(st)
        to_download.append(p)

    total = reused_count + len(to_download)
    completed = reused_count
    if on_progress and total > 0:
        on_progress(completed, total, f"已复用 {reused_count} 个本地已下载 Mod，准备下载其余 {len(to_download)} 个...")

    sem = asyncio.Semaphore(max(1, min(settings.concurrency, 16)))

    proxy = None if transport is not None else build_proxy_url(settings)
    client_kwargs: dict = {
        "headers": {"User-Agent": USER_AGENT},
        "timeout": httpx.Timeout(60.0, connect=15.0),
        "follow_redirects": True,
        "trust_env": settings.proxy_mode == "system",
    }
    if proxy:
        client_kwargs["proxy"] = proxy
    if transport is not None:
        client_kwargs["transport"] = transport

    async with httpx.AsyncClient(**client_kwargs) as client:

        async def _download_one(plan: ModUpgradePlan) -> None:
            nonlocal completed
            cand = plan.selected_candidate
            assert cand and cand.download_url
            item_state = report.item_states[plan.uid]

            if cancel_event and cancel_event.is_set():
                item_state.status = ModDownloadStatus.CANCELLED
                item_state.error = "已中断"
                _notify_item(item_state)
                return

            target_name = cand.filename
            if plan.mod.disabled and not target_name.endswith(".disabled"):
                target_name += ".disabled"
            final_path = dest_dir / target_name
            part_path = dest_dir / f".{target_name}.part"

            async with sem:
                if cancel_event and cancel_event.is_set():
                    item_state.status = ModDownloadStatus.CANCELLED
                    item_state.error = "已中断"
                    _notify_item(item_state)
                    return

                item_state.status = ModDownloadStatus.DOWNLOADING
                item_state.downloaded_bytes = 0
                item_state.error = ""
                _notify_item(item_state)
                if on_progress:
                    on_progress(completed, total, f"正在下载：{plan.mod.display_name}")

                urls = _rewrite_download_url(cand.download_url, settings.use_mcim_mirror)
                last_err = ""
                success = False

                for dl_url in urls:
                    try:
                        async with client.stream("GET", dl_url) as resp:
                            resp.raise_for_status()
                            cl = resp.headers.get("Content-Length")
                            if cl and cl.isdigit() and item_state.total_bytes <= 0:
                                item_state.total_bytes = int(cl)

                            sha1 = hashlib.sha1()
                            sha512 = hashlib.sha512()
                            md5 = hashlib.md5()
                            dl_bytes = 0
                            last_notify_bytes = 0
                            with part_path.open("wb") as fp:
                                async for chunk in resp.aiter_bytes(chunk_size=128 * 1024):
                                    if cancel_event and cancel_event.is_set():
                                        raise asyncio.CancelledError("用户中断下载")
                                    fp.write(chunk)
                                    sha1.update(chunk)
                                    sha512.update(chunk)
                                    md5.update(chunk)
                                    dl_bytes += len(chunk)
                                    item_state.downloaded_bytes = dl_bytes
                                    if dl_bytes - last_notify_bytes >= 256 * 1024:
                                        last_notify_bytes = dl_bytes
                                        _notify_item(item_state)
                                        if on_progress:
                                            on_progress(completed, total, f"正在下载：{plan.mod.display_name}")

                        if cand.sha512 and sha512.hexdigest().lower() != cand.sha512.lower():
                            raise ValueError("SHA-512 校验不匹配")
                        if cand.sha1 and sha1.hexdigest().lower() != cand.sha1.lower():
                            raise ValueError("SHA-1 校验不匹配")
                        if cand.md5 and md5.hexdigest().lower() != cand.md5.lower():
                            raise ValueError("MD5 校验不匹配")

                        os.replace(part_path, final_path)
                        verified = compute_file_hashes(final_path)
                        report.downloaded_files[plan.uid] = str(final_path)
                        report.verified_hashes[plan.uid] = verified
                        item_state.status = ModDownloadStatus.DOWNLOADED
                        item_state.file_path = str(final_path)
                        item_state.downloaded_bytes = verified.file_size
                        item_state.total_bytes = verified.file_size
                        item_state.error = ""
                        _notify_item(item_state)
                        success = True
                        break
                    except asyncio.CancelledError:
                        if part_path.exists():
                            part_path.unlink(missing_ok=True)
                        item_state.status = ModDownloadStatus.CANCELLED
                        item_state.error = "已中断"
                        _notify_item(item_state)
                        return
                    except Exception as exc:
                        last_err = str(exc)
                        if part_path.exists():
                            part_path.unlink(missing_ok=True)
                        continue

                if not success:
                    item_state.status = ModDownloadStatus.FAILED
                    item_state.error = last_err or "下载失败"
                    _notify_item(item_state)
                    report.failed_items.append(
                        {"uid": plan.uid, "name": plan.mod.display_name, "error": item_state.error}
                    )

                completed += 1
                if on_progress:
                    on_progress(completed, total, f"已完成：{plan.mod.display_name}")

        await asyncio.gather(*[_download_one(p) for p in to_download])

    if cancel_event and cancel_event.is_set():
        report.cancelled = True
        for st in report.item_states.values():
            if st.status in (ModDownloadStatus.PENDING, ModDownloadStatus.DOWNLOADING):
                st.status = ModDownloadStatus.CANCELLED
                st.error = "已中断"
                _notify_item(st)

    return report
