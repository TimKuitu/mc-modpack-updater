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
from mc_updater.core.models import AppSettings, LoaderType, ModPlatform, SourceType
from mc_updater.parsers.input_detector import detect_and_prepare_input
from mc_updater.parsers.mod_identifier import identify_pack_mods


def _make_fabric_jar(path: Path, mod_id: str, name: str, version: str) -> bytes:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "fabric.mod.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "id": mod_id,
                    "version": version,
                    "name": name,
                    "authors": ["TestAuthor"],
                    "depends": {"minecraft": ">=26.1-"},
                    "jars": [{"file": "META-INF/jars/embedded-lib.jar"}],
                }
            ),
        )
    return path.read_bytes()


def _make_neoforge_jar(path: Path, mod_id: str, name: str, version: str) -> bytes:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "META-INF/neoforge.mods.toml",
            f'modLoader="javafml"\n[[mods]]\nmodId="{mod_id}"\nversion="{version}"\ndisplayName="{name}"\n',
        )
    return path.read_bytes()


@pytest.mark.asyncio
async def test_pcl2_isolated_instance_and_four_stage_identify(tmp_path: Path) -> None:
    dot_mc = tmp_path / ".minecraft"
    versions = dot_mc / "versions"
    vanilla_dir = versions / "26.1"
    inst_dir = versions / "26.1-Fabric-Pack"
    vanilla_dir.mkdir(parents=True)
    (inst_dir / "mods").mkdir(parents=True)
    (inst_dir / "config").mkdir(parents=True)
    (inst_dir / "PCL").mkdir(parents=True)

    (vanilla_dir / "26.1.json").write_text(json.dumps({"id": "26.1", "type": "release"}), encoding="utf-8")
    (inst_dir / "26.1-Fabric-Pack.json").write_text(
        json.dumps(
            {
                "id": "26.1-Fabric-Pack",
                "inheritsFrom": "26.1",
                "libraries": [{"name": "net.fabricmc:fabric-loader:0.16.10"}],
            }
        ),
        encoding="utf-8",
    )
    (inst_dir / "PCL" / "Setup.ini").write_text("VersionArgumentIndie:1\n", encoding="utf-8")
    (inst_dir / "config" / "sodium.json").write_text("{}", encoding="utf-8")

    jar1_bytes = _make_fabric_jar(inst_dir / "mods" / "sodium-26.1.jar", "sodium", "Sodium", "0.6.0")
    jar2_bytes = _make_fabric_jar(inst_dir / "mods" / "iris-26.1.jar.disabled", "iris", "Iris", "1.8.0")
    jar3_bytes = _make_neoforge_jar(inst_dir / "mods" / "custom-local.jar", "customlocal", "CustomLocal", "1.0.0")

    h1 = compute_bytes_hashes(jar1_bytes)
    h2 = compute_bytes_hashes(jar2_bytes)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/v2/version_files"):
            body = json.loads(request.content.decode())
            if body.get("algorithm") == "sha512":
                return httpx.Response(
                    200,
                    json={
                        h1.sha512: {
                            "id": "ver_sodium_old",
                            "project_id": "proj_sodium",
                            "version_number": "0.6.0",
                        }
                    },
                )
            return httpx.Response(200, json={})
        if "/v2/projects" in url:
            return httpx.Response(
                200,
                json=[{"id": "proj_sodium", "title": "Sodium", "slug": "sodium", "icon_url": "https://x/s.png"}],
            )
        if url.endswith("/v1/fingerprints/432"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "exactMatches": [
                            {
                                "id": 99999,
                                "file": {"id": 88888, "fileFingerprint": h2.murmur2},
                            }
                        ]
                    }
                },
            )
        if url.endswith("/v1/mods"):
            return httpx.Response(
                200,
                json={"data": [{"id": 99999, "name": "Iris Shaders", "slug": "irisshaders"}]},
            )
        return httpx.Response(404)

    http = RateLimitedHttpClient(
        settings=AppSettings(use_mcim_mirror=False, curseforge_api_key="test-key"),
        transport=httpx.MockTransport(handler),
    )
    mr = ModrinthClient(http, base_url_override="https://api.modrinth.com/v2")
    cf = CurseForgeClient(http, api_key="test-key", base_url_override="https://api.curseforge.com/v1")

    detected = detect_and_prepare_input(str(inst_dir))
    assert detected.source_type == SourceType.PCL2_DIR
    assert detected.mc_version == "26.1"
    assert detected.loader == LoaderType.FABRIC
    assert detected.loader_version == "0.16.10"
    assert detected.needs_shared_confirmation is False

    result = await identify_pack_mods(detected, mr, cf)
    await http.close()

    assert len(result.mods) == 3
    by_name = {m.filename: m for m in result.mods}
    assert by_name["sodium-26.1.jar"].platform == ModPlatform.MODRINTH
    assert by_name["sodium-26.1.jar"].identified_by == "modrinth_hash"
    assert by_name["iris-26.1.jar.disabled"].disabled is True
    assert by_name["iris-26.1.jar.disabled"].platform == ModPlatform.CURSEFORGE
    assert by_name["iris-26.1.jar.disabled"].identified_by == "curseforge_fp"
    assert by_name["custom-local.jar"].platform == ModPlatform.LOCAL
    assert by_name["custom-local.jar"].jar_meta is not None
    assert by_name["custom-local.jar"].jar_meta.mod_id == "customlocal"


def test_pcl2_non_isolated_requires_confirmation(tmp_path: Path) -> None:
    dot_mc = tmp_path / ".minecraft"
    inst_dir = dot_mc / "versions" / "26.1-Shared"
    inst_dir.mkdir(parents=True)
    (dot_mc / "mods").mkdir(parents=True)
    (inst_dir / "26.1-Shared.json").write_text(json.dumps({"id": "26.1"}), encoding="utf-8")

    detected = detect_and_prepare_input(str(inst_dir), allow_shared_fallback=False)
    assert detected.needs_shared_confirmation is True

    confirmed = detect_and_prepare_input(str(inst_dir), allow_shared_fallback=True)
    assert confirmed.needs_shared_confirmation is False
    assert confirmed.isolation_mode == "shared_confirmed"
    assert confirmed.mods_dir == dot_mc / "mods"
