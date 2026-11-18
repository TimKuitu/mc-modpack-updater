from __future__ import annotations

import re
from dataclasses import dataclass


_YEAR_VER_RE = re.compile(r"^(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?(?:-(?P<pre>.+))?$")
_WEEKLY_SNAP_RE = re.compile(r"^(?P<year>\d{2})w(?P<week>\d{2})(?P<letter>[a-z]+)$", re.IGNORECASE)


def is_year_based_mc_version(version: str) -> bool:
    """判断是否为 Mojang 2026+ 年份制版本号（例如 26.1、26.1.1、26.1-snapshot-1）。"""
    m = _YEAR_VER_RE.match(version.strip())
    if not m:
        return False
    major = int(m.group("major"))
    return major >= 26


@dataclass(frozen=True)
class ParsedVersion:
    """通用 MC / SemVer 风格版本解析，支持年份制 26.1+、传统 1.21.x 及快照后缀。"""

    raw: str
    major: int
    minor: int
    patch: int
    pre: str
    is_snapshot: bool = False

    @classmethod
    def parse(cls, raw: str) -> "ParsedVersion":
        text = raw.strip()
        snap_m = _WEEKLY_SNAP_RE.match(text)
        if snap_m:
            year = int(snap_m.group("year"))
            week = int(snap_m.group("week"))
            return cls(raw=text, major=year, minor=0, patch=week, pre=snap_m.group("letter"), is_snapshot=True)

        m = _YEAR_VER_RE.match(text)
        if m:
            major = int(m.group("major"))
            minor = int(m.group("minor") or 0)
            patch = int(m.group("patch") or 0)
            pre = m.group("pre") or ""
            return cls(
                raw=text,
                major=major,
                minor=minor,
                patch=patch,
                pre=pre,
                is_snapshot=bool(pre),
            )
        # 兜底提取数字段
        nums = [int(x) for x in re.findall(r"\d+", text)[:3]]
        while len(nums) < 3:
            nums.append(0)
        return cls(raw=text, major=nums[0], minor=nums[1], patch=nums[2], pre=text, is_snapshot=True)

    def sort_key(self) -> tuple[int, int, int, int, str]:
        # 正式版 (pre == "") 排在同数字的预发布/快照版之后（即更大）
        release_rank = 1 if not self.pre else 0
        return (self.major, self.minor, self.patch, release_rank, self.pre)


def compare_versions(a: str, b: str) -> int:
    ka = ParsedVersion.parse(a).sort_key()
    kb = ParsedVersion.parse(b).sort_key()
    if ka < kb:
        return -1
    if ka > kb:
        return 1
    return 0


class VersionPredicateParser:
    """Fabric / SemVer 依赖版本范围解析器。

    支持：
    - `*` 或 `x` 通配，如 `26.1.x`
    - 比较运算符：`>=`, `<=`, `>`, `<`, `=`
    - 波浪号 `~` 与插入符 `^`
    - 空格分隔的 AND 组合，例如 `>=26.1 <26.2`
    - list[str] 表示 OR 组合

    注意：仅用于本地元数据辅助参考与依赖自检，升级兼容真源必须以远程平台 `game_versions` 为准。
    """

    @staticmethod
    def matches(version: str, predicate: str | list[str]) -> bool:
        if isinstance(predicate, list):
            return any(VersionPredicateParser.matches(version, item) for item in predicate)

        expr = predicate.strip()
        if not expr or expr == "*":
            return True

        # 处理空格分隔的 AND 条件
        tokens = [t.strip() for t in expr.split() if t.strip()]
        return all(VersionPredicateParser._match_single(version, tok) for tok in tokens)

    @staticmethod
    def _match_single(version: str, token: str) -> bool:
        if token in ("*", "x", "X"):
            return True

        v = ParsedVersion.parse(version)

        # 通配符 26.1.x / 26.x
        if token.lower().endswith(".x") or token.endswith(".*"):
            prefix = token[:-2]
            parts = [int(p) for p in prefix.split(".") if p.isdigit()]
            if len(parts) == 1:
                return v.major == parts[0]
            if len(parts) == 2:
                return v.major == parts[0] and v.minor == parts[1]

        # ~26.1 / ~26.1.2
        if token.startswith("~"):
            base_str = token[1:]
            base = ParsedVersion.parse(base_str)
            dot_count = base_str.split("-")[0].count(".")
            if v.sort_key() < base.sort_key():
                return False
            if dot_count == 0:
                return v.major == base.major
            return v.major == base.major and v.minor == base.minor

        # ^26.1 / ^0.2.3
        if token.startswith("^"):
            base_str = token[1:]
            base = ParsedVersion.parse(base_str)
            if v.sort_key() < base.sort_key():
                return False
            if base.major > 0:
                return v.major == base.major
            if base.minor > 0:
                return v.major == 0 and v.minor == base.minor
            return v.major == 0 and v.minor == 0 and v.patch == base.patch

        for op in (">=", "<=", ">", "<", "="):
            if token.startswith(op):
                target_str = token[len(op) :].strip()
                # Fabric 常见写法 >=26.1- （尾随 - 表示包含该版本的预发布/快照）
                if target_str.endswith("-"):
                    base_ver = ParsedVersion.parse(target_str[:-1])
                    min_key = (base_ver.major, base_ver.minor, base_ver.patch, 0, "")
                    vk = v.sort_key()
                    if op == ">=":
                        return vk >= min_key
                    if op == "<=":
                        return vk <= min_key
                    if op == ">":
                        return vk > min_key
                    if op == "<":
                        return vk < min_key
                    return vk == min_key
                cmp = compare_versions(version, target_str)
                if op == ">=":
                    return cmp >= 0
                if op == "<=":
                    return cmp <= 0
                if op == ">":
                    return cmp > 0
                if op == "<":
                    return cmp < 0
                if op == "=":
                    return cmp == 0

        # 无前缀默认精确匹配（忽略尾随 -）
        target_str = token[:-1] if token.endswith("-") else token
        return compare_versions(version, target_str) == 0
