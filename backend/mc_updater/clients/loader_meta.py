from __future__ import annotations

from mc_updater.clients.http_client import RateLimitedHttpClient
from mc_updater.core.config import FileCache
from mc_updater.core.models import LoaderType


class LoaderMetaClient:
    """获取各加载器（Fabric / Quilt / NeoForge / Forge）适配目标 MC 版本的推荐版本号。"""

    def __init__(self, http: RateLimitedHttpClient) -> None:
        self.http = http
        self.cache = FileCache("loader_meta")

    async def get_recommended_loader_version(self, mc_version: str, loader: LoaderType) -> str:
        if loader == LoaderType.UNKNOWN:
            return ""
        cache_key = f"{loader.value}_{mc_version}"
        cached = self.cache.get(cache_key, ttl_seconds=3600)
        if cached:
            return str(cached)

        version = ""
        try:
            if loader == LoaderType.FABRIC:
                url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}"
                data = await self.http.get_json(url)
                if isinstance(data, list) and data:
                    stable = next((d for d in data if d.get("loader", {}).get("stable")), data[0])
                    version = stable.get("loader", {}).get("version", "")
            elif loader == LoaderType.QUILT:
                url = f"https://meta.quiltmc.org/v3/versions/loader/{mc_version}"
                data = await self.http.get_json(url)
                if isinstance(data, list) and data:
                    version = data[0].get("loader", {}).get("version", "")
            elif loader == LoaderType.NEOFORGE:
                url = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
                data = await self.http.get_json(url)
                versions = list(data.get("versions") or [])
                # NeoForge 年份制直接以 <mc>.x 开头；1.21.1 -> 21.1.x
                if mc_version.startswith("26.") or not mc_version.startswith("1."):
                    prefix = f"{mc_version}."
                else:
                    parts = mc_version.split(".")
                    prefix = f"{parts[1]}.{parts[2] if len(parts) > 2 else '0'}."
                matched = [v for v in versions if v.startswith(prefix)]
                if matched:
                    version = matched[-1]
            elif loader == LoaderType.FORGE:
                url = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
                data = await self.http.get_json(url)
                promos = data.get("promos") or {}
                version = promos.get(f"{mc_version}-recommended") or promos.get(f"{mc_version}-latest") or ""
        except Exception:
            version = ""

        if version:
            self.cache.set(cache_key, version)
        return version
