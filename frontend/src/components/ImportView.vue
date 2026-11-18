<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderOpen, FileArchive, UploadCloud, ArrowRight, Sparkles } from 'lucide-vue-next'
import { desktopApi } from '../bridge/pywebview'
import { useUpdaterStore } from '../stores/updater'

const store = useUpdaterStore()
const isDragging = ref(false)
const searchMod = ref('')

async function runAnalyze(path: string, allowShared = false) {
  const clean = path.trim()
  if (!clean) {
    ElMessage.warning('请先选择或输入整合包路径')
    return
  }
  store.inputPath = clean
  store.busy = true
  store.busyText = '正在解析整合包并向平台批量反查 Mod 身份...'
  try {
    const res = await desktopApi.analyzeInput(clean, allowShared)
    if (res.needs_shared_confirmation) {
      store.busy = false
      await ElMessageBox.confirm(
        `未在当前实例目录检测到独立的 mods 文件夹。\n\n检测到上级共享目录：\n${res.shared_mods_path}\n\n是否改为读取 .minecraft 共享目录？（注意：非隔离目录可能混杂其他版本的 Mod）`,
        '未开启版本隔离',
        {
          confirmButtonText: '读取共享目录',
          cancelButtonText: '取消',
          type: 'warning',
        }
      )
      await runAnalyze(clean, true)
      return
    }
    store.packResult = res
    if (res.mc_version) store.targetMcVersion = res.mc_version
    if (res.loader !== 'unknown') store.targetLoader = res.loader
    ElMessage.success(`识别成功：共读取 ${res.mods.length} 个 Mod`)
  } catch (err: unknown) {
    ElMessage.error((err as Error).message || '解析失败')
  } finally {
    store.busy = false
  }
}

async function pickFile() {
  try {
    const p = await desktopApi.pickPackFile()
    if (p) await runAnalyze(p)
  } catch (err: unknown) {
    ElMessage.error((err as Error).message)
  }
}

async function pickFolder() {
  try {
    const p = await desktopApi.pickPcl2Folder()
    if (p) await runAnalyze(p)
  } catch (err: unknown) {
    ElMessage.error((err as Error).message)
  }
}

onMounted(() => {
  window.__mcUpdaterOnFileDrop = (path: string) => {
    isDragging.value = false
    if (path) runAnalyze(path)
  }
})

onUnmounted(() => {
  window.__mcUpdaterOnFileDrop = undefined
})

const filteredMods = () => {
  if (!store.packResult) return []
  const q = searchMod.value.trim().toLowerCase()
  if (!q) return store.packResult.mods
  return store.packResult.mods.filter(
    (m) =>
      m.display_name.toLowerCase().includes(q) ||
      m.filename.toLowerCase().includes(q) ||
      (m.slug || '').toLowerCase().includes(q)
  )
}

const sourceLabel: Record<string, string> = {
  pcl2_dir: 'PCL2 实例目录',
  mrpack: 'Modrinth 整合包 (.mrpack)',
  curseforge_zip: 'CurseForge 整合包',
  mcbbs_zip: 'MCBBS 整合包',
  multimc_zip: 'MultiMC / Prism 整合包',
  generic_zip: 'PCL2 懒人包 / 散装包',
}

const platformTag: Record<string, { text: string; type: 'success' | 'warning' | 'info' }> = {
  modrinth: { text: 'Modrinth', type: 'success' },
  curseforge: { text: 'CurseForge', type: 'warning' },
  local: { text: '本地元数据', type: 'info' },
}
</script>

