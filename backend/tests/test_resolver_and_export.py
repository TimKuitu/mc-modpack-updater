from __future__ import annotations

import json
import zipfile
from pathlib import Path

import httpx
import pytest

from mc_updater.clients.curseforge import CurseForgeClient
from mc_updater.clients.http_client import RateLimitedHttpClient
from mc_updater.clients.modrinth import ModrinthClient
from mc_updater.core.hashing import compute_bytes_hashes
from mc_updater.core.models import (
    AppSettings,
    CompatStatus,
    ConfigItem,
    LoaderType,
    ModEntry,
    ModPlatform,
)
from mc_updater.downloader.download_manager import download_upgrade_plans
from mc_updater.exporter.backup_exporter import export_config_backup_zip
from mc_updater.exporter.mrpack_exporter import export_pcl2_mrpack
from mc_updater.resolver.dependency_resolver import resolve_dependencies_and_conflicts
from mc_updater.resolver.upgrade_matcher import match_pack_upgrades


@pytest.mark.asyncio
async def test_full_upgrade_dep_download_and_mrpack_export(tmp_path: Path) -> None:
    # 准备假 jar 字节与哈希
    mr_jar = b"PK\x03\x04modrinth-new-jar-bytes"
    dep_jar = b"PK\x03\x04fabric-api-jar-bytes"
    cf_jar = b"PK\x03\x04curseforge-jar-bytes"
    mr_h = compute_bytes_hashes(mr_jar)
    dep_h = compute_bytes_hashes(dep_jar)
    cf_h = compute_bytes_hashes(cf_jar)

    old_h1 = compute_bytes_hashes(b"old-sodium")
    old_h2 = compute_bytes_hashes(b"old-beta-only")
    old_h3 = compute_bytes_hashes(b"old-cf-mod")
    old_h4 = compute_bytes_hashes(b"old-dead-mod")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/v2/version_files/update"):
            body = json.loads(request.content.decode())
            vtypes = body.get("version_types") or []
            if "release" in vtypes:
                return httpx.Response(
                    200,
                    json={
                        old_h1.sha512: {
                            "id": "ver_sodium_261",
                            "project_id": "proj_sodium",
                            "version_number": "0.7.0",
                            "version_type": "release",
                            "game_versions": ["26.1"],
                            "loaders": ["fabric"],
                            "files": [
                                {
                                    "primary": True,
                                    "url": "https://cdn.modrinth.com/data/proj_sodium/versions/ver_sodium_261/sodium-0.7.0.jar",
                                    "filename": "sodium-0.7.0.jar",
                                    "size": len(mr_jar),
                                    "hashes": {"sha1": mr_h.sha1, "sha512": mr_h.sha512},
                                }
                            ],
                            "dependencies": [
                                {
                                    "project_id": "proj_fapi",
                                    "version_id": "ver_old_stale",
                                    "dependency_type": "required",
                                }
                            ],
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    old_h2.sha512: {
                        "id": "ver_beta_261",
                        "project_id": "proj_beta",
                        "version_number": "1.0.0-beta.1",
                        "version_type": "beta",
                        "game_versions": ["26.1"],
                        "loaders": ["fabric"],
                        "files": [
                            {
                                "primary": True,
                                "url": "https://cdn.modrinth.com/data/proj_beta/versions/ver_beta_261/beta-1.0.0.jar",
                                "filename": "beta-1.0.0.jar",
                                "size": len(mr_jar),
                                "hashes": {"sha1": mr_h.sha1, "sha512": mr_h.sha512},
                            }
                        ],
                        "dependencies": [],
                    }
                },
            )

        if "/v2/project/proj_sodium/version" in url:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "ver_sodium_261",
                        "project_id": "proj_sodium",
                        "version_number": "0.7.0",
                        "version_type": "release",
                        "game_versions": ["26.1"],
                        "loaders": ["fabric"],
                        "files": [
                            {
                                "primary": True,
                                "url": "https://cdn.modrinth.com/data/proj_sodium/versions/ver_sodium_261/sodium-0.7.0.jar",
                                "filename": "sodium-0.7.0.jar",
                                "size": len(mr_jar),
                                "hashes": {"sha1": mr_h.sha1, "sha512": mr_h.sha512},
                            }
                        ],
                        "dependencies": [
                            {"project_id": "proj_fapi", "version_id": "ver_old_stale", "dependency_type": "required"}
                        ],
                    }
                ],
            )
        if "/v2/project/proj_fapi/version" in url:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "ver_fapi_261",
                        "project_id": "proj_fapi",
                        "version_number": "0.120.0+26.1",
                        "version_type": "release",
                        "game_versions": ["26.1"],
                        "loaders": ["fabric"],
                        "files": [
                            {
                                "primary": True,
                                "url": "https://cdn.modrinth.com/data/proj_fapi/versions/ver_fapi_261/fabric-api-0.120.0.jar",
                                "filename": "fabric-api-0.120.0.jar",
                                "size": len(dep_jar),
                                "hashes": {"sha1": dep_h.sha1, "sha512": dep_h.sha512},
                            }
                        ],
                        "dependencies": [],
                    }
                ],
            )
        if "/v2/projects" in url:
            return httpx.Response(
                200,
                json=[{"id": "proj_fapi", "title": "Fabric API", "slug": "fabric-api"}],
            )
        if "/v1/mods/555/files" in url:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": 777,
                            "modId": 555,
                            "displayName": "CF Mod 26.1",
                            "fileName": "cfmod-26.1.jar",
                            "fileLength": len(cf_jar),
                            "releaseType": 1,
                            "isAvailable": True,
                            "gameVersions": ["26.1", "Fabric"],
                            "downloadUrl": "https://edge.forgecdn.net/files/777/cfmod-26.1.jar",
                            "hashes": [{"algo": 1, "value": cf_h.sha1}, {"algo": 2, "value": cf_h.md5}],
                        }
                    ]
                },
            )
        if "sodium-0.7.0.jar" in url or "beta-1.0.0.jar" in url:
            return httpx.Response(200, content=mr_jar)
        if "fabric-api-0.120.0.jar" in url:
            return httpx.Response(200, content=dep_jar)
        if "cfmod-26.1.jar" in url:
            return httpx.Response(200, content=cf_jar)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    settings = AppSettings(use_mcim_mirror=False, curseforge_api_key="cf-key", concurrency=4)
    http = RateLimitedHttpClient(settings=settings, transport=transport)
    mr = ModrinthClient(http, base_url_override="https://api.modrinth.com/v2")
    cf = CurseForgeClient(http, api_key="cf-key", base_url_override="https://api.curseforge.com/v1")

    mods = [
        ModEntry(
            uid="m1",
            filename="sodium-old.jar",
            hashes=old_h1,
            platform=ModPlatform.MODRINTH,
            modrinth_project_id="proj_sodium",
            display_name="Sodium",
        ),
        ModEntry(
            uid="m2",
            filename="beta-old.jar",
            hashes=old_h2,
            platform=ModPlatform.MODRINTH,
            modrinth_project_id="proj_beta",
            display_name="BetaMod",
        ),
        ModEntry(
            uid="m3",
            filename="cf-old.jar",
            hashes=old_h3,
            platform=ModPlatform.CURSEFORGE,
            curseforge_mod_id=555,
            slug="cf-mod",
            display_name="CF Mod",
        ),
        ModEntry(
            uid="m4",
            filename="dead-old.jar",
            hashes=old_h4,
            platform=ModPlatform.LOCAL,
            display_name="DeadMod",
        ),
    ]

    plans = await match_pack_upgrades(mods, "26.1", LoaderType.FABRIC, mr, cf)
    by_uid = {p.uid: p for p in plans}
    assert by_uid["m1"].status == CompatStatus.UPGRADABLE
    assert by_uid["m2"].status == CompatStatus.BETA_ONLY
    assert by_uid["m3"].status == CompatStatus.UPGRADABLE
    assert by_uid["m4"].status == CompatStatus.UNAVAILABLE

    plans_with_deps, dep_warns, conflict_warns = await resolve_dependencies_and_conflicts(
        plans, "26.1", LoaderType.FABRIC, mr, cf
    )
    await http.close()

    assert not dep_warns
    assert not conflict_warns
    assert any(p.is_auto_dependency and p.mod.modrinth_project_id == "proj_fapi" for p in plans_with_deps)

    # 下载校验
    dl_dir = tmp_path / "dl"
    dl_report = await download_upgrade_plans(
        plans_with_deps,
        dl_dir,
        settings,
        transport=transport,
    )
    assert not dl_report.failed_items
    assert len(dl_report.downloaded_files) == 4  # sodium, beta, cfmod, fabric-api

    # 准备原配置目录
    game_dir = tmp_path / "instance"
    (game_dir / "config").mkdir(parents=True)
    (game_dir / "config" / "sodium.json").write_text('{"fps": true}', encoding="utf-8")
    (game_dir / "options.txt").write_text("lang:zh_cn\n", encoding="utf-8")

    cfg_items = [
        ConfigItem(rel_path="config", label="config", selected=True),
        ConfigItem(rel_path="options.txt", label="options.txt", selected=True),
    ]

    # 导出备份 zip
    backup_zip = tmp_path / "backup.zip"
    _, _, cfg_cnt = export_config_backup_zip(game_dir, cfg_items, backup_zip)
    assert cfg_cnt == 2
    assert backup_zip.is_file()

    # 导出 PCL2 兼容 .mrpack
    out_mrpack = tmp_path / "upgraded-26.1.mrpack"
    exp = export_pcl2_mrpack(
        pack_name="测试整合包",
        version_id="2.0.0",
        target_mc="26.1",
        target_loader=LoaderType.FABRIC,
        target_loader_version="0.16.10",
        plans=plans_with_deps,
        download_report=dl_report,
        game_dir=game_dir,
        config_items=cfg_items,
        output_path=out_mrpack,
    )

    assert exp.included_mods_in_index == 3  # Modrinth 白名单进 files[]
    assert exp.included_mods_in_overrides == 1  # CurseForge CDN 进 overrides/mods/
    assert exp.included_config_files == 2

    with zipfile.ZipFile(out_mrpack, "r") as zf:
        names = set(zf.namelist())
        assert "modrinth.index.json" in names
        assert "overrides/mods/cfmod-26.1.jar" in names
        assert "overrides/config/sodium.json" in names
        assert "overrides/options.txt" in names
        idx = json.loads(zf.read("modrinth.index.json").decode("utf-8"))
        assert idx["dependencies"]["minecraft"] == "26.1"
        assert idx["dependencies"]["fabric-loader"] == "0.16.10"
