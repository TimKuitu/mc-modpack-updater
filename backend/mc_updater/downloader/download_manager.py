from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from mc_updater.clients.http_client import USER_AGENT, build_proxy_url
from mc_updater.core.hashing import compute_file_hashes
from mc_updater.core.models import (
    AppSettings,
    CompatStatus,
    DownloadReport,
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


async def download_upgrade_plans(
    plans: list[ModUpgradePlan],
    dest_dir: Path,
    settings: AppSettings,
    *,
    skip_modrinth_files: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> DownloadReport:
    """并发流式下载选中的 Mod 并校验 SHA-512 / SHA-1 / MD5，原子替换落盘。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    report = DownloadReport()

    to_download: list[ModUpgradePlan] = []
    for p in plans:
        if p.user_action == "skip" or p.status in (CompatStatus.SKIPPED, CompatStatus.UNAVAILABLE):
            continue
        if p.user_action == "keep_original" or p.status == CompatStatus.KEEP_ORIGINAL:
            continue
        if p.user_action == "manual_jar" and p.manual_jar_path and Path(p.manual_jar_path).is_file():
            report.downloaded_files[p.uid] = p.manual_jar_path
            report.verified_hashes[p.uid] = compute_file_hashes(p.manual_jar_path)
            continue
        cand = p.selected_candidate
        if not cand or not cand.download_url:
            continue
        if (
            skip_modrinth_files
            and cand.platform == ModPlatform.MODRINTH
            and is_whitelisted_mrpack_url(cand.download_url)
            and cand.sha1
            and cand.sha512
        ):
            report.skipped_modrinth_count += 1
            continue
        to_download.append(p)

    total = len(to_download)
    completed = 0
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

            target_name = cand.filename
            if plan.mod.disabled and not target_name.endswith(".disabled"):
                target_name += ".disabled"
            final_path = dest_dir / target_name
            part_path = dest_dir / f".{target_name}.part"

            async with sem:
                urls = _rewrite_download_url(cand.download_url, settings.use_mcim_mirror)
                last_err = ""
                success = False

                for dl_url in urls:
                    try:
                        async with client.stream("GET", dl_url) as resp:
                            resp.raise_for_status()
                            sha1 = hashlib.sha1()
                            sha512 = hashlib.sha512()
                            md5 = hashlib.md5()
                            with part_path.open("wb") as fp:
                                async for chunk in resp.aiter_bytes(chunk_size=128 * 1024):
                                    fp.write(chunk)
                                    sha1.update(chunk)
                                    sha512.update(chunk)
                                    md5.update(chunk)

                        if cand.sha512 and sha512.hexdigest().lower() != cand.sha512.lower():
                            raise ValueError("SHA-512 校验不匹配")
                        if cand.sha1 and sha1.hexdigest().lower() != cand.sha1.lower():
                            raise ValueError("SHA-1 校验不匹配")
                        if cand.md5 and md5.hexdigest().lower() != cand.md5.lower():
                            raise ValueError("MD5 校验不匹配")

                        os.replace(part_path, final_path)
                        report.downloaded_files[plan.uid] = str(final_path)
                        report.verified_hashes[plan.uid] = compute_file_hashes(final_path)
                        success = True
                        break
                    except Exception as exc:
                        last_err = str(exc)
                        if part_path.exists():
                            part_path.unlink(missing_ok=True)
                        continue

                if not success:
                    report.failed_items.append(
                        {"uid": plan.uid, "name": plan.mod.display_name, "error": last_err or "下载失败"}
                    )

                completed += 1
                if on_progress:
                    on_progress(completed, total, f"正在下载：{plan.mod.display_name}")

        await asyncio.gather(*[_download_one(p) for p in to_download])

    return report
