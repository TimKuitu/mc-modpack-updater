<script setup lang="ts">
import { reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { desktopApi } from '../bridge/pywebview'
import { useUpdaterStore } from '../stores/updater'

const store = useUpdaterStore()
const form = reactive({ ...store.settings })

watch(
  () => store.settingsOpen,
  (open) => {
    if (open) Object.assign(form, store.settings)
  }
)

async function save() {
  try {
    await store.saveSettings({ ...form })
    store.settingsOpen = false
    ElMessage.success('设置已保存（API Key 已加密存储于本地）')
  } catch (err: unknown) {
    ElMessage.error((err as Error).message)
  }
}
</script>

<template>
  <el-drawer v-model="store.settingsOpen" title="高级设置" size="420px">
    <el-form label-position="top">
      <el-form-item label="CurseForge API Key（选填，用于 CurseForge 识别与更新）">
        <el-input
          v-model="form.curseforge_api_key"
          type="password"
          show-password
          placeholder="填写 $2a$10$... 密钥"
        />
      </el-form-item>

      <el-form-item label="国内网络加速">
        <el-switch v-model="form.use_mcim_mirror" active-text="启用 MCIM 镜像加速（推荐）" />
      </el-form-item>

      <el-form-item label="网络代理模式">
        <el-radio-group v-model="form.proxy_mode">
          <el-radio value="system">跟随系统代理</el-radio>
          <el-radio value="custom">自定义代理</el-radio>
          <el-radio value="direct">直连</el-radio>
        </el-radio-group>
      </el-form-item>

      <el-form-item v-if="form.proxy_mode === 'custom'" label="自定义代理地址">
        <el-input
          v-model="form.custom_proxy_url"
          placeholder="例如 http://127.0.0.1:7890 或 socks5://127.0.0.1:7890"
        />
      </el-form-item>

      <el-form-item label="并发下载线程数">
        <el-slider v-model="form.concurrency" :min="1" :max="12" show-input />
      </el-form-item>

      <el-form-item label="版本策略">
        <el-checkbox v-model="form.include_beta_by_default">
          存在正式版时仍优先提示测试版更新
        </el-checkbox>
      </el-form-item>

      <el-form-item>
        <el-button type="primary" style="width: 100%" @click="save">保存设置</el-button>
      </el-form-item>
    </el-form>
  </el-drawer>
</template>
