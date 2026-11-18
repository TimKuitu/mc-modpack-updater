from __future__ import annotations

from pathlib import Path
from typing import Iterator

from mc_updater.core.models import ConfigItem

_SKIP_FILENAMES = {"session.lock", "desktop.ini", ".ds_store"}


def iter_selected_config_files(
    game_dir: Path | None,
    config_items: list[ConfigItem],
) -> Iterator[tuple[Path, str]]:
    """遍历用户勾选的配置文件，返回 (本地绝对路径, 压缩包内相对路径)。"""
    if not game_dir or not game_dir.is_dir():
        return

    for item in config_items:
        if not item.selected:
            continue
        target = game_dir / item.rel_path
        if not target.exists():
            continue
        if target.is_file():
            if target.name.lower() not in _SKIP_FILENAMES:
                yield target, item.rel_path.replace("\\", "/")
        elif target.is_dir():
            for f in sorted(target.rglob("*")):
                if not f.is_file():
                    continue
                if f.name.lower() in _SKIP_FILENAMES:
                    continue
                rel = f.relative_to(game_dir).as_posix()
                yield f, rel
