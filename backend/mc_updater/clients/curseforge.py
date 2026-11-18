from __future__ import annotations

from typing import Any

from mc_updater.clients.http_client import RateLimitedHttpClient
from mc_updater.core.models import (
    CandidateVersion,
    DependencyRef,
    LoaderType,
    ModPlatform,
)

CURSEFORGE_API = "https://api.curseforge.com/v1"
MINECRAFT_GAME_ID = 432

_LOADER_TAG_MAP: dict[LoaderType, set[str]] = {
    LoaderType.FABRIC: {"fabric"},
    LoaderType.QUILT: {"quilt", "fabric"},  # Quilt 可兼顾标记了 Fabric/Quilt 的部分 Mod，精确匹配优先
    LoaderType.NEOFORGE: {"neoforge"},
    LoaderType.FORGE: {"forge"},
}


def _extract_hashes(file_obj: dict[str, Any]) -> tuple[str | None, str | None]:
    sha1 = None
    md5 = None
    for h in file_obj.get("hashes") or []:
        algo = h.get("algo")
        if algo == 1:
            sha1 = h.get("value")
        elif algo == 2:
            md5 = h.get("value")
    return sha1, md5


def _parse_cf_dependencies(raw_deps: list[dict[str, Any]]) -> list[DependencyRef]:
    deps: list[DependencyRef] = []
    for d in raw_deps:
        rtype = d.get("relationType")
        if rtype == 3:
            dep_type = "required"
        elif rtype == 2:
            dep_type = "optional"
        elif rtype == 5:
            dep_type = "incompatible"
        elif rtype == 1:
            dep_type = "embedded"
        else:
            continue
        deps.append(
            DependencyRef(
                platform=ModPlatform.CURSEFORGE,
                project_id=str(d.get("modId", "")),
                dependency_type=dep_type,
            )
        )
    return deps


def parse_curseforge_file(
    file_obj: dict[str, Any],
    mod_slug: str = "",
) -> CandidateVersion:
    mod_id = int(file_obj.get("modId") or 0)
    file_id = int(file_obj.get("id") or 0)
    sha1, md5 = _extract_hashes(file_obj)
    rel_num = file_obj.get("releaseType", 1)
    rel_type = {1: "release", 2: "beta", 3: "alpha"}.get(rel_num, "release")
    game_versions = list(file_obj.get("gameVersions") or [])

    loaders: list[LoaderType] = []
    gv_lower = {g.lower() for g in game_versions}
    for lt in (LoaderType.FABRIC, LoaderType.NEOFORGE, LoaderType.FORGE, LoaderType.QUILT):
        if lt.value in gv_lower:
            loaders.append(lt)

    download_url = file_obj.get("downloadUrl")
    allow_dist = bool(download_url)
    website_url = (
        f"https://www.curseforge.com/minecraft/mc-mods/{mod_slug}/files/{file_id}"
        if mod_slug
        else f"https://www.curseforge.com/projects/{mod_id}/files/{file_id}"
    )

    return CandidateVersion(
        platform=ModPlatform.CURSEFORGE,
        project_id=str(mod_id),
        version_id=str(file_id),
        version_number=file_obj.get("displayName") or file_obj.get("fileName") or str(file_id),
        name=file_obj.get("displayName", ""),
        release_type=rel_type,  # type: ignore[arg-type]
        game_versions=game_versions,
        loaders=loaders,
        download_url=download_url,
        filename=file_obj.get("fileName") or f"{mod_id}-{file_id}.jar",
        file_size=int(file_obj.get("fileLength") or 0),
        sha1=sha1,
        md5=md5,
        allow_distribution=allow_dist,
        website_url=website_url,
        date_published=file_obj.get("fileDate", ""),
        dependencies=_parse_cf_dependencies(file_obj.get("dependencies") or []),
    )


class CurseForgeClient:
    def __init__(
        self,
        http: RateLimitedHttpClient,
        api_key: str = "",
        base_url_override: str | None = None,
    ) -> None:
        self.http = http
        self.api_key = api_key
        self.base_url = (base_url_override or CURSEFORGE_API).rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key.strip())

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key.strip(),
            "Accept": "application/json",
        }

    async def match_fingerprints(self, fingerprints: list[int]) -> dict[int, dict[str, Any]]:
        if not self.enabled or not fingerprints:
            return {}
        matched: dict[int, dict[str, Any]] = {}
        chunk_size = 100
        for i in range(0, len(fingerprints), chunk_size):
            batch = fingerprints[i : i + chunk_size]
            res = await self.http.post_json(
                f"{self.base_url}/fingerprints/{MINECRAFT_GAME_ID}",
                headers=self._headers(),
                json={"fingerprints": batch},
            )
            data = res.get("data") or {}
            for item in data.get("exactMatches") or []:
                fp = item.get("file", {}).get("fileFingerprint")
                if fp is not None:
                    matched[int(fp)] = item
        return matched

    async def get_mods_batch(self, mod_ids: list[int]) -> dict[int, dict[str, Any]]:
        if not self.enabled or not mod_ids:
            return {}
        unique = list(dict.fromkeys(mod_ids))
        result: dict[int, dict[str, Any]] = {}
        chunk_size = 100
        for i in range(0, len(unique), chunk_size):
            batch = unique[i : i + chunk_size]
            res = await self.http.post_json(
                f"{self.base_url}/mods",
                headers=self._headers(),
                json={"modIds": batch},
            )
            for item in res.get("data") or []:
                mid = item.get("id")
                if mid is not None:
                    result[int(mid)] = item
        return result

    async def get_files_batch(self, file_ids: list[int]) -> dict[int, dict[str, Any]]:
        if not self.enabled or not file_ids:
            return {}
        unique = list(dict.fromkeys(file_ids))
        result: dict[int, dict[str, Any]] = {}
        chunk_size = 100
        for i in range(0, len(unique), chunk_size):
            batch = unique[i : i + chunk_size]
            res = await self.http.post_json(
                f"{self.base_url}/mods/files",
                headers=self._headers(),
                json={"fileIds": batch},
            )
            for item in res.get("data") or []:
                fid = item.get("id")
                if fid is not None:
                    result[int(fid)] = item
        return result

    async def get_mod_files(
        self,
        mod_id: int,
        target_mc: str,
        target_loader: LoaderType,
        mod_slug: str = "",
    ) -> list[CandidateVersion]:
        """按 gameVersion 查询文件并在本地精准过滤加载器，避免漏掉未标 loader 的文件。"""
        if not self.enabled:
            return []
        res = await self.http.get_json(
            f"{self.base_url}/mods/{mod_id}/files",
            headers=self._headers(),
            params={"gameVersion": target_mc, "pageSize": 50},
        )
        raw_files = res.get("data") or []
        accepted_tags = _LOADER_TAG_MAP.get(target_loader, set())

        candidates: list[CandidateVersion] = []
        for f in raw_files:
            if not f.get("isAvailable", True):
                continue
            gv = list(f.get("gameVersions") or [])
            if target_mc not in gv:
                continue
            gv_lower = {g.lower() for g in gv}
            has_any_loader_tag = bool(gv_lower & {"fabric", "neoforge", "forge", "quilt"})
            if target_loader != LoaderType.UNKNOWN and has_any_loader_tag:
                if not (gv_lower & accepted_tags):
                    continue
            candidates.append(parse_curseforge_file(f, mod_slug=mod_slug))
        return candidates
