<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshCw, ExternalLink, FolderUp, ArrowRight, ArrowLeft } from 'lucide-vue-next'
import { desktopApi } from '../bridge/pywebview'
import { useUpdaterStore } from '../stores/updater'
import type { ModUpgradePlan } from '../types/api'

const store = useUpdaterStore()
const showSnapshots = ref(false)
const statusFilter = ref('all')

const versionGroups = computed(() => {
  const list = store.gameVersions.filter((v) =>
    showSnapshots.value ? true : v.version_type === 'release'
  )
  return [
    {
      label: '26.1+ 年份制版本（推荐）',
      options: list.filter((v) => v.is_year_based),
    },
    {
      label: '传统 1.x 版本',
      options: list.filter((v) => !v.is_year_based),
    },
  ].filter((g) => g.options.length > 0)
})

async function refreshLoaderVersion() {
  if (!store.targetMcVersion || store.targetLoader === 'unknown') return
  try {
    const ver = await desktopApi.getRecommendedLoader(store.targetMcVersion, store.targetLoader)
    if (ver) store.targetLoaderVersion = ver
  } catch {
    // ignore
  }
}

watch([() => store.targetMcVersion, () => store.targetLoader], () => {
  refreshLoaderVersion()
})

onMounted(async () => {
  try {
    await store.loadGameVersions(false)
    await refreshLoaderVersion()
  } catch (err: unknown) {
    ElMessage.warning('加载 MC 版本列表失败：' + (err as Error).message)
  }
})

async function runCheck() {
  if (!store.targetMcVersion) {
    ElMessage.warning('请选择目标 MC 版本')
    return
  }
  store.busy = true
  store.busyText = `正在匹配 ${store.targetMcVersion} (${store.targetLoader}) 兼容版本并解析前置依赖...`
  try {
    store.upgradeResult = await desktopApi.checkUpgrades(
      store.targetMcVersion,
      store.targetLoader,
      store.targetLoaderVersion,
      store.settings.include_beta_by_default
    )
    store.downloadReport = null
    store.downloadItemStates = {}
    store.downloadCancelled = false
    ElMessage.success('兼容性检测与依赖解析完成')
  } catch (err: unknown) {
    ElMessage.error((err as Error).message)
  } finally {
    store.busy = false
  }
}

async function handleCandidateChange(plan: ModUpgradePlan, versionId: string) {
  try {
    store.upgradeResult = await desktopApi.updatePlanAction(plan.uid, 'select_candidate', versionId)
  } catch (err: unknown) {
    ElMessage.error((err as Error).message)
  }
}

async function handleAction(plan: ModUpgradePlan, action: 'skip' | 'keep_original') {
  try {
    store.upgradeResult = await desktopApi.updatePlanAction(plan.uid, action)
  } catch (err: unknown) {
    ElMessage.error((err as Error).message)
  }
}

async function handleManualJar(plan: ModUpgradePlan) {
  try {
    const res = await desktopApi.pickManualJarForMod(plan.uid)
    if (res) {
      store.upgradeResult = res
      ElMessage.success(`已导入 ${plan.mod.display_name} 的手动版本`)
    }
  } catch (err: unknown) {
    ElMessage.error((err as Error).message)
  }
}

async function openDownloadPage(url: string) {
  try {
    await desktopApi.openUrlInBrowser(url)
  } catch (err: unknown) {
    ElMessage.error((err as Error).message)
  }
}

const filteredPlans = computed(() => {
  if (!store.upgradeResult) return []
  if (statusFilter.value === 'all') return store.upgradeResult.plans
  return store.upgradeResult.plans.filter((p) => p.status === statusFilter.value)
})

const statusMeta: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
  upgradable: { label: '可升级', type: 'success' },
  beta_only: { label: '仅测试版', type: 'warning' },
  manual_required: { label: '需手动下载', type: 'danger' },
  unavailable: { label: '无新版', type: 'info' },
  keep_original: { label: '保留原版', type: 'warning' },
  skipped: { label: '已跳过', type: 'info' },
}
</script>

