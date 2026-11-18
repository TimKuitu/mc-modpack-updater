from __future__ import annotations

import asyncio
from typing import Any

from mc_updater.clients.curseforge import CurseForgeClient
from mc_updater.clients.modrinth import ModrinthClient, parse_modrinth_version
from mc_updater.core.models import (
    CandidateVersion,
    CompatStatus,
    LoaderType,
    ModEntry,
    ModPlatform,
    ModUpgradePlan,
)


def _pick_best_candidate(
    candidates: list[CandidateVersion],
    prefer_beta: bool = False,
) -> CandidateVersion | None:
    if not candidates:
        return None
    releases = [c for c in candidates if c.release_type == "release"]
    if releases:
        return releases[0]
    if prefer_beta or candidates:
        return candidates[0]
    return None


async def match_pack_upgrades(
    mods: list[ModEntry],
    target_mc: str,
    target_loader: LoaderType,
    modrinth: ModrinthClient,
    curseforge: CurseForgeClient | None = None,
    prefer_beta: bool = False,
) -> list[ModUpgradePlan]:
    """为整合包内所有 Mod 计算目标版本兼容性与候选更新。

    关键策略：
    - 严禁依赖本地 `>=1.21` 开放区间，严格以平台 `game_versions` 为真源；
    - Modrinth 采用两步分流：先查 release，未命中再查 beta/alpha，避免测试版盖住正式版；
    - CurseForge 禁分发 Mod 先尝试在 Modrinth 交叉查找替代，找不到则标记 MANUAL_REQUIRED。
    """
    loaders = [target_loader.value] if target_loader != LoaderType.UNKNOWN else []
    game_versions = [target_mc]

    # 1. 收集有哈希的 Mod，走 Modrinth 批量 /version_files/update 两步调用
    hash_to_mod: dict[str, ModEntry] = {}
    for m in mods:
        if m.hashes and m.hashes.sha512:
            hash_to_mod[m.hashes.sha512] = m

    release_hits: dict[str, CandidateVersion] = {}
    beta_hits: dict[str, CandidateVersion] = {}

    if hash_to_mod:
        all_hashes = list(hash_to_mod.keys())
        try:
            raw_rel = await modrinth.find_updates_by_hashes(
                all_hashes,
                loaders=loaders,
                game_versions=game_versions,
                algorithm="sha512",
                version_types=["release"],
            )
            for h, vobj in raw_rel.items():
                cand = parse_modrinth_version(vobj)
                # 二次验证：防止镜像/服务端忽略 version_types 或 game_versions
                if cand.release_type == "release" and target_mc in cand.game_versions:
                    release_hits[h] = cand
        except Exception:
            pass

        missing_hashes = [h for h in all_hashes if h not in release_hits]
        if missing_hashes:
            try:
                raw_beta = await modrinth.find_updates_by_hashes(
                    missing_hashes,
                    loaders=loaders,
                    game_versions=game_versions,
                    algorithm="sha512",
                    version_types=["beta", "alpha"],
                )
                for h, vobj in raw_beta.items():
                    cand = parse_modrinth_version(vobj)
                    if target_mc in cand.game_versions:
                        beta_hits[h] = cand
            except Exception:
                pass

    # 2. 对每个 Mod 补全候选版本列表并决定最终状态
    sem = asyncio.Semaphore(6)

    async def process_single(mod: ModEntry) -> ModUpgradePlan:
        async with sem:
            sha512 = mod.hashes.sha512 if mod.hashes else ""
            candidates: list[CandidateVersion] = []

            # 2a. 已有 Modrinth project_id -> 拉取该项目的完整兼容版本列表（供用户微调切换）
            if mod.modrinth_project_id:
                try:
                    candidates = await modrinth.get_project_versions(
                        mod.modrinth_project_id,
                        loaders=loaders or None,
                        game_versions=game_versions,
                    )
                except Exception:
                    candidates = []
                # 若批量接口命中了但详情接口被限流或为空，补回批量结果
                if not candidates:
                    if sha512 in release_hits:
                        candidates = [release_hits[sha512]]
                    elif sha512 in beta_hits:
                        candidates = [beta_hits[sha512]]

            # 2b. 若仍无候选，尝试 CurseForge 通道
            if not candidates and mod.curseforge_mod_id and curseforge and curseforge.enabled:
                try:
                    candidates = await curseforge.get_mod_files(
                        mod.curseforge_mod_id,
                        target_mc=target_mc,
                        target_loader=target_loader,
                        mod_slug=mod.slug or "",
                    )
                except Exception:
                    candidates = []

            # 2c. 若无平台身份（如纯本地 jar），尝试按 slug / mod_id 在 Modrinth 交叉搜索
            cross_note = ""
            if not candidates and not mod.modrinth_project_id and not mod.curseforge_mod_id:
                query = mod.slug or (mod.jar_meta.mod_id if mod.jar_meta else "") or mod.display_name
                if query:
                    try:
                        hits = await modrinth.search_project(
                            query,
                            loader=target_loader.value if target_loader != LoaderType.UNKNOWN else None,
                            game_version=target_mc,
                            limit=3,
                        )
                        exact = next(
                            (h for h in hits if (h.get("slug") or "").lower() == query.lower()),
                            hits[0] if hits else None,
                        )
                        if exact and exact.get("project_id"):
                            candidates = await modrinth.get_project_versions(
                                exact["project_id"],
                                loaders=loaders or None,
                                game_versions=game_versions,
                            )
                            if candidates:
                                cross_note = f"通过 Modrinth 名称匹配到 {exact.get('title', query)}"
                    except Exception:
                        pass

            # 2d. 若 CurseForge 命中但禁止第三方分发，尝试在 Modrinth 找直链替代
            best = _pick_best_candidate(candidates, prefer_beta=prefer_beta)
            if best and best.platform == ModPlatform.CURSEFORGE and not best.allow_distribution:
                alt_query = mod.slug or mod.display_name
                if alt_query:
                    try:
                        hits = await modrinth.search_project(
                            alt_query,
                            loader=target_loader.value if target_loader != LoaderType.UNKNOWN else None,
                            game_version=target_mc,
                            limit=3,
                        )
                        exact = next(
                            (h for h in hits if (h.get("slug") or "").lower() == alt_query.lower()),
                            None,
                        )
                        if exact and exact.get("project_id"):
                            mr_cands = await modrinth.get_project_versions(
                                exact["project_id"],
                                loaders=loaders or None,
                                game_versions=game_versions,
                            )
                            mr_best = _pick_best_candidate(mr_cands, prefer_beta=prefer_beta)
                            if mr_best:
                                candidates = mr_cands + candidates
                                best = mr_best
                                cross_note = "CurseForge 禁分发，已自动切换至 Modrinth 同源直链"
                    except Exception:
                        pass

            # 3. 判定最终状态
            if not best:
                return ModUpgradePlan(
                    uid=mod.uid,
                    mod=mod,
                    status=CompatStatus.UNAVAILABLE,
                    candidates=[],
                    note=f"平台暂无适配 {target_mc} 的版本",
                )

            if not best.allow_distribution or not best.download_url:
                return ModUpgradePlan(
                    uid=mod.uid,
                    mod=mod,
                    status=CompatStatus.MANUAL_REQUIRED,
                    selected_candidate=best,
                    candidates=candidates,
                    note="作者禁止第三方下载，请点击链接手动下载 .jar 后导入校验",
                )

            status = CompatStatus.UPGRADABLE if best.release_type == "release" else CompatStatus.BETA_ONLY
            return ModUpgradePlan(
                uid=mod.uid,
                mod=mod,
                status=status,
                selected_candidate=best,
                candidates=candidates,
                note=cross_note or ("仅找到测试版 (beta/alpha)" if status == CompatStatus.BETA_ONLY else ""),
            )

    tasks = [process_single(m) for m in mods]
    return list(await asyncio.gather(*tasks))
