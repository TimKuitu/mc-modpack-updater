<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DownloadCloud,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Square,
  Clock,
  Loader2,
  XCircle,
  PauseCircle,
  Zap,
} from 'lucide-vue-next'
import { desktopApi } from '../bridge/pywebview'
import { useUpdaterStore } from '../stores/updater'
import type { DownloadReport, ModDownloadItemState, ModDownloadStatus, ModUpgradePlan } from '../types/api'

const store = useUpdaterStore()
const skipModrinth = ref(store.settings.skip_modrinth_download_for_mrpack)
const modFilter = ref<'all' | 'downloaded' | 'active' | 'attention' | 'ignored'>('all')
let pollTimer: number | null = null

const percent = computed(() => {
  if (!store.downloadTotal) return 0
  return Math.min(100, Math.round((store.downloadCurrent / store.downloadTotal) * 100))
})

function formatBytes(bytes: number) {
  if (!bytes || bytes <= 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function inferInitialStatus(plan: ModUpgradePlan): ModDownloadStatus {
  if (plan.user_action === 'manual_jar' && plan.manual_jar_path) {
    return 'downloaded'
  }
  if (plan.user_action === 'keep_original' || plan.status === 'keep_original') {
    return 'keep_original'
  }
  if (
    plan.user_action === 'skip' ||
    plan.status === 'skipped' ||
    plan.status === 'unavailable' ||
    plan.status === 'manual_required'
  ) {
    return 'skipped'
  }
  const cand = plan.selected_candidate
  if (!cand || !cand.download_url) {
    return 'skipped'
  }
  if (skipModrinth.value && cand.platform === 'modrinth') {
    return 'skipped_fast'
  }
  return 'pending'
}

interface ModDownloadRow {
  uid: string
  name: string
  filename: string
  platform: string
  status: ModDownloadStatus
  downloadedBytes: number
  totalBytes: number
  error: string
}

const modRows = computed<ModDownloadRow[]>(() => {
  const plans = store.upgradeResult?.plans || []
  return plans.map((plan) => {
    const live = store.downloadItemStates[plan.uid] || store.downloadReport?.item_states?.[plan.uid]
    const status: ModDownloadStatus = live ? live.status : inferInitialStatus(plan)
    const cand = plan.selected_candidate
    return {
      uid: plan.uid,
      name: plan.mod.display_name,
      filename: cand?.filename || plan.mod.filename,
      platform: cand?.platform || plan.mod.platform,
      status,
      downloadedBytes: live?.downloaded_bytes ?? 0,
      totalBytes: live?.total_bytes || cand?.file_size || 0,
      error: live?.error || '',
    }
  })
})

const counts = computed(() => {
  const res = {
    total: modRows.value.length,
    downloaded: 0,
    active: 0,
    attention: 0,
    ignored: 0,
  }
  for (const r of modRows.value) {
    if (r.status === 'downloaded') res.downloaded++
    else if (r.status === 'pending' || r.status === 'downloading') res.active++
    else if (r.status === 'cancelled' || r.status === 'failed') res.attention++
    else res.ignored++
  }
  return res
})

const filteredRows = computed(() => {
  if (modFilter.value === 'all') return modRows.value
  if (modFilter.value === 'downloaded') return modRows.value.filter((r) => r.status === 'downloaded')
  if (modFilter.value === 'active') {
    return modRows.value.filter((r) => r.status === 'pending' || r.status === 'downloading')
  }
  if (modFilter.value === 'attention') {
    return modRows.value.filter((r) => r.status === 'cancelled' || r.status === 'failed')
  }
  return modRows.value.filter(
    (r) => r.status === 'skipped_fast' || r.status === 'keep_original' || r.status === 'skipped'
  )
})

const startButtonText = computed(() => {
  if (store.downloadCancelled || counts.value.attention > 0) {
    return '继续下载未完成项'
  }
  if (store.downloadReport) {
    return '重新校验 / 补全下载'
  }
  return '开始下载 Mod'
})

const statusMeta: Record<
  ModDownloadStatus,
  { label: string; type: 'success' | 'primary' | 'warning' | 'danger' | 'info' }
> = {
  downloaded: { label: '已下载', type: 'success' },
  downloading: { label: '下载中', type: 'primary' },
  pending: { label: '待下载', type: 'info' },
  cancelled: { label: '已中断', type: 'warning' },
  failed: { label: '下载失败', type: 'danger' },
  skipped_fast: { label: '极速跳过', type: 'success' },
  keep_original: { label: '保留原版', type: 'warning' },
  skipped: { label: '已跳过', type: 'info' },
}

async function startDownload() {
  store.downloadRunning = true
  store.downloadCancelling = false
  store.downloadCancelled = false
  store.downloadCurrent = 0
  store.downloadTotal = store.upgradeResult?.plans.length || 1
  store.downloadMessage = '正在初始化并发下载队列（已下载文件将自动校验并复用）...'
  store.downloadReport = null

  try {
    await desktopApi.startDownload(skipModrinth.value)
    startPollingFallback()
  } catch (err: unknown) {
    store.downloadRunning = false
    ElMessage.error((err as Error).message)
  }
}

async function cancelDownload() {
  if (!store.downloadRunning || store.downloadCancelling) return
  store.downloadCancelling = true
  store.downloadMessage = '正在中断下载，已下载完成的 Mod 将保留在本地...'
  try {
    await desktopApi.cancelDownload()
  } catch (err: unknown) {
    store.downloadCancelling = false
    ElMessage.error((err as Error).message)
  }
}

function applyItemStates(raw?: unknown) {
  if (raw && typeof raw === 'object') {
    store.downloadItemStates = raw as Record<string, ModDownloadItemState>
  }
}

function startPollingFallback() {
  stopPollingFallback()
  pollTimer = window.setInterval(async () => {
    try {
      const state = await desktopApi.getTaskState()
      applyItemStates(state.item_states)
      if (!state.running && state.stage === 'done') {
        store.downloadRunning = false
        store.downloadCancelling = false
        store.downloadCancelled = false
        store.downloadReport = state.report as DownloadReport
        store.downloadMessage = state.message || '下载与校验完成'
        stopPollingFallback()
      } else if (!state.running && state.stage === 'cancelled') {
        store.downloadRunning = false
        store.downloadCancelling = false
        store.downloadCancelled = true
        store.downloadReport = state.report as DownloadReport
        store.downloadMessage = state.message || '下载已中断，已完成的文件已保留'
        stopPollingFallback()
      } else if (!state.running && state.stage === 'error') {
        store.downloadRunning = false
        store.downloadCancelling = false
        stopPollingFallback()
        ElMessage.error(state.error || '下载任务出错')
      } else {
        store.downloadCurrent = state.current
        store.downloadTotal = state.total
        store.downloadMessage = state.message
      }
    } catch {
      // ignore
    }
  }, 500)
}

function stopPollingFallback() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(() => {
  window.__mcUpdaterOnProgress = (ev) => {
    store.downloadCurrent = ev.current
    store.downloadTotal = ev.total
    store.downloadMessage = ev.message
    if (ev.detail?.item_states) {
      applyItemStates(ev.detail.item_states)
    }
    if (ev.stage === 'done') {
      store.downloadRunning = false
      store.downloadCancelling = false
      store.downloadCancelled = false
      if (ev.detail?.report) {
        store.downloadReport = ev.detail.report as DownloadReport
      }
      stopPollingFallback()
      ElMessage.success('Mod 下载与哈希校验全部完成')
    } else if (ev.stage === 'cancelled') {
      store.downloadRunning = false
      store.downloadCancelling = false
      store.downloadCancelled = true
      if (ev.detail?.report) {
        store.downloadReport = ev.detail.report as DownloadReport
      }
      stopPollingFallback()
      ElMessage.warning(ev.message || '下载已中断，已下载完成的 Mod 已保留')
    } else if (ev.stage === 'error') {
      store.downloadRunning = false
      store.downloadCancelling = false
      stopPollingFallback()
      ElMessage.error(ev.message)
    }
  }
})

onUnmounted(() => {
  window.__mcUpdaterOnProgress = undefined
  stopPollingFallback()
})
</script>

<template>
  <div class="view-wrap">
    <section class="solid-card dl-card">
      <div class="dl-head">
        <div>
          <div class="section-title">1. 并发下载与哈希校验</div>
          <div class="section-sub">
            使用 {{ store.settings.concurrency }} 线程并发流式下载，支持随时中断并保留已下载 Mod，下次继续自动复用校验
          </div>
        </div>
        <div class="dl-controls">
          <el-checkbox v-model="skipModrinth" :disabled="store.downloadRunning">
            极速模式（Modrinth 链接仅写入清单，跳过本地下载）
          </el-checkbox>
          <el-button
            v-if="store.downloadRunning"
            type="danger"
            size="large"
            plain
            :loading="store.downloadCancelling"
            @click="cancelDownload"
          >
            <Square :size="15" style="margin-right: 6px" />
            {{ store.downloadCancelling ? '正在中断...' : '中断下载' }}
          </el-button>
          <el-button
            type="primary"
            size="large"
            :loading="store.downloadRunning"
            @click="startDownload"
          >
            <DownloadCloud :size="16" style="margin-right: 6px" />
            {{ startButtonText }}
          </el-button>
        </div>
      </div>

      <div v-if="store.downloadRunning || store.downloadReport || store.downloadCancelled" class="progress-box">
        <el-progress
          :percentage="store.downloadReport && !store.downloadCancelled ? 100 : percent"
          :status="store.downloadCancelled ? 'warning' : store.downloadReport ? 'success' : undefined"
          :stroke-width="12"
        />
        <div class="progress-text">
          <span>{{ store.downloadMessage }}</span>
          <span v-if="store.downloadReport" class="done-badge" :class="{ warn: store.downloadCancelled }">
            <PauseCircle v-if="store.downloadCancelled" :size="15" />
            <CheckCircle2 v-else :size="15" />
            已保留落地 {{ Object.keys(store.downloadReport.downloaded_files).length }} 个
            <template v-if="counts.attention > 0"> · 未完成/失败 {{ counts.attention }} 个</template>
          </span>
        </div>
      </div>
    </section>

    <div class="mid-grid">
      <section class="solid-card mods-card">
        <div class="mods-head">
          <div>
            <div class="section-title">2. Mod 下载状态明细（共 {{ counts.total }} 个）</div>
            <div class="section-sub">实时展示每个 Mod 是否已下载到本地或跳过</div>
          </div>
          <div class="filter-pills">
            <button
              class="filter-pill"
              :class="{ active: modFilter === 'all' }"
              @click="modFilter = 'all'"
            >
              全部 ({{ counts.total }})
            </button>
            <button
              class="filter-pill"
              :class="{ active: modFilter === 'downloaded' }"
              @click="modFilter = 'downloaded'"
            >
              已下载 ({{ counts.downloaded }})
            </button>
            <button
              class="filter-pill"
              :class="{ active: modFilter === 'active' }"
              @click="modFilter = 'active'"
            >
              待/下载中 ({{ counts.active }})
            </button>
            <button
              class="filter-pill"
              :class="{ active: modFilter === 'attention' }"
              @click="modFilter = 'attention'"
            >
              中断/失败 ({{ counts.attention }})
            </button>
            <button
              class="filter-pill"
              :class="{ active: modFilter === 'ignored' }"
              @click="modFilter = 'ignored'"
            >
              无需下载 ({{ counts.ignored }})
            </button>
          </div>
        </div>

        <div class="table-wrap">
          <el-table :data="filteredRows" height="100%" style="width: 100%" size="small">
            <el-table-column label="Mod / 目标文件" min-width="220">
              <template #default="{ row }">
                <div class="mod-name">{{ row.name }}</div>
                <div class="mod-file" :title="row.filename">{{ row.filename }}</div>
              </template>
            </el-table-column>

            <el-table-column label="来源" width="96" align="center">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">
                  {{ row.platform === 'modrinth' ? 'Modrinth' : row.platform === 'curseforge' ? 'CurseForge' : '本地' }}
                </el-tag>
              </template>
            </el-table-column>

            <el-table-column label="下载状态" width="130" align="center">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="statusMeta[row.status as ModDownloadStatus].type"
                  effect="dark"
                >
                  <span class="status-inner">
                    <CheckCircle2 v-if="row.status === 'downloaded'" :size="12" />
                    <Loader2 v-else-if="row.status === 'downloading'" :size="12" class="spin-icon" />
                    <Clock v-else-if="row.status === 'pending'" :size="12" />
                    <PauseCircle v-else-if="row.status === 'cancelled'" :size="12" />
                    <XCircle v-else-if="row.status === 'failed'" :size="12" />
                    <Zap v-else-if="row.status === 'skipped_fast'" :size="12" />
                    {{ statusMeta[row.status as ModDownloadStatus].label }}
                  </span>
                </el-tag>
              </template>
            </el-table-column>

            <el-table-column label="大小 / 详情" min-width="140">
              <template #default="{ row }">
                <div v-if="row.status === 'downloading'" class="size-text">
                  {{ formatBytes(row.downloadedBytes) }}
                  <template v-if="row.totalBytes > 0"> / {{ formatBytes(row.totalBytes) }}</template>
                </div>
                <div v-else-if="row.status === 'failed' && row.error" class="err-text" :title="row.error">
                  {{ row.error }}
                </div>
                <div v-else-if="row.totalBytes > 0" class="size-text">
                  {{ formatBytes(row.totalBytes) }}
                </div>
                <div v-else class="size-text">-</div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </section>

      <section class="solid-card cfg-card">
        <div class="cfg-head">
          <div>
            <div class="section-title">3. 勾选保留的原整合包配置文件</div>
            <div class="section-sub">
              勾选的文件将打包进新整合包的 <code>overrides/</code>，也可在下一步单独导出原配置备份
            </div>
          </div>
        </div>

        <div class="cfg-list">
          <div
            v-for="item in store.packResult?.config_items || []"
            :key="item.rel_path"
            class="cfg-item"
            @click="item.selected = !item.selected"
          >
            <el-checkbox v-model="item.selected" @click.stop />
            <div class="cfg-info">
              <div class="cfg-label">{{ item.label }}</div>
              <div class="cfg-meta">{{ item.file_count }} 个文件 · {{ formatBytes(item.size_bytes) }}</div>
            </div>
          </div>
          <div v-if="(store.packResult?.config_items || []).length === 0" class="empty-cfg">
            未在原整合包中扫描到可保留的配置文件目录
          </div>
        </div>
      </section>
    </div>

    <footer class="bottom-nav">
      <el-button :disabled="store.downloadRunning" @click="store.step = 1">
        <ArrowLeft :size="15" style="margin-right: 6px" />
        返回上一步
      </el-button>
      <el-button type="primary" size="large" :disabled="store.downloadRunning" @click="store.step = 3">
        下一步：导出 PCL2 整合包
        <ArrowRight :size="16" style="margin-left: 6px" />
      </el-button>
    </footer>
  </div>
</template>

<style scoped>
.view-wrap {
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 100%;
  min-height: 0;
}

.dl-card {
  padding: 16px 20px;
  flex-shrink: 0;
}

.dl-head,
.cfg-head,
.mods-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.dl-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.section-title {
  font-size: 15px;
  font-weight: 700;
}

.section-sub {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 3px;
}

.progress-box {
  margin-top: 12px;
}

.progress-text {
  margin-top: 8px;
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-secondary);
}

.done-badge {
  color: #34d399;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.done-badge.warn {
  color: #fbbf24;
}

.mid-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 1.75fr 1fr;
  gap: 14px;
}

