<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { DownloadCloud, ArrowLeft, ArrowRight, CheckCircle2 } from 'lucide-vue-next'
import { desktopApi } from '../bridge/pywebview'
import { useUpdaterStore } from '../stores/updater'
import type { DownloadReport } from '../types/api'

const store = useUpdaterStore()
const skipModrinth = ref(store.settings.skip_modrinth_download_for_mrpack)
let pollTimer: number | null = null

const percent = computed(() => {
  if (!store.downloadTotal) return 0
  return Math.min(100, Math.round((store.downloadCurrent / store.downloadTotal) * 100))
})

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

async function startDownload() {
  store.downloadRunning = true
  store.downloadCurrent = 0
  store.downloadTotal = store.upgradeResult?.plans.length || 1
  store.downloadMessage = '正在初始化并发下载队列...'
  store.downloadReport = null

  try {
    await desktopApi.startDownload(skipModrinth.value)
    startPollingFallback()
  } catch (err: unknown) {
    store.downloadRunning = false
    ElMessage.error((err as Error).message)
  }
}

function startPollingFallback() {
  stopPollingFallback()
  pollTimer = window.setInterval(async () => {
    try {
      const state = await desktopApi.getTaskState()
      if (!state.running && state.stage === 'done') {
        store.downloadRunning = false
        store.downloadReport = state.report as DownloadReport
        stopPollingFallback()
      } else if (!state.running && state.stage === 'error') {
        store.downloadRunning = false
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
  }, 800)
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
    if (ev.stage === 'done') {
      store.downloadRunning = false
      if (ev.detail?.report) {
        store.downloadReport = ev.detail.report as DownloadReport
      }
      stopPollingFallback()
      ElMessage.success('Mod 下载与哈希校验全部完成')
    } else if (ev.stage === 'error') {
      store.downloadRunning = false
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
            使用 {{ store.settings.concurrency }} 线程并发流式下载，并自动校验 SHA-512 / SHA-1 防损坏
          </div>
        </div>
        <div class="dl-controls">
          <el-checkbox v-model="skipModrinth">
            极速模式（Modrinth 链接仅写入清单，跳过本地下载）
          </el-checkbox>
          <el-button
            type="primary"
            size="large"
            :loading="store.downloadRunning"
            @click="startDownload"
          >
            <DownloadCloud :size="16" style="margin-right: 6px" />
            {{ store.downloadReport ? '重新下载校验' : '开始下载 Mod' }}
          </el-button>
        </div>
      </div>

      <div v-if="store.downloadRunning || store.downloadReport" class="progress-box">
        <el-progress
          :percentage="store.downloadReport ? 100 : percent"
          :status="store.downloadReport ? 'success' : undefined"
          :stroke-width="12"
        />
        <div class="progress-text">
          <span>{{ store.downloadMessage }}</span>
          <span v-if="store.downloadReport" class="done-badge">
            <CheckCircle2 :size="15" />
            已落地 {{ Object.keys(store.downloadReport.downloaded_files).length }} 个，失败 {{ store.downloadReport.failed_items.length }} 个
          </span>
        </div>
      </div>
    </section>

    <section class="solid-card cfg-card">
      <div class="cfg-head">
        <div>
          <div class="section-title">2. 勾选保留的原整合包配置文件</div>
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

    <footer class="bottom-nav">
      <el-button @click="store.step = 1">
        <ArrowLeft :size="15" style="margin-right: 6px" />
        返回上一步
      </el-button>
      <el-button type="primary" size="large" @click="store.step = 3">
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
  padding: 18px 20px;
  flex-shrink: 0;
}

.dl-head,
.cfg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.dl-controls {
  display: flex;
  align-items: center;
  gap: 14px;
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
  margin-top: 14px;
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

.cfg-card {
  flex: 1;
  min-height: 0;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cfg-list {
  flex: 1;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
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
