import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { desktopApi } from '../bridge/pywebview'
import type {
  AppSettings,
  DownloadReport,
  ExportResult,
  GameVersionOption,
  LoaderType,
  ModDownloadItemState,
  PackAnalysisResult,
  UpgradeAnalysisResult,
} from '../types/api'

export const useUpdaterStore = defineStore('updater', () => {
  const step = ref<0 | 1 | 2 | 3>(0)
  const settingsOpen = ref(false)
  const busy = ref(false)
  const busyText = ref('')

  const settings = ref<AppSettings>({
    curseforge_api_key: '',
    use_mcim_mirror: true,
    proxy_mode: 'system',
    custom_proxy_url: '',
    concurrency: 6,
    include_beta_by_default: false,
    skip_modrinth_download_for_mrpack: false,
  })

  const inputPath = ref('')
  const packResult = ref<PackAnalysisResult | null>(null)

  const gameVersions = ref<GameVersionOption[]>([])
  const targetMcVersion = ref('26.1')
  const targetLoader = ref<LoaderType>('fabric')
  const targetLoaderVersion = ref('')
  const upgradeResult = ref<UpgradeAnalysisResult | null>(null)

  const downloadRunning = ref(false)
  const downloadCancelling = ref(false)
  const downloadCancelled = ref(false)
  const downloadCurrent = ref(0)
  const downloadTotal = ref(0)
  const downloadMessage = ref('')
  const downloadReport = ref<DownloadReport | null>(null)
  const downloadItemStates = ref<Record<string, ModDownloadItemState>>({})

  const exportResult = ref<ExportResult | null>(null)
  const backupResult = ref<{ output_path: string; file_size: number; file_count: number } | null>(
    null
  )

  const selectedConfigPaths = computed(() => {
    if (!packResult.value) return []
    return packResult.value.config_items.filter((c) => c.selected).map((c) => c.rel_path)
  })

  async function initSettings() {
    try {
      settings.value = await desktopApi.getSettings()
    } catch {
      // ignore in browser preview
    }
  }

  async function saveSettings(next: AppSettings) {
    settings.value = await desktopApi.saveSettings(next)
  }

  async function loadGameVersions(force = false) {
    if (gameVersions.value.length > 0 && !force) return
    gameVersions.value = await desktopApi.getGameVersions(force)
    if (gameVersions.value.length > 0) {
      const firstYearRel = gameVersions.value.find(
        (v) => v.is_year_based && v.version_type === 'release'
      )
      if (firstYearRel && !targetMcVersion.value) {
        targetMcVersion.value = firstYearRel.version
      }
    }
  }

  return {
    step,
    settingsOpen,
    busy,
    busyText,
    settings,
    inputPath,
    packResult,
    gameVersions,
    targetMcVersion,
    targetLoader,
    targetLoaderVersion,
    upgradeResult,
    downloadRunning,
    downloadCancelling,
    downloadCancelled,
    downloadCurrent,
    downloadTotal,
    downloadMessage,
    downloadReport,
    downloadItemStates,
    exportResult,
    backupResult,
    selectedConfigPaths,
    initSettings,
    saveSettings,
    loadGameVersions,
  }
})
