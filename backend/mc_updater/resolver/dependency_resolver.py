from __future__ import annotations

import uuid

from mc_updater.clients.curseforge import CurseForgeClient
from mc_updater.clients.modrinth import ModrinthClient
from mc_updater.core.models import (
    CandidateVersion,
    CompatStatus,
    LoaderType,
    ModEntry,
    ModPlatform,
    ModUpgradePlan,
)


async def resolve_dependencies_and_conflicts(
    plans: list[ModUpgradePlan],
    target_mc: str,
    target_loader: LoaderType,
    modrinth: ModrinthClient,
    curseforge: CurseForgeClient | None = None,
) -> tuple[list[ModUpgradePlan], list[str], list[str]]:
    """递归补全 required 前置依赖，并检测 incompatible 冲突。"""
    result_plans = list(plans)
    dep_warnings: list[str] = []
    conflict_warnings: list[str] = []

    loaders = [target_loader.value] if target_loader != LoaderType.UNKNOWN else []
    game_versions = [target_mc]

    def _active_project_keys() -> dict[tuple[ModPlatform, str], ModUpgradePlan]:
        mapping: dict[tuple[ModPlatform, str], ModUpgradePlan] = {}
        for p in result_plans:
            if p.status == CompatStatus.SKIPPED or p.user_action == "skip":
                continue
            if p.selected_candidate:
                mapping[(p.selected_candidate.platform, p.selected_candidate.project_id)] = p
            if p.mod.modrinth_project_id:
                mapping[(ModPlatform.MODRINTH, p.mod.modrinth_project_id)] = p
            if p.mod.curseforge_mod_id:
                mapping[(ModPlatform.CURSEFORGE, str(p.mod.curseforge_mod_id))] = p
        return mapping

    # BFS 队列解析 required 依赖，带 visited 防环
    visited_projects: set[tuple[ModPlatform, str]] = set()
    queue: list[ModUpgradePlan] = [
        p
        for p in result_plans
        if p.selected_candidate and p.status not in (CompatStatus.SKIPPED, CompatStatus.UNAVAILABLE)
    ]

    while queue:
        parent_plan = queue.pop(0)
        cand = parent_plan.selected_candidate
        if not cand:
            continue
        parent_key = (cand.platform, cand.project_id)
        if parent_key in visited_projects:
            continue
        visited_projects.add(parent_key)

        active_keys = _active_project_keys()

        for dep in cand.dependencies:
            if dep.dependency_type == "embedded" or not dep.project_id:
                continue

            dep_key = (dep.platform, dep.project_id)

            if dep.dependency_type == "incompatible":
                if dep_key in active_keys:
                    other = active_keys[dep_key]
                    msg = f"冲突告警：{parent_plan.mod.display_name} 与 {other.mod.display_name} 不兼容"
                    if msg not in conflict_warnings:
                        conflict_warnings.append(msg)
                    if other.mod.display_name not in parent_plan.conflicts_with:
                        parent_plan.conflicts_with.append(other.mod.display_name)
                    if parent_plan.mod.display_name not in other.conflicts_with:
                        other.conflicts_with.append(parent_plan.mod.display_name)
                continue

            if dep.dependency_type != "required":
                continue

            if dep_key in active_keys:
                existing = active_keys[dep_key]
                if parent_plan.mod.display_name not in existing.required_by:
                    existing.required_by.append(parent_plan.mod.display_name)
                continue

            if dep_key in visited_projects:
                continue

            # 拉取缺失的前置依赖兼容版本
            dep_cands: list[CandidateVersion] = []
            dep_name = dep.project_id
            dep_slug = dep.project_id
            dep_icon = None

            if dep.platform == ModPlatform.MODRINTH:
                try:
                    dep_cands = await modrinth.get_project_versions(
                        dep.project_id,
                        loaders=loaders or None,
                        game_versions=game_versions,
                    )
                    proj_map = await modrinth.get_projects_batch([dep.project_id])
                    if dep.project_id in proj_map:
                        dep_name = proj_map[dep.project_id].get("title") or dep_name
                        dep_slug = proj_map[dep.project_id].get("slug") or dep_slug
                        dep_icon = proj_map[dep.project_id].get("icon_url")
                except Exception:
                    dep_cands = []
            elif dep.platform == ModPlatform.CURSEFORGE and curseforge and curseforge.enabled:
                try:
                    cf_id = int(dep.project_id)
                    mods_meta = await curseforge.get_mods_batch([cf_id])
                    if cf_id in mods_meta:
                        dep_name = mods_meta[cf_id].get("name") or dep_name
                        dep_slug = mods_meta[cf_id].get("slug") or dep_slug
                        dep_icon = (mods_meta[cf_id].get("logo") or {}).get("thumbnailUrl")
                    dep_cands = await curseforge.get_mod_files(
                        cf_id,
                        target_mc=target_mc,
                        target_loader=target_loader,
                        mod_slug=dep_slug,
                    )
                except Exception:
                    dep_cands = []

            best_dep = next((c for c in dep_cands if c.release_type == "release"), dep_cands[0] if dep_cands else None)
            if not best_dep:
                dep_warnings.append(
                    f"前置依赖 {dep_name}（由 {parent_plan.mod.display_name} 需要）暂无适配 {target_mc} 的版本"
                )
                continue

            dep_mod = ModEntry(
                uid=str(uuid.uuid4()),
                filename=best_dep.filename,
                platform=dep.platform,
                modrinth_project_id=dep.project_id if dep.platform == ModPlatform.MODRINTH else None,
                curseforge_mod_id=int(dep.project_id) if dep.platform == ModPlatform.CURSEFORGE else None,
                slug=dep_slug,
                display_name=dep_name,
                current_version=best_dep.version_number,
                icon_url=dep_icon,
                identified_by="auto_dependency",
                is_library=True,
            )
            dep_status = (
                CompatStatus.MANUAL_REQUIRED
                if (not best_dep.allow_distribution or not best_dep.download_url)
                else (CompatStatus.UPGRADABLE if best_dep.release_type == "release" else CompatStatus.BETA_ONLY)
            )
            new_plan = ModUpgradePlan(
                uid=dep_mod.uid,
                mod=dep_mod,
                status=dep_status,
                selected_candidate=best_dep,
                candidates=dep_cands,
                is_auto_dependency=True,
                required_by=[parent_plan.mod.display_name],
                note=f"自动补齐前置（被 {parent_plan.mod.display_name} 依赖）",
            )
            result_plans.append(new_plan)
            queue.append(new_plan)

    return result_plans, dep_warnings, conflict_warnings
