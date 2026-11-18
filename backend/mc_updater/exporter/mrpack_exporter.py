from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from mc_updater.core.models import (
    CompatStatus,
    ConfigItem,
    DownloadReport,
    ExportResult,
    LoaderType,
    ModPlatform,
    ModUpgradePlan,
)
from mc_updater.downloader.download_manager import is_whitelisted_mrpack_url
from mc_updater.exporter.overrides_collector import iter_selected_config_files


_MRPACK_LOADER_DEP_KEY = {
    LoaderType.FABRIC: "fabric-loader",
    LoaderType.QUILT: "quilt-loader",
    LoaderType.NEOFORGE: "neoforge",
    LoaderType.FORGE: "forge",
}


def export_pcl2_mrpack(
    *,
    pack_name: str,
    version_id: str,
    target_mc: str,
    target_loader: LoaderType,
    target_loader_version: str,
    plans: list[ModUpgradePlan],
    download_report: DownloadReport,
    game_dir: Path | None,
    config_items: list[ConfigItem],
    output_path: str | Path,
    summary: str = "由 MC 整合包升级助手自动生成",
) -> ExportResult:
    """导出严格兼容 PCL2 / PCL-CE 拖入安装的 .mrpack 整合包。

    策略：
    - 白名单域名 (cdn.modrinth.com / github.com / gitlab.com) 且有 sha1+sha512 的未禁用 Mod 写入 modrinth.index.json files[]；
    - 其余（CurseForge 下载 jar、手动补齐的禁分发 jar、强制保留原版 jar、禁用 .jar.disabled）统一写入 overrides/mods/；
    - 勾选的原配置文件写入 overrides/（不拆分 client-overrides/，确保 PCL2 最大兼容性）。
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    dependencies: dict[str, str] = {"minecraft": target_mc}
    loader_key = _MRPACK_LOADER_DEP_KEY.get(target_loader)
    if loader_key and target_loader_version:
        dependencies[loader_key] = target_loader_version

    index_files: list[dict[str, Any]] = []
    override_jars: list[tuple[Path, str]] = []
    warnings: list[str] = []
    has_non_redist_cf = False

    for plan in plans:
        if plan.user_action == "skip" or plan.status == CompatStatus.SKIPPED:
            continue

        # 1. 用户强制保留原 jar
        if plan.user_action == "keep_original" or plan.status == CompatStatus.KEEP_ORIGINAL:
            if plan.mod.local_path and Path(plan.mod.local_path).is_file():
                p = Path(plan.mod.local_path)
                override_jars.append((p, f"overrides/mods/{p.name}"))
            else:
                warnings.append(f"原 Mod {plan.mod.display_name} 无本地文件，无法保留到 overrides。")
            continue

        # 2. 用户手动导入的禁分发 jar
        if plan.user_action == "manual_jar" and plan.manual_jar_path and Path(plan.manual_jar_path).is_file():
            p = Path(plan.manual_jar_path)
            target_name = p.name + (".disabled" if plan.mod.disabled and not p.name.endswith(".disabled") else "")
            override_jars.append((p, f"overrides/mods/{target_name}"))
            has_non_redist_cf = True
            continue

        cand = plan.selected_candidate
        if not cand or plan.status in (CompatStatus.UNAVAILABLE, CompatStatus.MANUAL_REQUIRED):
            continue

        if cand.platform == ModPlatform.CURSEFORGE and not cand.allow_distribution:
            has_non_redist_cf = True

        # 3. 判断能否写进 modrinth.index.json files[]
        verified = download_report.verified_hashes.get(plan.uid)
        sha1 = (verified.sha1 if verified else None) or cand.sha1
        sha512 = (verified.sha512 if verified else None) or cand.sha512
        fsize = (verified.file_size if verified else 0) or cand.file_size

        if (
            not plan.mod.disabled
            and is_whitelisted_mrpack_url(cand.download_url)
            and sha1
            and sha512
            and fsize > 0
        ):
            index_files.append(
                {
                    "path": f"mods/{cand.filename}",
                    "hashes": {"sha1": sha1, "sha512": sha512},
                    "env": {"client": "required", "server": "required"},
                    "downloads": [cand.download_url],
                    "fileSize": fsize,
                }
            )
        else:
            # 非白名单直链（如 CurseForge CDN）或禁用 Mod -> 放入 overrides/mods/
            local_dl = download_report.downloaded_files.get(plan.uid)
            if local_dl and Path(local_dl).is_file():
                lp = Path(local_dl)
                override_jars.append((lp, f"overrides/mods/{lp.name}"))
            else:
                warnings.append(f"Mod {plan.mod.display_name} 缺少本地下载文件且无法写入在线清单，已跳过。")

    index_payload = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": version_id,
        "name": pack_name,
        "summary": summary,
        "files": index_files,
        "dependencies": dependencies,
    }

    config_count = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(
            "modrinth.index.json",
            json.dumps(index_payload, ensure_ascii=False, indent=2),
        )
        for src_jar, arcname in override_jars:
            zf.write(src_jar, arcname=arcname)
        for src_cfg, rel_posix in iter_selected_config_files(game_dir, config_items):
            zf.write(src_cfg, arcname=f"overrides/{rel_posix}")
            config_count += 1

    # 自检压缩包可读性与规范结构
    with zipfile.ZipFile(out, "r") as zf:
        names = zf.namelist()
        if "modrinth.index.json" not in names:
            raise RuntimeError("导出自检失败：缺少 modrinth.index.json")
        for n in names:
            if n.startswith("/") or ".." in Path(n).parts:
                raise RuntimeError(f"导出自检失败：非法路径 {n}")

    return ExportResult(
        output_path=str(out),
        file_size=out.stat().st_size,
        included_mods_in_index=len(index_files),
        included_mods_in_overrides=len(override_jars),
        included_config_files=config_count,
        has_non_redistributable_cf=has_non_redist_cf,
        warnings=warnings,
    )
