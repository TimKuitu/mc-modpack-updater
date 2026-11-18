from __future__ import annotations

import configparser
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mc_updater.core.models import LoaderType


@dataclass
class InstanceMetaResult:
    instance_name: str
    mc_version: str = ""
    loader: LoaderType = LoaderType.UNKNOWN
    loader_version: str = ""
    isolation_mode: str = "isolated"  # isolated / shared_confirmed / unknown
    needs_shared_confirmation: bool = False
    mods_dir: Path | None = None
    game_dir: Path | None = None
    shared_mods_path: str | None = None
    warnings: list[str] = field(default_factory=list)


def _find_version_json(instance_dir: Path) -> Path | None:
    exact = instance_dir / f"{instance_dir.name}.json"
    if exact.is_file():
        return exact
    for candidate in sorted(instance_dir.glob("*.json")):
        if candidate.name.lower() in ("pcl.json", "pack.json", "manifest.json"):
            continue
        return candidate
    return None


def _load_inherits_chain(start_json: Path, max_depth: int = 8) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    visited: set[Path] = set()
    cur: Path | None = start_json

    for _ in range(max_depth):
        if cur is None or not cur.is_file() or cur in visited:
            break
        visited.add(cur)
        try:
            data = json.loads(cur.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            break
        chain.append(data)
        parent_id = data.get("inheritsFrom")
        if not parent_id:
            break
        # 常见路径：同目录、或 ..\..\versions\<parent>\<parent>.json
        parent_same = cur.parent / f"{parent_id}.json"
        parent_sibling = cur.parent.parent / str(parent_id) / f"{parent_id}.json"
        if parent_same.is_file():
            cur = parent_same
        elif parent_sibling.is_file():
            cur = parent_sibling
        else:
            cur = None
    return chain


def _extract_mc_and_loader_from_chain(chain: list[dict[str, Any]]) -> tuple[str, LoaderType, str]:
    mc_version = ""
    loader = LoaderType.UNKNOWN
    loader_version = ""

    # 合并所有 libraries 与 arguments.game，子节点优先
    all_libs: list[str] = []
    all_game_args: list[str] = []
    all_patches: list[dict[str, Any]] = []
    main_classes: list[str] = []

    for node in chain:
        if node.get("mainClass"):
            main_classes.append(str(node["mainClass"]))
        for lib in node.get("libraries") or []:
            if isinstance(lib, dict) and lib.get("name"):
                all_libs.append(str(lib["name"]))
        args = (node.get("arguments") or {}).get("game") or []
        for a in args:
            if isinstance(a, str):
                all_game_args.append(a)
        for p in node.get("patches") or []:
            if isinstance(p, dict):
                all_patches.append(p)

    # 1. 检测加载器
    for lib_name in all_libs:
        if lib_name.startswith("net.fabricmc:fabric-loader:"):
            loader = LoaderType.FABRIC
            loader_version = lib_name.split(":", 2)[2].split("@")[0]
            break
        if lib_name.startswith("org.quiltmc:quilt-loader:"):
            loader = LoaderType.QUILT
            loader_version = lib_name.split(":", 2)[2].split("@")[0]
            break
        if lib_name.startswith("net.neoforged:neoforge:"):
            loader = LoaderType.NEOFORGE
            loader_version = lib_name.split(":", 2)[2].split("@")[0]
            break
        if lib_name.startswith("net.neoforged:forge:"):
            loader = LoaderType.NEOFORGE
            ver_part = lib_name.split(":", 2)[2].split("@")[0]
            loader_version = ver_part.split("-", 1)[1] if "-" in ver_part else ver_part
            break
        if lib_name.startswith("net.minecraftforge:forge:"):
            loader = LoaderType.FORGE
            ver_part = lib_name.split(":", 2)[2].split("@")[0]
            loader_version = ver_part.split("-", 1)[1] if "-" in ver_part else ver_part
            break

    # 2. 若 libraries 未命中，结合参数或 mainClass
    for i, arg in enumerate(all_game_args[:-1]):
        if arg == "--fml.neoForgeVersion":
            loader = LoaderType.NEOFORGE
            loader_version = loader_version or all_game_args[i + 1]
        elif arg == "--fml.forgeVersion" and loader == LoaderType.UNKNOWN:
            loader = LoaderType.FORGE
            loader_version = loader_version or all_game_args[i + 1]
        elif arg == "--fml.mcVersion" and not mc_version:
            mc_version = all_game_args[i + 1]

    if loader == LoaderType.UNKNOWN:
        for mc in main_classes:
            if "fabric" in mc.lower() or "KnotClient" in mc:
                loader = LoaderType.FABRIC
                break
            if "quilt" in mc.lower():
                loader = LoaderType.QUILT
                break

    # 3. 提取 MC 版本：patches -> arguments --fml.mcVersion -> 终端父节点 id / clientVersion
    if not mc_version:
        for p in all_patches:
            if p.get("id") == "game" and p.get("version"):
                mc_version = str(p["version"])
                break

    if not mc_version and chain:
        root = chain[-1]
        mc_version = str(
            root.get("clientVersion")
            or root.get("jar")
            or root.get("inheritsFrom")
            or root.get("id")
            or ""
        )
        # 若最末节点本身仍是 loader-mc 组合名（如 26.1-fabric-0.16.0），尝试拆分前缀
        for sep in ("-fabric", "-neoforge", "-forge", "-quilt"):
            if sep in mc_version.lower():
                idx = mc_version.lower().find(sep)
                mc_version = mc_version[:idx]
                break

    return mc_version, loader, loader_version


def _read_pcl_indie_flag(instance_dir: Path) -> bool | None:
    setup_ini = instance_dir / "PCL" / "Setup.ini"
    if not setup_ini.is_file():
        return None
    try:
        text = setup_ini.read_text(encoding="utf-8", errors="ignore")
        # PCL Setup.ini 可能无 section 头，统一加上 [PCL] 解析
        if not text.lstrip().startswith("["):
            text = "[PCL]\n" + text
        cp = configparser.ConfigParser()
        cp.read_string(text)
        for sec in cp.sections():
            if cp.has_option(sec, "VersionArgumentIndie"):
                val = cp.get(sec, "VersionArgumentIndie").strip()
                return val not in ("0", "False", "false", "")
    except Exception:
        pass
    return None


def parse_pcl2_instance_dir(
    instance_dir: Path,
    allow_shared_fallback: bool = False,
) -> InstanceMetaResult:
    """解析 PCL2 版本目录，支持三级版本隔离判定与 inheritsFrom 继承链。"""
    res = InstanceMetaResult(instance_name=instance_dir.name)
    vjson = _find_version_json(instance_dir)
    if vjson:
        chain = _load_inherits_chain(vjson)
        mc_ver, loader, loader_ver = _extract_mc_and_loader_from_chain(chain)
        res.mc_version = mc_ver
        res.loader = loader
        res.loader_version = loader_ver
    else:
        res.warnings.append("未在目录中找到版本 JSON 文件，无法自动识别游戏版本与加载器。")

    # 三级版本隔离判定
    local_mods = instance_dir / "mods"
    local_config = instance_dir / "config"
    pcl_indie = _read_pcl_indie_flag(instance_dir)

    if local_mods.is_dir() or local_config.is_dir():
        res.isolation_mode = "isolated"
        res.game_dir = instance_dir
        res.mods_dir = local_mods if local_mods.is_dir() else None
        return res

    # 检查上级 .minecraft\mods
    dot_mc = instance_dir.parent.parent
    shared_mods = dot_mc / "mods"
    if pcl_indie is False or (shared_mods.is_dir() and not local_mods.is_dir()):
        res.shared_mods_path = str(shared_mods) if shared_mods.is_dir() else str(dot_mc)
        if allow_shared_fallback:
            res.isolation_mode = "shared_confirmed"
            res.game_dir = dot_mc
            res.mods_dir = shared_mods if shared_mods.is_dir() else None
            res.warnings.append("当前读取的是 .minecraft 共享目录（未开启版本隔离），可能混杂其他版本 Mod。")
        else:
            res.isolation_mode = "unknown"
            res.needs_shared_confirmation = True
            res.warnings.append("未检测到当前实例独立的 mods 目录，需确认是否读取 .minecraft 共享目录。")
        return res

    # 没有任何 mods 目录，但作为隔离空实例处理
    res.isolation_mode = "isolated"
    res.game_dir = instance_dir
    res.mods_dir = None
    return res
