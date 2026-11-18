<script setup lang="ts">
import { Settings, Package, SearchCheck, DownloadCloud, PackageCheck } from 'lucide-vue-next'
import { useUpdaterStore } from '../stores/updater'

const store = useUpdaterStore()

const steps = [
  { idx: 0 as const, label: '1. 导入整合包', icon: Package },
  { idx: 1 as const, label: '2. 版本兼容性', icon: SearchCheck },
  { idx: 2 as const, label: '3. 下载与配置', icon: DownloadCloud },
  { idx: 3 as const, label: '4. 导出 PCL2 包', icon: PackageCheck },
]

function canJump(idx: number) {
  if (idx === 0) return true
  if (idx === 1) return Boolean(store.packResult && !store.packResult.needs_shared_confirmation)
  if (idx === 2) return Boolean(store.upgradeResult)
  if (idx === 3) return Boolean(store.upgradeResult)
  return false
}
</script>

<template>
  <header class="glass-panel header-bar">
    <div class="brand">
      <div class="brand-badge">MC</div>
      <div>
        <div class="brand-title">MC 整合包升级助手</div>
        <div class="brand-sub">PCL2 / PCL-CE · 26.1+ 年份制适配</div>
      </div>
    </div>

    <nav class="step-pills">
      <button
        v-for="s in steps"
        :key="s.idx"
        class="step-pill"
        :class="{ active: store.step === s.idx, disabled: !canJump(s.idx) }"
        :disabled="!canJump(s.idx)"
        @click="store.step = s.idx"
      >
        <component :is="s.icon" :size="15" />
        <span>{{ s.label }}</span>
      </button>
    </nav>

    <div class="header-actions">
      <el-tag v-if="store.settings.use_mcim_mirror" size="small" type="success" effect="dark">
        MCIM 加速中
      </el-tag>
      <el-button circle plain @click="store.settingsOpen = true" title="设置">
        <Settings :size="16" />
      </el-button>
    </div>
  </header>
</template>

<style scoped>
.header-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  gap: 16px;
  flex-shrink: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-badge {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, #10b981, #0ea5e9);
  display: grid;
  place-items: center;
  font-weight: 800;
  font-size: 14px;
  color: #06281e;
  box-shadow: 0 4px 14px rgba(16, 185, 129, 0.35);
}

.brand-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.brand-sub {
  font-size: 11px;
  color: var(--text-secondary);
}

.step-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(9, 13, 22, 0.55);
  padding: 4px;
  border-radius: 12px;
  border: 1px solid var(--border-subtle);
}

.step-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 13px;
  border-radius: 9px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.18s ease;
}

.step-pill:hover:not(.disabled) {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.05);
}

.step-pill.active {
  background: rgba(16, 185, 129, 0.18);
  color: #34d399;
  box-shadow: inset 0 0 0 1px rgba(52, 211, 153, 0.35);
}

.step-pill.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
