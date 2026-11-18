from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from mc_updater.clients.curseforge import CurseForgeClient
from mc_updater.clients.modrinth import ModrinthClient
from mc_updater.core.hashing import compute_file_hashes
from mc_updater.core.models import (
    FileHashes,
    ModEntry,
    ModPlatform,
    PackAnalysisResult,
    SourceType,
)
from mc_updater.parsers.input_detector import DetectedInput
from mc_updater.parsers.jar_metadata import parse_jar_metadata

_MODRINTH_URL_RE = re.compile(r"cdn\.modrinth\.com/data/([A-Za-z0-9]+)/versions/([A-Za-z0-9]+)/")


async def identify_pack_mods(
    detected: DetectedInput,
    modrinth: ModrinthClient,
    curseforge: CurseForgeClient | None = None,
) -> PackAnalysisResult:
    """四级 Mod 识别流水线：
    1. 整合包清单 (modrinth.index.json / manifest.json)
    2. Modrinth SHA512/SHA1 批量哈希反查
    3. CurseForge Murmur2 指纹批量反查（需 API Key）
    4. Jar 内元数据兜底
    """
    mods: list[ModEntry] = []
    seen_filenames: set[str] = set()

    # --- 第 1 级：清单优先 ---
    if detected.source_type == SourceType.MRPACK and detected.manifest_data:
        files = detected.manifest_data.get("files") or []
        mr_hashes_to_lookup: list[str] = []
        mr_entries_by_sha1: dict[str, ModEntry] = {}

        for f in files:
            rel_path = str(f.get("path", ""))
            if not rel_path.startswith("mods/"):
                continue
            fname = Path(rel_path).name
            hashes = f.get("hashes") or {}
            sha1 = hashes.get("sha1", "")
            sha512 = hashes.get("sha512", "")
            downloads = f.get("downloads") or []
            pid, vid = None, None
            for dl in downloads:
                m = _MODRINTH_URL_RE.search(dl)
                if m:
                    pid, vid = m.group(1), m.group(2)
                    break

            entry = ModEntry(
                uid=str(uuid.uuid4()),
                filename=fname,
                hashes=FileHashes(
                    sha1=sha1,
                    sha512=sha512,
                    md5="",
                    murmur2=0,
                    file_size=int(f.get("fileSize") or 0),
                )
                if (sha1 or sha512)
                else None,
                platform=ModPlatform.MODRINTH if pid else ModPlatform.LOCAL,
                modrinth_project_id=pid,
                modrinth_version_id=vid,
                display_name=fname,
                identified_by="manifest",
            )
            mods.append(entry)
            seen_filenames.add(fname.lower())
            if sha512:
                mr_hashes_to_lookup.append(sha512)
                mr_entries_by_sha1[sha512] = entry
            elif sha1:
                mr_hashes_to_lookup.append(sha1)
                mr_entries_by_sha1[sha1] = entry

        # 若清单仅有 sha1/sha512 无 project_id，通过 Modrinth 批量接口补全 project_id
        if mr_hashes_to_lookup:
            sha512_list = [h for h in mr_hashes_to_lookup if len(h) == 128]
            sha1_list = [h for h in mr_hashes_to_lookup if len(h) == 40]
            try:
                if sha512_list:
                    res512 = await modrinth.get_versions_by_hashes(sha512_list, "sha512")
                    _apply_modrinth_hash_matches(mr_entries_by_sha1, res512)
                if sha1_list:
                    res1 = await modrinth.get_versions_by_hashes(sha1_list, "sha1")
                    _apply_modrinth_hash_matches(mr_entries_by_sha1, res1)
            except Exception:
                pass

    elif detected.source_type == SourceType.CURSEFORGE_ZIP and detected.manifest_data:
        cf_files = detected.manifest_data.get("files") or []
        file_ids = [int(f["fileID"]) for f in cf_files if "fileID" in f]
        mod_ids = [int(f["projectID"]) for f in cf_files if "projectID" in f]

        files_meta: dict[int, dict[str, Any]] = {}
        mods_meta: dict[int, dict[str, Any]] = {}
        if curseforge and curseforge.enabled:
            try:
                files_meta = await curseforge.get_files_batch(file_ids)
                mods_meta = await curseforge.get_mods_batch(mod_ids)
            except Exception:
                pass

        for f in cf_files:
            pid = int(f.get("projectID", 0))
            fid = int(f.get("fileID", 0))
            finfo = files_meta.get(fid, {})
            minfo = mods_meta.get(pid, {})
            fname = finfo.get("fileName") or f"cf-{pid}-{fid}.jar"
            seen_filenames.add(fname.lower())
            mods.append(
                ModEntry(
                    uid=str(uuid.uuid4()),
                    filename=fname,
                    platform=ModPlatform.CURSEFORGE,
                    curseforge_mod_id=pid,
                    curseforge_file_id=fid,
                    slug=minfo.get("slug"),
                    display_name=minfo.get("name") or fname,
                    current_version=finfo.get("displayName") or "",
                    icon_url=(minfo.get("logo") or {}).get("thumbnailUrl"),
                    identified_by="manifest",
                )
            )

    # --- 扫描本地 / overrides 中的 .jar 与 .jar.disabled ---
    disk_entries: list[ModEntry] = []
    if detected.mods_dir and detected.mods_dir.is_dir():
        for jar_path in sorted(detected.mods_dir.iterdir()):
            if not jar_path.is_file():
                continue
            low = jar_path.name.lower()
            if low.endswith(".jar"):
                disabled = False
            elif low.endswith(".jar.disabled"):
                disabled = True
            else:
                continue

            if jar_path.name.lower() in seen_filenames:
                continue

            hashes = compute_file_hashes(jar_path)
            jmeta = parse_jar_metadata(jar_path)
            entry = ModEntry(
                uid=str(uuid.uuid4()),
                filename=jar_path.name,
                local_path=str(jar_path),
                disabled=disabled,
                hashes=hashes,
                jar_meta=jmeta,
                platform=ModPlatform.LOCAL,
                slug=jmeta.mod_id or None,
                display_name=jmeta.name or jar_path.stem,
                current_version=jmeta.version or "",
                identified_by="jar_metadata",
            )
            disk_entries.append(entry)
            mods.append(entry)

    # --- 第 2 级：Modrinth 批量哈希反查 ---
    if disk_entries:
        by_sha512 = {e.hashes.sha512: e for e in disk_entries if e.hashes}
        matched_uids: set[str] = set()
        try:
            res512 = await modrinth.get_versions_by_hashes(list(by_sha512.keys()), "sha512")
            for h, vobj in res512.items():
                if h in by_sha512:
                    entry = by_sha512[h]
                    _apply_single_modrinth_version(entry, vobj)
                    matched_uids.add(entry.uid)
        except Exception:
            pass

        unmatched = [e for e in disk_entries if e.uid not in matched_uids and e.hashes]
        if unmatched:
            by_sha1 = {e.hashes.sha1: e for e in unmatched if e.hashes}
            try:
                res1 = await modrinth.get_versions_by_hashes(list(by_sha1.keys()), "sha1")
                for h, vobj in res1.items():
                    if h in by_sha1:
                        entry = by_sha1[h]
                        _apply_single_modrinth_version(entry, vobj)
                        matched_uids.add(entry.uid)
            except Exception:
                pass

        # --- 第 3 级：CurseForge 指纹反查 ---
        still_unmatched = [e for e in disk_entries if e.uid not in matched_uids and e.hashes]
        if still_unmatched and curseforge and curseforge.enabled:
            by_fp = {e.hashes.murmur2: e for e in still_unmatched if e.hashes and e.hashes.murmur2}
            try:
                fp_matches = await curseforge.match_fingerprints(list(by_fp.keys()))
                cf_mod_ids = [int(m["id"]) for m in fp_matches.values() if "id" in m]
                cf_mods_meta = await curseforge.get_mods_batch(cf_mod_ids) if cf_mod_ids else {}
                for fp, m_obj in fp_matches.items():
                    entry = by_fp.get(fp)
                    if not entry:
                        continue
                    cf_mid = int(m_obj.get("id", 0))
                    cf_file = m_obj.get("file") or {}
                    minfo = cf_mods_meta.get(cf_mid, {})
                    entry.platform = ModPlatform.CURSEFORGE
                    entry.curseforge_mod_id = cf_mid
                    entry.curseforge_file_id = int(cf_file.get("id", 0)) or None
                    entry.slug = minfo.get("slug") or entry.slug
                    entry.display_name = minfo.get("name") or entry.display_name
                    entry.icon_url = (minfo.get("logo") or {}).get("thumbnailUrl")
                    entry.identified_by = "curseforge_fp"
            except Exception:
                pass

    # --- 批量补全 Modrinth 项目名称与图标 ---
    mr_pids = [m.modrinth_project_id for m in mods if m.modrinth_project_id]
    if mr_pids:
        try:
            projects = await modrinth.get_projects_batch([p for p in mr_pids if p])
            for m in mods:
                if m.modrinth_project_id and m.modrinth_project_id in projects:
                    pinfo = projects[m.modrinth_project_id]
                    m.display_name = pinfo.get("title") or m.display_name
                    m.slug = pinfo.get("slug") or m.slug
                    m.icon_url = pinfo.get("icon_url") or m.icon_url
        except Exception:
            pass

    return PackAnalysisResult(
        source_path=detected.source_path,
        source_type=detected.source_type,
        pack_name=detected.pack_name,
        mc_version=detected.mc_version,
        loader=detected.loader,
        loader_version=detected.loader_version,
        isolation_mode=detected.isolation_mode,  # type: ignore[arg-type]
        needs_shared_confirmation=detected.needs_shared_confirmation,
        shared_mods_path=detected.shared_mods_path,
        mods=mods,
        config_items=detected.config_items,
        warnings=detected.warnings,
        extracted_dir=str(detected.extracted_dir) if detected.extracted_dir else None,
    )


def _apply_single_modrinth_version(entry: ModEntry, vobj: dict[str, Any]) -> None:
    entry.platform = ModPlatform.MODRINTH
    entry.modrinth_project_id = vobj.get("project_id")
    entry.modrinth_version_id = vobj.get("id")
    entry.current_version = vobj.get("version_number") or entry.current_version
    entry.identified_by = "modrinth_hash"


def _apply_modrinth_hash_matches(
    entries_by_hash: dict[str, ModEntry],
    res: dict[str, dict[str, Any]],
) -> None:
    for h, vobj in res.items():
        if h in entries_by_hash:
            entry = entries_by_hash[h]
            entry.platform = ModPlatform.MODRINTH
            entry.modrinth_project_id = vobj.get("project_id") or entry.modrinth_project_id
            entry.modrinth_version_id = vobj.get("id") or entry.modrinth_version_id
            entry.current_version = vobj.get("version_number") or entry.current_version
