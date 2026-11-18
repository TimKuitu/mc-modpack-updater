from __future__ import annotations

import configparser
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from mc_updater.core.models import ConfigItem, LoaderType, SourceType
from mc_updater.parsers.instance_meta import parse_pcl2_instance_dir

# 默认扫描的配置文件/目录规则
_CONFIG_CANDIDATES: list[tuple[str, str, str, bool]] = [
    ("config", "Mod 配置 (config/)", "config", True),
    ("defaultconfigs", "默认配置 (defaultconfigs/)", "config", True),
    ("kubejs", "KubeJS 脚本 (kubejs/)", "scripts", True),
    ("scripts", "CraftTweaker 脚本 (scripts/)", "scripts", True),
    ("options.txt", "游戏基础设置 (options.txt)", "client", True),
    ("servers.dat", "服务器列表 (servers.dat)", "client", True),
    ("resourcepacks", "资源包 (resourcepacks/)", "resource", True),
    ("shaderpacks", "光影包 (shaderpacks/)", "resource", True),
    ("journeymap", "旅行地图数据 (journeymap/)", "client", False),
    ("xaero", "Xaero 地图数据 (xaero/)", "client", False),
    ("saves", "单人存档 (saves/)", "save", False),
]

_EXCLUDED_TOP = {"logs", "crash-reports", "natives", "mods", "libraries", "versions", "assets", ".fabric", ".mixin.out"}