<template>
  <div class="view-wrap">
    <section class="solid-card target-bar">
      <div class="target-controls">
        <div class="field">
          <span class="field-label">目标 MC 版本</span>
          <el-select
            v-model="store.targetMcVersion"
            filterable
            allow-create
            placeholder="选择或输入 26.x"
            style="width: 190px"
          >
            <el-option-group v-for="grp in versionGroups" :key="grp.label" :label="grp.label">
              <el-option
                v-for="v in grp.options"
                :key="v.version"
                :label="v.version"
                :value="v.version"
              />
            </el-option-group>
          </el-select>
        </div>

        <div class="field">
          <span class="field-label">目标加载器</span>
          <el-select v-model="store.targetLoader" style="width: 140px">
            <el-option label="Fabric" value="fabric" />
            <el-option label="NeoForge" value="neoforge" />
            <el-option label="Forge" value="forge" />
            <el-option label="Quilt" value="quilt" />
          </el-select>
        </div>

        <div class="field">
          <span class="field-label">加载器版本</span>
          <el-input
            v-model="store.targetLoaderVersion"
            placeholder="自动获取"
            style="width: 145px"
          />
        </div>

        <el-checkbox v-model="showSnapshots">显示快照版</el-checkbox>
      </div>

      <div class="target-actions">
        <el-button @click="store.loadGameVersions(true)" title="刷新版本列表">
          <RefreshCw :size="15" />
        </el-button>
        <el-button type="primary" size="large" @click="runCheck">开始检测兼容性</el-button>
      </div>
    </section>

    <template v-if="store.upgradeResult">
      <section class="stats-row">
        <div class="solid-card stat-card" @click="statusFilter = 'all'">
          <div class="stat-num">{{ store.upgradeResult.summary_counts.total || 0 }}</div>
          <div class="stat-label">全部 Mod（含自动前置 {{ store.upgradeResult.summary_counts.auto_deps || 0 }}）</div>
        </div>
        <div class="solid-card stat-card emerald" @click="statusFilter = 'upgradable'">
          <div class="stat-num">{{ store.upgradeResult.summary_counts.upgradable || 0 }}</div>
          <div class="stat-label">可升级（正式版）</div>
        </div>
        <div class="solid-card stat-card amber" @click="statusFilter = 'beta_only'">
          <div class="stat-num">{{ store.upgradeResult.summary_counts.beta_only || 0 }}</div>
          <div class="stat-label">仅测试版</div>
        </div>
        <div class="solid-card stat-card rose" @click="statusFilter = 'manual_required'">
          <div class="stat-num">{{ store.upgradeResult.summary_counts.manual_required || 0 }}</div>
          <div class="stat-label">需手动下载</div>
        </div>
        <div class="solid-card stat-card muted-card" @click="statusFilter = 'unavailable'">
          <div class="stat-num">{{ store.upgradeResult.summary_counts.unavailable || 0 }}</div>
          <div class="stat-label">暂无新版</div>
        </div>
      </section>

      <el-alert
        v-for="(w, i) in [...store.upgradeResult.conflict_warnings, ...store.upgradeResult.dependency_warnings]"
        :key="i"
        :title="w"
        type="warning"
        show-icon
        :closable="false"
      />

      <section class="solid-card table-card">
        <el-table :data="filteredPlans" height="100%" style="width: 100%">
          <el-table-column label="Mod 名称" min-width="230">
            <template #default="{ row }">
              <div class="mod-name-col">
                <div class="mod-title">
                  {{ row.mod.display_name }}
                  <el-tag v-if="row.is_auto_dependency" size="small" type="success" effect="plain">
                    自动前置
                  </el-tag>
                </div>
                <div class="mod-note">{{ row.note || row.mod.filename }}</div>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="状态" width="115">
            <template #default="{ row }">
              <el-tag :type="statusMeta[row.status]?.type || 'info'" size="small" effect="dark">
                {{ statusMeta[row.status]?.label || row.status }}
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column label="目标版本选择" min-width="240">
            <template #default="{ row }">
              <el-select
                v-if="row.candidates.length > 0"
                :model-value="row.selected_candidate?.version_id"
                size="small"
                style="width: 100%"
                @change="(val: string) => handleCandidateChange(row, val)"
              >
                <el-option
                  v-for="c in row.candidates"
                  :key="c.version_id"
                  :label="`${c.version_number} [${c.release_type}]`"
                  :value="c.version_id"
                />
              </el-select>
              <span v-else class="muted">无可用版本</span>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button
                  v-if="row.status === 'manual_required' && row.selected_candidate?.website_url"
                  size="small"
                  type="warning"
                  plain
                  @click="openDownloadPage(row.selected_candidate.website_url)"
                >
                  <ExternalLink :size="13" style="margin-right: 4px" />
                  下载页
                </el-button>
                <el-button
                  v-if="row.status === 'manual_required'"
                  size="small"
                  type="primary"
                  plain
                  @click="handleManualJar(row)"
                >
                  <FolderUp :size="13" style="margin-right: 4px" />
                  导入
                </el-button>
                <el-button
                  v-if="row.mod.local_path && row.status !== 'keep_original'"
                  size="small"
                  plain
                  @click="handleAction(row, 'keep_original')"
                >
                  保留原版
                </el-button>
                <el-button
                  v-if="row.status !== 'skipped'"
                  size="small"
                  plain
                  @click="handleAction(row, 'skip')"
                >
                  跳过
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <footer class="bottom-nav">
        <el-button @click="store.step = 0">
          <ArrowLeft :size="15" style="margin-right: 6px" />
          返回上一步
        </el-button>
        <el-button type="primary" size="large" @click="store.step = 2">
          下一步：下载 Mod 与选择配置
          <ArrowRight :size="16" style="margin-left: 6px" />
        </el-button>
      </footer>
    </template>
  </div>
</template>

<style scoped>
.view-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
}

.target-bar {
  padding: 14px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-shrink: 0;
}

.target-controls {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.field {
  display: flex;
  align-items: center;
  gap: 8px;
}

.field-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.target-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  flex-shrink: 0;
}

.stat-card {
  padding: 12px 14px;
  cursor: pointer;
}

.stat-num {
  font-size: 22px;
  font-weight: 800;
}

.stat-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.stat-card.emerald .stat-num {
  color: #34d399;
}
.stat-card.amber .stat-num {
  color: #fbbf24;
}
.stat-card.rose .stat-num {
  color: #fb7185;
}
.stat-card.muted-card .stat-num {
  color: #94a3b8;
}

.table-card {
  flex: 1;
  min-height: 0;
  padding: 8px;
  overflow: hidden;
}

.mod-title {
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}

.mod-note {
  font-size: 11px;
  color: var(--text-secondary);
}

.row-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.muted {
  color: var(--text-secondary);
  font-size: 12px;
}

.bottom-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
</style>
