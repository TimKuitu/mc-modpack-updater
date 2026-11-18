from __future__ import annotations

import zipfile
from pathlib import Path

from mc_updater.core.models import ConfigItem
from mc_updater.exporter.overrides_collector import iter_selected_config_files


def export_config_backup_zip(
    game_dir: Path | None,
    config_items: list[ConfigItem],
    output_zip_path: str | Path,
) -> tuple[str, int, int]:
    """将原整合包选中的配置文件打包为独立备份 .zip，返回 (路径, 字节数, 文件数)。"""
    out = Path(output_zip_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src_file, rel_posix in iter_selected_config_files(game_dir, config_items):
            zf.write(src_file, arcname=rel_posix)
            count += 1

    return str(out), out.stat().st_size, count
