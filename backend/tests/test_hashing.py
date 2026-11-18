from __future__ import annotations

from pathlib import Path
from mc_updater.core.hashing import (
    compute_bytes_hashes,
    compute_curseforge_fingerprint,
    compute_file_hashes,
)


def test_curseforge_murmur2_known_vectors() -> None:
    # 标准 CurseForge Murmur2 去除空白符后的已知向量
    assert compute_curseforge_fingerprint(b"test") == 2667173943
    assert compute_curseforge_fingerprint(b"t e\ts\rt\n") == 2667173943
    assert compute_curseforge_fingerprint(b"   \t\r\n  ") == 0


def test_stream_file_hashes_matches_bytes_hashes(tmp_path: Path) -> None:
    sample = b"FabricModData-\t\n\r -" * 50000
    f = tmp_path / "sample.jar"
    f.write_bytes(sample)

    mem = compute_bytes_hashes(sample)
    disk = compute_file_hashes(f)

    assert disk.sha1 == mem.sha1
    assert disk.sha512 == mem.sha512
    assert disk.md5 == mem.md5
    assert disk.murmur2 == mem.murmur2
    assert disk.file_size == len(sample)
