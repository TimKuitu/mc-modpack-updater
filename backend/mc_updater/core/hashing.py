from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from .models import FileHashes

_WHITESPACE_TABLE = bytes.maketrans(b"", b"")
_DELETE_WHITESPACE = b"\t\n\r "


def compute_curseforge_fingerprint(data: bytes) -> int:
    """计算 CurseForge MurmurHash2 指纹（去除 0x09, 0x0A, 0x0D, 0x20，seed=1）。"""
    normalized = data.translate(_WHITESPACE_TABLE, _DELETE_WHITESPACE)
    length = len(normalized)
    if length == 0:
        return 0

    m = 0x5BD1E995
    h = (1 ^ length) & 0xFFFFFFFF

    blocks = length // 4
    for (k,) in struct.iter_unpack("<I", normalized[: blocks * 4]):
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> 24
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k

    tail = normalized[blocks * 4 :]
    rem = len(tail)
    if rem == 3:
        h ^= tail[2] << 16
    if rem >= 2:
        h ^= tail[1] << 8
    if rem >= 1:
        h ^= tail[0]
        h = (h * m) & 0xFFFFFFFF

    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h


def compute_bytes_hashes(data: bytes) -> FileHashes:
    """对内存字节一次性计算 sha1、sha512、md5 与 CurseForge murmur2。"""
    return FileHashes(
        sha1=hashlib.sha1(data).hexdigest(),
        sha512=hashlib.sha512(data).hexdigest(),
        md5=hashlib.md5(data).hexdigest(),
        murmur2=compute_curseforge_fingerprint(data),
        file_size=len(data),
    )


def compute_file_hashes(path: str | Path) -> FileHashes:
    """对磁盘文件一次性流式读取并计算全部哈希与 CurseForge murmur2。"""
    p = Path(path)
    sha1 = hashlib.sha1()
    sha512 = hashlib.sha512()
    md5 = hashlib.md5()
    buf = bytearray()
    size = 0

    with p.open("rb") as f:
        while chunk := f.read(1024 * 256):
            size += len(chunk)
            sha1.update(chunk)
            sha512.update(chunk)
            md5.update(chunk)
            buf.extend(chunk)

    return FileHashes(
        sha1=sha1.hexdigest(),
        sha512=sha512.hexdigest(),
        md5=md5.hexdigest(),
        murmur2=compute_curseforge_fingerprint(bytes(buf)),
        file_size=size,
    )