.mods-card,
.cfg-card {
  min-height: 0;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.filter-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.filter-pill {
  border: 1px solid var(--border-subtle);
  background: rgba(9, 13, 22, 0.5);
  color: var(--text-secondary);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.filter-pill:hover {
  color: var(--text-primary);
  border-color: rgba(52, 211, 153, 0.45);
}

.filter-pill.active {
  background: rgba(16, 185, 129, 0.18);
  color: #34d399;
  border-color: rgba(52, 211, 153, 0.5);
}

.table-wrap {
  flex: 1;
  min-height: 0;
}

.mod-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.3;
}

.mod-file {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status-inner {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.spin-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.size-text {
  font-size: 12px;
  color: var(--text-secondary);
}

.err-text {
  font-size: 12px;
  color: #f87171;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cfg-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-content: start;
}

.cfg-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(9, 13, 22, 0.5);
  border: 1px solid var(--border-subtle);
  cursor: pointer;
}

.cfg-item:hover {
  border-color: rgba(52, 211, 153, 0.45);
}

.cfg-label {
  font-size: 13px;
  font-weight: 600;
}

.cfg-meta {
  font-size: 11px;
  color: var(--text-secondary);
}

.empty-cfg {
  color: var(--text-secondary);
  font-size: 13px;
}

.bottom-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
</style>
