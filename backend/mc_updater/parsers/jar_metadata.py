from __future__ import annotations

import base64
import json
import tomllib
import zipfile
from pathlib import Path
from typing import Any

from mc_updater.core.models import JarMetadata, LoaderType


def _extract_icon_b64(zf: zipfile.ZipFile, icon_path: str | None) -> str | None:
    if not icon_path:
        return None
    norm = icon_path.lstrip("/")
    try:
        info = zf.getinfo(norm)
        if info.file_size > 512 * 1024:  # 跳过异常大图标
            return None
        raw = zf.read(norm)
        ext = Path(norm).suffix.lower().lstrip(".") or "png"
        if ext not in ("png", "jpg", "jpeg", "webp"):
            ext = "png"
        return f"data:image/{ext};base64,{base64.b64encode(raw).decode('ascii')}"
    except Exception:
        return None


def _normalize_authors(raw_authors: Any) -> list[str]:
    if not raw_authors:
        return []
    out: list[str] = []
    if isinstance(raw_authors, list):
        for a in raw_authors:
            if isinstance(a, str):
                out.append(a)
            elif isinstance(a, dict) and a.get("name"):
                out.append(str(a["name"]))
    elif isinstance(raw_authors, str):
        out.append(raw_authors)
    return out


def parse_jar_metadata(jar_path: str | Path) -> JarMetadata:
    """解析 .jar 文件内部元数据（fabric.mod.json / quilt.mod.json / neoforge.mods.toml / mods.toml / mcmod.info）。"""
    path = Path(jar_path)
    meta = JarMetadata()
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())

            # 1. Fabric
            if "fabric.mod.json" in names:
                data = json.loads(zf.read("fabric.mod.json").decode("utf-8", errors="ignore"))
                icon_field = data.get("icon")
                icon_path = None
                if isinstance(icon_field, str):
                    icon_path = icon_field
                elif isinstance(icon_field, dict) and icon_field:
                    # 取最大分辨率或任意一个
                    icon_path = list(icon_field.values())[-1]

                depends_raw = data.get("depends") or {}
                depends: dict[str, str | list[str]] = {}
                if isinstance(depends_raw, dict):
                    for k, v in depends_raw.items():
                        if isinstance(v, (str, list)):
                            depends[str(k)] = v

                embedded = [
                    str(j.get("file", ""))
                    for j in (data.get("jars") or [])
                    if isinstance(j, dict) and j.get("file")
                ]

                return JarMetadata(
                    mod_id=str(data.get("id", "")),
                    name=str(data.get("name") or data.get("id") or ""),
                    version=str(data.get("version", "")),
                    description=str(data.get("description", "")),
                    authors=_normalize_authors(data.get("authors")),
                    loaders=[LoaderType.FABRIC],
                    depends=depends,
                    embedded_jars=embedded,
                    icon_base64=_extract_icon_b64(zf, icon_path),
                    source_format="fabric.mod.json",
                )

            # 2. Quilt
            if "quilt.mod.json" in names:
                data = json.loads(zf.read("quilt.mod.json").decode("utf-8", errors="ignore"))
                ql = data.get("quilt_loader") or {}
                qmeta = ql.get("metadata") or {}
                depends = {}
                for dep in ql.get("depends") or []:
                    if isinstance(dep, dict) and dep.get("id"):
                        depends[str(dep["id"])] = str(dep.get("versions", "*"))
                embedded = [str(j) for j in (ql.get("jars") or []) if isinstance(j, str)]
                return JarMetadata(
                    mod_id=str(ql.get("id", "")),
                    name=str(qmeta.get("name") or ql.get("id") or ""),
                    version=str(ql.get("version", "")),
                    description=str(qmeta.get("description", "")),
                    authors=list((qmeta.get("contributors") or {}).keys())
                    if isinstance(qmeta.get("contributors"), dict)
                    else [],
                    loaders=[LoaderType.QUILT],
                    depends=depends,
                    embedded_jars=embedded,
                    icon_base64=_extract_icon_b64(zf, qmeta.get("icon")),
                    source_format="quilt.mod.json",
                )

            # 3. NeoForge / Forge TOML
            toml_name = None
            default_loader = LoaderType.FORGE
            if "META-INF/neoforge.mods.toml" in names:
                toml_name = "META-INF/neoforge.mods.toml"
                default_loader = LoaderType.NEOFORGE
            elif "META-INF/mods.toml" in names:
                toml_name = "META-INF/mods.toml"
                default_loader = LoaderType.FORGE

            if toml_name:
                parsed = tomllib.loads(zf.read(toml_name).decode("utf-8", errors="ignore"))
                mods_list = parsed.get("mods") or []
                first_mod = mods_list[0] if mods_list else {}
                mod_id = str(first_mod.get("modId", ""))
                depends = {}
                deps_map = parsed.get("dependencies") or {}
                mod_deps = deps_map.get(mod_id) or []
                if isinstance(mod_deps, list):
                    for d in mod_deps:
                        if isinstance(d, dict) and d.get("modId"):
                            depends[str(d["modId"])] = str(d.get("versionRange", "*"))

                embedded: list[str] = []
                if "META-INF/jarjar/metadata.json" in names:
                    try:
                        jj = json.loads(
                            zf.read("META-INF/jarjar/metadata.json").decode("utf-8", errors="ignore")
                        )
                        for j in jj.get("jars") or []:
                            if isinstance(j, dict) and j.get("path"):
                                embedded.append(str(j["path"]))
                    except Exception:
                        pass

                return JarMetadata(
                    mod_id=mod_id,
                    name=str(first_mod.get("displayName") or mod_id),
                    version=str(first_mod.get("version", "")),
                    description=str(first_mod.get("description", "")),
                    authors=_normalize_authors(first_mod.get("authors")),
                    loaders=[default_loader],
                    depends=depends,
                    embedded_jars=embedded,
                    icon_base64=_extract_icon_b64(zf, first_mod.get("logoFile")),
                    source_format=toml_name,
                )

            # 4. Legacy mcmod.info
            if "mcmod.info" in names:
                raw = json.loads(zf.read("mcmod.info").decode("utf-8", errors="ignore"))
                items = raw if isinstance(raw, list) else raw.get("modList") or []
                if items and isinstance(items[0], dict):
                    first = items[0]
                    return JarMetadata(
                        mod_id=str(first.get("modid", "")),
                        name=str(first.get("name") or first.get("modid") or ""),
                        version=str(first.get("version", "")),
                        description=str(first.get("description", "")),
                        authors=_normalize_authors(first.get("authorList")),
                        loaders=[LoaderType.FORGE],
                        icon_base64=_extract_icon_b64(zf, first.get("logoFile")),
                        source_format="mcmod.info",
                    )
    except Exception:
        pass
    return meta
