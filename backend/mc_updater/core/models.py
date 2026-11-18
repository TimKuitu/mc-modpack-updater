from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class LoaderType(str, Enum):
    FABRIC = "fabric"
    NEOFORGE = "neoforge"
    FORGE = "forge"
    QUILT = "quilt"
    UNKNOWN = "unknown"


class SourceType(str, Enum):
    PCL2_DIR = "pcl2_dir"
    MRPACK = "mrpack"
    CURSEFORGE_ZIP = "curseforge_zip"
    MCBBS_ZIP = "mcbbs_zip"
    MULTIMC_ZIP = "multimc_zip"
    GENERIC_ZIP = "generic_zip"


class ModPlatform(str, Enum):
    MODRINTH = "modrinth"
    CURSEFORGE = "curseforge"
    LOCAL = "local"


class CompatStatus(str, Enum):
    UPGRADABLE = "upgradable"          # 有兼容正式版
    BETA_ONLY = "beta_only"            # 仅测试版 (beta/alpha)
    MANUAL_REQUIRED = "manual_required"  # CurseForge 禁止第三方下载
    UNAVAILABLE = "unavailable"        # 新版本无此 Mod
    KEEP_ORIGINAL = "keep_original"    # 用户选择强制保留原版
    SKIPPED = "skipped"                # 用户选择跳过


class FileHashes(BaseModel):
    sha1: str
    sha512: str
    md5: str
    murmur2: int
    file_size: int


class DependencyRef(BaseModel):
    platform: ModPlatform
    project_id: str | None = None
    version_id: str | None = None
    mod_id_hint: str | None = None
    dependency_type: Literal["required", "optional", "incompatible", "embedded"] = "required"


class JarMetadata(BaseModel):
    mod_id: str = ""
    name: str = ""
    version: str = ""
    description: str = ""
    authors: list[str] = Field(default_factory=list)
    loaders: list[LoaderType] = Field(default_factory=list)
    depends: dict[str, str | list[str]] = Field(default_factory=dict)
    embedded_jars: list[str] = Field(default_factory=list)
    icon_base64: str | None = None
    source_format: str = ""  # fabric.mod.json / quilt.mod.json / neoforge.mods.toml / mods.toml


class ModEntry(BaseModel):
    uid: str
    filename: str
    local_path: str | None = None  # 若存在于本地目录或解压缓存目录
    disabled: bool = False
    hashes: FileHashes | None = None
    jar_meta: JarMetadata | None = None

    # 识别到的平台身份
    platform: ModPlatform = ModPlatform.LOCAL
    modrinth_project_id: str | None = None
    modrinth_version_id: str | None = None
    curseforge_mod_id: int | None = None
    curseforge_file_id: int | None = None
    slug: str | None = None
    display_name: str = ""
    current_version: str = ""
    icon_url: str | None = None
    identified_by: str = "jar_metadata"  # manifest / modrinth_hash / curseforge_fp / jar_metadata
    is_library: bool = False


class CandidateVersion(BaseModel):
    platform: ModPlatform
    project_id: str
    version_id: str
    version_number: str
    name: str = ""
    release_type: Literal["release", "beta", "alpha"] = "release"
    game_versions: list[str] = Field(default_factory=list)
    loaders: list[LoaderType] = Field(default_factory=list)
    download_url: str | None = None
    filename: str
    file_size: int = 0
    sha1: str | None = None
    sha512: str | None = None
    md5: str | None = None
    allow_distribution: bool = True
    website_url: str | None = None
    date_published: str = ""
    dependencies: list[DependencyRef] = Field(default_factory=list)


class ModUpgradePlan(BaseModel):
    uid: str
    mod: ModEntry
    status: CompatStatus
    selected_candidate: CandidateVersion | None = None
    candidates: list[CandidateVersion] = Field(default_factory=list)
    user_action: Literal["auto", "select_candidate", "keep_original", "skip", "manual_jar"] = "auto"
    manual_jar_path: str | None = None
    manual_verified: bool = False
    is_auto_dependency: bool = False
    required_by: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    note: str = ""


class ConfigItem(BaseModel):
    rel_path: str
    label: str
    category: Literal["config", "scripts", "resource", "client", "save", "other"] = "config"
    file_count: int = 0
    size_bytes: int = 0
    selected: bool = True


class PackAnalysisResult(BaseModel):
    source_path: str
    source_type: SourceType
    pack_name: str
    mc_version: str
    loader: LoaderType
    loader_version: str = ""
    isolation_mode: Literal["isolated", "shared_confirmed", "archive", "unknown"] = "unknown"
    needs_shared_confirmation: bool = False
    shared_mods_path: str | None = None
    mods: list[ModEntry] = Field(default_factory=list)
    config_items: list[ConfigItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    extracted_dir: str | None = None


class UpgradeAnalysisResult(BaseModel):
    target_mc_version: str
    target_loader: LoaderType
    target_loader_version: str = ""
    plans: list[ModUpgradePlan] = Field(default_factory=list)
    summary_counts: dict[str, int] = Field(default_factory=dict)
    dependency_warnings: list[str] = Field(default_factory=list)
    conflict_warnings: list[str] = Field(default_factory=list)


class GameVersionOption(BaseModel):
    version: str
    version_type: Literal["release", "snapshot", "alpha", "beta"] = "release"
    is_year_based: bool = False
    date: str = ""


class AppSettings(BaseModel):
    curseforge_api_key: str = ""
    use_mcim_mirror: bool = True
    proxy_mode: Literal["system", "custom", "direct"] = "system"
    custom_proxy_url: str = ""
    concurrency: int = 6
    include_beta_by_default: bool = False
    skip_modrinth_download_for_mrpack: bool = False


class ModDownloadStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    SKIPPED_FAST = "skipped_fast"
    KEEP_ORIGINAL = "keep_original"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ModDownloadItemState(BaseModel):
    uid: str
    status: ModDownloadStatus = ModDownloadStatus.PENDING
    file_path: str | None = None
    error: str = ""
    downloaded_bytes: int = 0
    total_bytes: int = 0


class DownloadReport(BaseModel):
    downloaded_files: dict[str, str] = Field(default_factory=dict)  # uid -> local file path
    verified_hashes: dict[str, FileHashes] = Field(default_factory=dict)
    failed_items: list[dict[str, str]] = Field(default_factory=list)
    skipped_modrinth_count: int = 0
    cancelled: bool = False
    item_states: dict[str, ModDownloadItemState] = Field(default_factory=dict)


class ExportResult(BaseModel):
    output_path: str
    file_size: int
    included_mods_in_index: int = 0
    included_mods_in_overrides: int = 0
    included_config_files: int = 0
    has_non_redistributable_cf: bool = False
    warnings: list[str] = Field(default_factory=list)


class ProgressEvent(BaseModel):
    task_id: str
    stage: str
    current: int = 0
    total: int = 0
    message: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
