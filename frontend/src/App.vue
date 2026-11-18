<script setup lang="ts">
import { onMounted } from 'vue'
import { waitForPywebviewReady } from './bridge/pywebview'
import { useUpdaterStore } from './stores/updater'
import StepHeader from './components/StepHeader.vue'
import ImportView from './components/ImportView.vue'
import AnalyzeView from './components/AnalyzeView.vue'
import DownloadConfigView from './components/DownloadConfigView.vue'
import ExportView from './components/ExportView.vue'
import SettingsDrawer from './components/SettingsDrawer.vue'

const store = useUpdaterStore()

onMounted(async () => {
  await waitForPywebviewReady()
  await store.initSettings()
})
</script>

<template>
  <div class="app-backdrop"></div>
  <div class="app-shell">
    <StepHeader />
    <main class="main-stage" v-loading="store.busy" :element-loading-text="store.busyText">
      <ImportView v-if="store.step === 0" />
      <AnalyzeView v-else-if="store.step === 1" />
      <DownloadConfigView v-else-if="store.step === 2" />
      <ExportView v-else />
    </main>
    <SettingsDrawer />
  </div>
</template>

<style scoped>
.app-shell {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.main-stage {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>
