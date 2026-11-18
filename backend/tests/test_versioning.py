from __future__ import annotations

from mc_updater.core.versioning import (
    ParsedVersion,
    VersionPredicateParser,
    compare_versions,
    is_year_based_mc_version,
)


def test_year_based_version_detection() -> None:
    assert is_year_based_mc_version("26.1") is True
    assert is_year_based_mc_version("26.1.2") is True
    assert is_year_based_mc_version("26.1-snapshot-1") is True
    assert is_year_based_mc_version("1.21.11") is False
    assert is_year_based_mc_version("1.20.1") is False


def test_version_ordering_no_lexicographical_bug() -> None:
    # 防止 "26.10" < "26.2" 字典序错误
    assert compare_versions("26.10", "26.2") > 0
    assert compare_versions("26.1", "1.21.11") > 0
    assert compare_versions("26.1", "26.1-snapshot-1") > 0
    assert compare_versions("26.1.1", "26.1") > 0
    assert ParsedVersion.parse("26w01a").is_snapshot is True


def test_fabric_version_predicate_parser() -> None:
    assert VersionPredicateParser.matches("26.1", ">=26.1") is True
    assert VersionPredicateParser.matches("26.1.1", "~26.1") is True
    assert VersionPredicateParser.matches("26.2", "~26.1") is False
    assert VersionPredicateParser.matches("26.2", "^26.1") is True
    assert VersionPredicateParser.matches("27.0", "^26.1") is False
    assert VersionPredicateParser.matches("26.1.3", "26.1.x") is True
    assert VersionPredicateParser.matches("26.1.3", ">=26.1 <26.2") is True
    assert VersionPredicateParser.matches("26.2", ">=26.1 <26.2") is False
    assert VersionPredicateParser.matches("26.1", ["1.21.1", "26.1"]) is True
    assert VersionPredicateParser.matches("26.1-snapshot-1", ">=26.1-") is True
    assert VersionPredicateParser.matches("26.1", ">=26.1-") is True