@dataclass
class DetectedInput:
    source_path: str
    source_type: SourceType
    pack_name: str
    mc_version: str = ""
    loader: LoaderType = LoaderType.UNKNOWN
    loader_version: str = ""
    isolation_mode: str = "archive"
    needs_shared_confirmation: bool = False
    shared_mods_path: str | None = None
    game_dir: Path | None = None
    mods_dir: Path | None = None
    overrides_dir: Path | None = None
    manifest_data: dict | None = None
    extracted_dir: Path | None = None
    config_items: list[ConfigItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """带路径穿越校验的安全解压。"""
    dest_resolved = dest_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            name = member.filename
            if name.startswith("/") or name.startswith("\\") or ".." in Path(name).parts:
                raise ValueError(f"检测到不安全的压缩包路径: {name}")
            target = (dest_resolved / name).resolve()
            if not str(target).startswith(str(dest_resolved)):
                raise ValueError(f"压缩包路径越界: {name}")
        zf.extractall(dest_resolved)


def scan_config_items(base_dir: Path) -> list[ConfigItem]:
    if not base_dir or not base_dir.is_dir():
        return []
    items: list[ConfigItem] = []
    seen: set[str] = set()

    for rel, label, cat, default_selected in _CONFIG_CANDIDATES:
        target = base_dir / rel
        if not target.exists():
            continue
        seen.add(rel)
        if target.is_file():
            items.append(
                ConfigItem(
                    rel_path=rel,
                    label=label,
                    category=cat,  # type: ignore[arg-type]
                    file_count=1,
                    size_bytes=target.stat().st_size,
                    selected=default_selected,
                )
            )
        elif target.is_dir():
            files = [f for f in target.rglob("*") if f.is_file() and f.name != "session.lock"]
            if not files:
                continue
            total_size = sum(f.stat().st_size for f in files)
            items.append(
                ConfigItem(
                    rel_path=rel,
                    label=label,
                    category=cat,  # type: ignore[arg-type]
                    file_count=len(files),
                    size_bytes=total_size,
                    selected=default_selected,
                )
            )
    return items


def _parse_multimc_cfg(cfg_path: Path) -> str:
    if not cfg_path.is_file():
        return ""
    try:
        text = "[MMC]\n" + cfg_path.read_text(encoding="utf-8", errors="ignore")
        cp = configparser.ConfigParser()
        cp.read_string(text)
        return cp.get("MMC", "name", fallback="").strip()
    except Exception:
        return ""


def detect_and_prepare_input(
    raw_path: str,
    allow_shared_fallback: bool = False,
) -> DetectedInput:
    p = Path(raw_path.strip().strip('"'))
    if not p.exists():
        raise FileNotFoundError(f"路径不存在：{raw_path}")

    # 1. 目录输入（PCL2 实例目录或直接包含 mods/ 的目录）
    if p.is_dir():
        inst = parse_pcl2_instance_dir(p, allow_shared_fallback=allow_shared_fallback)
        cfg_items = scan_config_items(inst.game_dir) if inst.game_dir else []
        return DetectedInput(
            source_path=str(p),
            source_type=SourceType.PCL2_DIR,
            pack_name=inst.instance_name,
            mc_version=inst.mc_version,
            loader=inst.loader,
            loader_version=inst.loader_version,
            isolation_mode=inst.isolation_mode,
            needs_shared_confirmation=inst.needs_shared_confirmation,
            shared_mods_path=inst.shared_mods_path,
            game_dir=inst.game_dir,
            mods_dir=inst.mods_dir,
            config_items=cfg_items,
            warnings=inst.warnings,
        )

    # 2. 压缩包输入 (.mrpack / .zip)
    if p.suffix.lower() not in (".mrpack", ".zip"):
        raise ValueError(f"不支持的文件格式：{p.suffix}（仅支持文件夹、.mrpack 或 .zip）")

    tmp_dir = Path(tempfile.mkdtemp(prefix="mc_updater_pack_"))
    try:
        safe_extract_zip(p, tmp_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # 若压缩包外层包了一层同名目录，自动下钻一层
    entries = list(tmp_dir.iterdir())
    root = entries[0] if (len(entries) == 1 and entries[0].is_dir()) else tmp_dir

    # A. Modrinth .mrpack
    mr_index = root / "modrinth.index.json"
    if mr_index.is_file():
        data = json.loads(mr_index.read_text(encoding="utf-8", errors="ignore"))
        deps = data.get("dependencies") or {}
        mc_ver = str(deps.get("minecraft", ""))
        loader, loader_ver = _detect_loader_from_mrpack_deps(deps)
        overrides = root / "overrides"
        client_overrides = root / "client-overrides"
        cfg_items = scan_config_items(overrides)
        if client_overrides.is_dir():
            # 补充合并提示
            for item in scan_config_items(client_overrides):
                if all(c.rel_path != item.rel_path for c in cfg_items):
                    cfg_items.append(item)
        return DetectedInput(
            source_path=str(p),
            source_type=SourceType.MRPACK,
            pack_name=str(data.get("name") or p.stem),
            mc_version=mc_ver,
            loader=loader,
            loader_version=loader_ver,
            isolation_mode="archive",
            game_dir=overrides if overrides.is_dir() else root,
            mods_dir=(overrides / "mods") if (overrides / "mods").is_dir() else None,
            overrides_dir=overrides if overrides.is_dir() else None,
            manifest_data=data,
            extracted_dir=tmp_dir,
            config_items=cfg_items,
        )

    # B. CurseForge manifest.json
    cf_manifest = root / "manifest.json"
    if cf_manifest.is_file():
        data = json.loads(cf_manifest.read_text(encoding="utf-8", errors="ignore"))
        if data.get("manifestType") == "minecraftModpack" or "minecraft" in data:
            mc_obj = data.get("minecraft") or {}
            mc_ver = str(mc_obj.get("version", ""))
            loader, loader_ver = _detect_loader_from_cf_manifest(mc_obj.get("modLoaders") or [])
            ov_name = data.get("overrides") or "overrides"
            overrides = root / ov_name
            return DetectedInput(
                source_path=str(p),
                source_type=SourceType.CURSEFORGE_ZIP,
                pack_name=str(data.get("name") or p.stem),
                mc_version=mc_ver,
                loader=loader,
                loader_version=loader_ver,
                isolation_mode="archive",
                game_dir=overrides if overrides.is_dir() else root,
                mods_dir=(overrides / "mods") if (overrides / "mods").is_dir() else None,
                overrides_dir=overrides if overrides.is_dir() else None,
                manifest_data=data,
                extracted_dir=tmp_dir,
                config_items=scan_config_items(overrides),
            )

    # C. MCBBS packmeta
    mcbbs_meta = root / "mcbbs.packmeta"
    if mcbbs_meta.is_file():
        data = json.loads(mcbbs_meta.read_text(encoding="utf-8", errors="ignore"))
        addons = data.get("addons") or []
        mc_ver = ""
        loader = LoaderType.UNKNOWN
        loader_ver = ""
        for ad in addons:
            aid = str(ad.get("id", "")).lower()
            aver = str(ad.get("version", ""))
            if aid == "game":
                mc_ver = aver
            elif aid in ("fabric", "neoforge", "forge", "quilt"):
                loader = LoaderType(aid)
                loader_ver = aver
        overrides = root / "overrides"
        return DetectedInput(
            source_path=str(p),
            source_type=SourceType.MCBBS_ZIP,
            pack_name=str(data.get("name") or p.stem),
            mc_version=mc_ver,
            loader=loader,
            loader_version=loader_ver,
            isolation_mode="archive",
            game_dir=overrides if overrides.is_dir() else root,
            mods_dir=(overrides / "mods") if (overrides / "mods").is_dir() else None,
            overrides_dir=overrides if overrides.is_dir() else None,
            manifest_data=data,
            extracted_dir=tmp_dir,
            config_items=scan_config_items(overrides),
        )

    # D. MultiMC / Prism mmc-pack.json
    mmc_pack = root / "mmc-pack.json"
    if mmc_pack.is_file():
        data = json.loads(mmc_pack.read_text(encoding="utf-8", errors="ignore"))
        mc_ver = ""
        loader = LoaderType.UNKNOWN
        loader_ver = ""
        for comp in data.get("components") or []:
            uid = comp.get("uid", "")
            ver = str(comp.get("version", ""))
            if uid == "net.minecraft":
                mc_ver = ver
            elif uid == "net.fabricmc.fabric-loader":
                loader, loader_ver = LoaderType.FABRIC, ver
            elif uid == "org.quiltmc.quilt-loader":
                loader, loader_ver = LoaderType.QUILT, ver
            elif uid == "net.neoforged":
                loader, loader_ver = LoaderType.NEOFORGE, ver
            elif uid == "net.minecraftforge":
                loader, loader_ver = LoaderType.FORGE, ver
        mc_root = root / ".minecraft" if (root / ".minecraft").is_dir() else (root / "minecraft" if (root / "minecraft").is_dir() else root)
        name = _parse_multimc_cfg(root / "instance.cfg") or p.stem
        return DetectedInput(
            source_path=str(p),
            source_type=SourceType.MULTIMC_ZIP,
            pack_name=name,
            mc_version=mc_ver,
            loader=loader,
            loader_version=loader_ver,
            isolation_mode="archive",
            game_dir=mc_root,
            mods_dir=(mc_root / "mods") if (mc_root / "mods").is_dir() else None,
            extracted_dir=tmp_dir,
            config_items=scan_config_items(mc_root),
        )

    # E. PCL2 懒人包 / 散装包
    dot_mc = root / ".minecraft" if (root / ".minecraft").is_dir() else root
    mods_dir = dot_mc / "mods" if (dot_mc / "mods").is_dir() else None
    mc_ver = ""
    loader = LoaderType.UNKNOWN
    loader_ver = ""
    versions_dir = dot_mc / "versions"
    if versions_dir.is_dir():
        subdirs = [d for d in versions_dir.iterdir() if d.is_dir()]
        if subdirs:
            inst = parse_pcl2_instance_dir(subdirs[0], allow_shared_fallback=True)
            mc_ver = inst.mc_version
            loader = inst.loader
            loader_ver = inst.loader_version
            if inst.mods_dir:
                mods_dir = inst.mods_dir
                dot_mc = inst.game_dir or dot_mc

    return DetectedInput(
        source_path=str(p),
        source_type=SourceType.GENERIC_ZIP,
        pack_name=p.stem,
        mc_version=mc_ver,
        loader=loader,
        loader_version=loader_ver,
        isolation_mode="archive",
        game_dir=dot_mc,
        mods_dir=mods_dir,
        extracted_dir=tmp_dir,
        config_items=scan_config_items(dot_mc),
    )


def _detect_loader_from_mrpack_deps(deps: dict) -> tuple[LoaderType, str]:
    for key, lt in (
        ("fabric-loader", LoaderType.FABRIC),
        ("quilt-loader", LoaderType.QUILT),
        ("neoforge", LoaderType.NEOFORGE),
        ("forge", LoaderType.FORGE),
    ):
        if key in deps:
            return lt, str(deps[key])
    return LoaderType.UNKNOWN, ""


def _detect_loader_from_cf_manifest(mod_loaders: list[dict]) -> tuple[LoaderType, str]:
    primary = next((m for m in mod_loaders if m.get("primary")), mod_loaders[0] if mod_loaders else None)
    if not primary:
        return LoaderType.UNKNOWN, ""
    lid = str(primary.get("id", ""))
    for prefix, lt in (
        ("fabric-", LoaderType.FABRIC),
        ("quilt-", LoaderType.QUILT),
        ("neoforge-", LoaderType.NEOFORGE),
        ("forge-", LoaderType.FORGE),
    ):
        if lid.lower().startswith(prefix):
            return lt, lid[len(prefix) :]
    return LoaderType.UNKNOWN, ""
