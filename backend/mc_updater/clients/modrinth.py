from __future__ import annotations

import json
from typing import Any

from mc_updater.clients.http_client import RateLimitedHttpClient
from mc_updater.core.config import FileCache
from mc_updater.core.models import (
    CandidateVersion,
    DependencyRef,
    GameVersionOption,
    LoaderType,
    ModPlatform,
)
from mc_updater.core.versioning import is_year_based_mc_version

MODRINTH_OFFICIAL_API = "https://api.modrinth.com/v2"
MODRINTH_MCIM_API = "https://mod.mcimirror.top/modrinth/v2"


def _parse_loaders(raw_loaders: list[str]) -> list[LoaderType]:
    result: list[LoaderType] = []
    for item in raw_loaders:
        low = item.lower()
        if low in ("fabric", "neoforge", "forge", "quilt"):
            result.append(LoaderType(low))
    return result


def _parse_dependencies(raw_deps: list[dict[str, Any]]) -> list[DependencyRef]:
    deps: list[DependencyRef] = []
    for d in raw_deps:
        dep_type = d.get("dependency_type", "required")
        if dep_type not in ("required", "optional", "incompatible", "embedded"):
            dep_type = "required"
        deps.append(
            DependencyRef(
                platform=ModPlatform.MODRINTH,
                project_id=d.get("project_id"),
                version_id=d.get("version_id"),
                dependency_type=dep_type,
            )
        )
    return deps


def parse_modrinth_version(raw: dict[str, Any], slug_map: dict[str, str] | None = None) -> CandidateVersion:
    files = raw.get("files") or []
    primary = next((f for f in files if f.get("primary")), files[0] if files else {})
    hashes = primary.get("hashes") or {}
    project_id = raw.get("project_id", "")
    slug = (slug_map or {}).get(project_id, project_id)
    rel_type = raw.get("version_type", "release")
    if rel_type not in ("release", "beta", "alpha"):
        rel_type = "release"

    return CandidateVersion(
        platform=ModPlatform.MODRINTH,
        project_id=project_id,
        version_id=raw.get("id", ""),
        version_number=raw.get("version_number", ""),
        name=raw.get("name", ""),
        release_type=rel_type,
        game_versions=list(raw.get("game_versions") or []),
        loaders=_parse_loaders(raw.get("loaders") or []),
        download_url=primary.get("url"),
        filename=primary.get("filename", f"{project_id}.jar"),
        file_size=int(primary.get("size") or 0),
        sha1=hashes.get("sha1"),
        sha512=hashes.get("sha512"),
        allow_distribution=True,
        website_url=f"https://modrinth.com/mod/{slug}/version/{raw.get('id', '')}",
        date_published=raw.get("date_published", ""),
        dependencies=_parse_dependencies(raw.get("dependencies") or []),
    )


class ModrinthClient:
    def __init__(self, http: RateLimitedHttpClient, base_url_override: str | None = None) -> None:
        self.http = http
        self.base_url_override = base_url_override
        self.cache = FileCache("modrinth")

    def _base_urls(self) -> list[str]:
        if self.base_url_override:
            return [self.base_url_override.rstrip("/")]
        if self.http.settings.use_mcim_mirror:
            return [MODRINTH_MCIM_API, MODRINTH_OFFICIAL_API]
        return [MODRINTH_OFFICIAL_API]

    async def _get(self, path: str, **kwargs: Any) -> Any:
        urls = self._base_urls()
        last_exc: Exception | None = None
        for base in urls:
            try:
                return await self.http.get_json(f"{base}{path}", **kwargs)
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        raise RuntimeError("Modrinth GET failed")

    async def _post(self, path: str, **kwargs: Any) -> Any:
        urls = self._base_urls()
        last_exc: Exception | None = None
        for base in urls:
            try:
                return await self.http.post_json(f"{base}{path}", **kwargs)
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        raise RuntimeError("Modrinth POST failed")

    async def get_game_versions(self, force_refresh: bool = False) -> list[GameVersionOption]:
        if not force_refresh:
            cached = self.cache.get("game_versions", ttl_seconds=3600)
            if cached:
                return [GameVersionOption.model_validate(item) for item in cached]

        raw = await self._get("/tag/game_version")
        options: list[GameVersionOption] = []
        for item in raw:
            ver = str(item.get("version", ""))
            vtype = item.get("version_type", "release")
            if vtype not in ("release", "snapshot", "alpha", "beta"):
                vtype = "snapshot"
            options.append(
                GameVersionOption(
                    version=ver,
                    version_type=vtype,
                    is_year_based=is_year_based_mc_version(ver),
                    date=item.get("date", ""),
                )
            )
        self.cache.set("game_versions", [o.model_dump() for o in options])
        return options

    async def get_versions_by_hashes(
        self, hashes: list[str], algorithm: str = "sha512"
    ) -> dict[str, dict[str, Any]]:
        if not hashes:
            return {}
        merged: dict[str, dict[str, Any]] = {}
        chunk_size = 60
        for i in range(0, len(hashes), chunk_size):
            batch = hashes[i : i + chunk_size]
            res = await self._post(
                "/version_files",
                json={"hashes": batch, "algorithm": algorithm},
            )
            if isinstance(res, dict):
                merged.update(res)
        return merged

    async def find_updates_by_hashes(
        self,
        hashes: list[str],
        loaders: list[str],
        game_versions: list[str],
        algorithm: str = "sha512",
        version_types: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        if not hashes:
            return {}
        merged: dict[str, dict[str, Any]] = {}
        chunk_size = 60
        for i in range(0, len(hashes), chunk_size):
            batch = hashes[i : i + chunk_size]
            payload: dict[str, Any] = {
                "hashes": batch,
                "algorithm": algorithm,
                "loaders": loaders,
                "game_versions": game_versions,
            }
            if version_types:
                payload["version_types"] = version_types
            res = await self._post("/version_files/update", json=payload)
            if isinstance(res, dict):
                merged.update(res)
        return merged

    async def get_project_versions(
        self,
        project_id: str,
        loaders: list[str] | None = None,
        game_versions: list[str] | None = None,
    ) -> list[CandidateVersion]:
        params: dict[str, str] = {"include_changelog": "false"}
        if loaders:
            params["loaders"] = json.dumps(loaders)
        if game_versions:
            params["game_versions"] = json.dumps(game_versions)
        raw = await self._get(f"/project/{project_id}/version", params=params)
        if not isinstance(raw, list):
            return []
        return [parse_modrinth_version(item) for item in raw]

    async def get_projects_batch(self, project_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not project_ids:
            return {}
        unique_ids = list(dict.fromkeys(project_ids))
        result: dict[str, dict[str, Any]] = {}
        chunk_size = 60
        for i in range(0, len(unique_ids), chunk_size):
            batch = unique_ids[i : i + chunk_size]
            res = await self._get("/projects", params={"ids": json.dumps(batch)})
            if isinstance(res, list):
                for item in res:
                    pid = item.get("id")
                    if pid:
                        result[pid] = item
        return result

    async def search_project(
        self,
        query: str,
        loader: str | None = None,
        game_version: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        facets: list[list[str]] = [["project_type:mod"]]
        if loader and loader != "unknown":
            facets.append([f"categories:{loader}"])
        if game_version:
            facets.append([f"versions:{game_version}"])
        params = {
            "query": query,
            "facets": json.dumps(facets),
            "limit": str(limit),
        }
        res = await self._get("/search", params=params)
        return list((res or {}).get("hits") or [])
