<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { PackageCheck, Archive, FolderSearch, ArrowLeft } from 'lucide-vue-next'
import { desktopApi } from '../bridge/pywebview'
import { useUpdaterStore } from '../stores/updater'

const store = useUpdaterStore()
const packName = ref(
  `${store.packResult?.pack_name || '我的整合包'}-${store.targetMcVersion || '26.1'}`
)
const versionId = ref('2.0.0')

async function doExportMrpack() {
  const defaultFile = `${packName.value}.mrpack`
  try {
    const outPath = await desktopApi.pickSaveMrpack(defaultFile)
    if (!outPath) return

    store.busy = true
    store.busyText = '正在打包标准 PCL2 整合包 (.mrpack) 并执行结构自检...'
    const res = await desktopApi.exportMrpack(
      outPath,
      packName.value,
      versionId.value,
      store.selectedConfigPaths
    )
    store.exportResult = res
    store.busy = false

    if (res.has_non_redistributable_cf) {
      await ElMessageBox.alert(
        '导出成功！\n\n提示：本次导出的压缩包内包含部分 CurseForge 禁止第三方分发的 Mod 实体文件（已放入 overrides/mods/）。仅限个人本地游玩，请勿公开分发此压缩包以免违反作者授权。',
        '导出的整合包内含非公开分发组件',
        { type: 'warning', confirmButtonText: '我知道了' }
      )
    } else {
      ElMessage.success('已生成可直接拖入 PCL2 安装的 .mrpack 整合包！')
    }
  } catch (err: unknown) {
    ElMessage.error((err as Error).message)
  } finally {
    store.busy = false
  }
}

async function doExportBackup() {
  try {
    const outPath = await desktopApi.pickSaveBackupZip(
      `原配置备份-${store.packResult?.pack_name || 'pack'}.zip`
    )
    if (!outPath) return
    store.busy = true
    store.busyText = '正在导出原整合包配置备份...'
    store.backupResult = await desktopApi.exportBackupZip(outPath, store.selectedConfigPaths)
    ElMessage.success(`配置备份导出完成，共 ${store.backupResult.file_count} 个文件`)
  } catch (err: unknown) {
    ElMessage.error((err as Error).message)
  } finally {
    store.busy = false
  }
}

async function reveal(path: string) {
  await desktopApi.revealInExplorer(path)
}
</script>

<template>
  <div class="view-wrap">
    <section class="solid-card export-card">
      <div class="section-title">导出升级后整合包（兼容 PCL2 / PCL-CE 直接拖入安装）</div>
      <div class="form-grid">
        <div class="form-item">
          <label>整合包名称</label>
          <el-input v-model="packName" />
        </div>
        <div class="form-item">
          <label>版本号</label>
          <el-input v-model="versionId" style="width: 160px" />
        </div>
      </div>

      <div class="btn-row">
        <el-button type="primary" size="large" @click="doExportMrpack">
          <PackageCheck :size="17" style="margin-right: 6px" />
          导出 PCL2 整合包 (.mrpack)
        </el-button>
        <el-button size="large" @click="doExportBackup">
          <Archive :size="17" style="margin-right: 6px" />
          单独导出原配置备份 (.zip)
        </el-button>
      </div>

      <div v-if="store.exportResult" class="result-box">
        <div class="result-title">整合包导出成功</div>
        <div class="result-line">输出路径：{{ store.exportResult.output_path }}</div>
        <div class="result-line">
          在线清单 Mod：{{ store.exportResult.included_mods_in_index }} 个 ｜ 本地 overrides Mod：
          {{ store.exportResult.included_mods_in_overrides }} 个 ｜ 配置文件：
          {{ store.exportResult.included_config_files }} 个
        </div>
        <el-button size="small" plain @click="reveal(store.exportResult.output_path)">
          <FolderSearch :size="14" style="margin-right: 5px" />
          在资源管理器中定位
        </el-button>
      </div>

      <div v-if="store.backupResult" class="result-box">
        <div class="result-title">原配置备份导出成功</div>
        <div class="result-line">
          输出路径：{{ store.backupResult.output_path }}（共 {{ store.backupResult.file_count }} 个文件）
        </div>
        <el-button size="small" plain @click="reveal(store.backupResult.output_path)">
          <FolderSearch :size="14" style="margin-right: 5px" />
          在资源管理器中定位
        </el-button>
      </div>
    </section>

    <section class="solid-card tips-card">
      <div class="section-title">PCL2 导入使用提示</div>
      <ul class="tips-list">
        <li>直接将生成的 <code>.mrpack</code> 文件拖入 PCL2 / PCL-CE 窗口，按提示输入版本名称即可自动安装。</li>
        <li>若拖入 PCL2 无反应，通常是因为 PCL2 以「管理员身份」运行而资源管理器未提权（Windows UIPI 限制）；请取消 PCL2 管理员运行，或在 PCL2 内使用「下载 → 安装整合包 → 选择本地文件」。</li>
        <li>跨大版本升级后若首次启动报错，请重点核对少数跳过/保留原版的 Mod 或旧版 <code>config/</code> 配置文件兼容性。</li>
      </ul>
    </section>

    <footer class="bottom-nav">
      <el-button @click="store.step = 2">
        <ArrowLeft :size="15" style="margin-right: 6px" />
        返回上一步
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
}

.export-card,
.tips-card {
  padding: 20px 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
}

.form-grid {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 280px;
}

.form-item label {
  font-size: 12px;
  color: var(--text-secondary);
}

.btn-row {
  display: flex;
  gap: 12px;
}

.result-box {
  padding: 14px 16px;
  border-radius: 10px;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(52, 211, 153, 0.35);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.result-title {
  font-weight: 700;
  color: #34d399;
}

.result-line {
  font-size: 12px;
  color: var(--text-primary);
}

.tips-list {
  margin: 0;
  padding-left: 18px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.75;
}

.tips-list code {
  background: rgba(255, 255, 255, 0.08);
  padding: 1px 5px;
  border-radius: 4px;
  color: #e2e8f0;
}

.bottom-nav {
  margin-top: auto;
}
</style>