<template>
  <div class="view-wrap">
    <section
      class="solid-card drop-zone"
      :class="{ dragging: isDragging }"
      @dragenter.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @dragover.prevent="isDragging = true"
      @drop.prevent="isDragging = false"
    >
      <div class="drop-icon">
        <UploadCloud :size="36" />
      </div>
      <div class="drop-title">拖入整合包压缩包，或选择 PCL2 版本目录</div>
      <div class="drop-desc">
        支持 <code>.mrpack</code>、CurseForge <code>.zip</code>、PCL2 导出包，以及 <code>.minecraft\versions\实例名</code> 目录
      </div>

      <div class="action-row">
        <el-button type="primary" size="large" @click="pickFile">
          <FileArchive :size="16" style="margin-right: 6px" />
          选择整合包压缩包
        </el-button>
        <el-button size="large" @click="pickFolder">
          <FolderOpen :size="16" style="margin-right: 6px" />
          选择 PCL2 版本目录
        </el-button>
      </div>

      <div class="path-input-row">
        <el-input
          v-model="store.inputPath"
          placeholder="或直接粘贴路径，例如 D:\MC\.minecraft\versions\26.1-Fabric"
          clearable
          @keyup.enter="runAnalyze(store.inputPath)"
        >
          <template #append>
            <el-button @click="runAnalyze(store.inputPath)">开始扫描</el-button>
          </template>
        </el-input>
      </div>
    </section>

    <section v-if="store.packResult && !store.packResult.needs_shared_confirmation" class="result-section">
      <div class="solid-card summary-bar">
        <div class="summary-meta">
          <div class="pack-name">{{ store.packResult.pack_name }}</div>
          <div class="pack-tags">
            <el-tag size="small" effect="dark" type="info">
              {{ sourceLabel[store.packResult.source_type] || store.packResult.source_type }}
            </el-tag>
            <el-tag size="small" effect="dark" type="success">
              MC {{ store.packResult.mc_version || '未知' }}
            </el-tag>
            <el-tag size="small" effect="dark" type="primary">
              {{ store.packResult.loader.toUpperCase() }} {{ store.packResult.loader_version }}
            </el-tag>
            <el-tag size="small" effect="plain">
              共 {{ store.packResult.mods.length }} 个 Mod
            </el-tag>
          </div>
        </div>
        <div class="summary-right">
          <el-input
            v-model="searchMod"
            placeholder="筛选 Mod..."
            clearable
            style="width: 200px"
          />
          <el-button type="primary" size="large" @click="store.step = 1">
            <Sparkles :size="16" style="margin-right: 6px" />
            下一步：检测升级版本
            <ArrowRight :size="16" style="margin-left: 6px" />
          </el-button>
        </div>
      </div>

      <div class="solid-card mod-list-card">
        <el-table :data="filteredMods()" height="100%" style="width: 100%">
          <el-table-column label="Mod" min-width="260">
            <template #default="{ row }">
              <div class="mod-cell">
                <img
                  v-if="row.icon_url || row.jar_meta?.icon_base64"
                  :src="row.icon_url || row.jar_meta?.icon_base64"
                  class="mod-icon"
                />
                <div v-else class="mod-icon-fallback">{{ (row.display_name || '?')[0] }}</div>
                <div>
                  <div class="mod-title">
                    {{ row.display_name }}
                    <el-tag v-if="row.disabled" size="small" type="danger" effect="plain">已禁用</el-tag>
                  </div>
                  <div class="mod-filename">{{ row.filename }}</div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="current_version" label="当前版本" width="160">
            <template #default="{ row }">
              <span>{{ row.current_version || row.jar_meta?.version || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="来源平台" width="130">
            <template #default="{ row }">
              <el-tag size="small" :type="platformTag[row.platform]?.type || 'info'" effect="dark">
                {{ platformTag[row.platform]?.text || row.platform }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="identified_by" label="识别方式" width="140">
            <template #default="{ row }">
              <span class="muted">{{ row.identified_by }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>
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

.drop-zone {
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  border: 1.5px dashed rgba(52, 211, 153, 0.35);
  background: rgba(16, 24, 39, 0.72);
  flex-shrink: 0;
}

.drop-zone.dragging {
  border-color: #34d399;
  background: rgba(16, 185, 129, 0.12);
}

.drop-icon {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: rgba(16, 185, 129, 0.14);
  color: #34d399;
  display: grid;
  place-items: center;
  margin-bottom: 10px;
}

.drop-title {
  font-size: 17px;
  font-weight: 700;
  margin-bottom: 6px;
}

.drop-desc {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 16px;
}

.drop-desc code {
  background: rgba(255, 255, 255, 0.08);
  padding: 2px 6px;
  border-radius: 5px;
  color: #e2e8f0;
}

.action-row {
  display: flex;
  gap: 12px;
  margin-bottom: 14px;
}

.path-input-row {
  width: 100%;
  max-width: 680px;
}

.result-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-height: 0;
}

.summary-bar {
  padding: 14px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
}

.pack-name {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 6px;
}

.pack-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.summary-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mod-list-card {
  flex: 1;
  min-height: 0;
  padding: 8px;
  overflow: hidden;
}

.mod-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mod-icon {
  width: 32px;
  height: 32px;
  border-radius: 7px;
  object-fit: cover;
  flex-shrink: 0;
}

.mod-icon-fallback {
  width: 32px;
  height: 32px;
  border-radius: 7px;
  background: rgba(56, 189, 248, 0.16);
  color: #38bdf8;
  display: grid;
  place-items: center;
  font-weight: 700;
  flex-shrink: 0;
}

.mod-title {
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.mod-filename {
  font-size: 11px;
  color: var(--text-secondary);
}

.muted {
  color: var(--text-secondary);
  font-size: 12px;
}
</style>
