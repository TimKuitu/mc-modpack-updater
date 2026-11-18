import type {
  AppSettings,
  ExportResult,
  GameVersionOption,
  ModDownloadItemState,
  PackAnalysisResult,
  ProgressEvent,
  UpgradeAnalysisResult,
} from '../types/api'

interface ApiResponse<T> {
  ok: boolean
  data?: T
  error?: string
}

declare global {
  interface Window {
    pywebview?: {
      api: Record<string, (...args: unknown[]) => Promise<ApiResponse<unknown>>>
    }
    __mcUpdaterOnProgress?: (ev: ProgressEvent) => void
    __mcUpdaterOnFileDrop?: (path: string) => void
  }
}

async function callApi<T>(method: string, ...args: unknown[]): Promise<T> {
  if (!window.pywebview?.api) {
    throw new Error('当前未运行在桌面容器环境中（缺少 pywebview 桥接）')
  }
  const res = (await window.pywebview.api[method](...args)) as ApiResponse<T>
  if (!res || !res.ok) {
    throw new Error(res?.error || `调用 ${method} 失败`)
  }
  return res.data as T
}

export function waitForPywebviewReady(): Promise<boolean> {
  if (window.pywebview?.api) return Promise.resolve(true)
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(Boolean(window.pywebview?.api)), 1200)
    window.addEventListener(
      'pywebviewready',
      () => {
        clearTimeout(timer)
        resolve(true)
      },
      { once: true }
    )
  })
}

export const desktopApi = {
  getSettings: () => callApi<AppSettings>('get_settings'),
  saveSettings: (s: AppSettings) => callApi<AppSettings>('save_settings', s),
  pickPackFile: () => callApi<string | null>('pick_pack_file'),
  pickPcl2Folder: () => callApi<string | null>('pick_pcl2_folder'),
  pickSaveMrpack: (defaultName: string) => callApi<string | null>('pick_save_mrpack', defaultName),
  pickSaveBackupZip: (defaultName: string) =>
    callApi<string | null>('pick_save_backup_zip', defaultName),
  analyzeInput: (path: string, allowShared = false) =>
    callApi<PackAnalysisResult>('analyze_input', path, allowShared),
  getGameVersions: (forceRefresh = false) =>
    callApi<GameVersionOption[]>('get_game_versions', forceRefresh),
  getRecommendedLoader: (mcVersion: string, loader: string) =>
    callApi<string>('get_recommended_loader', mcVersion, loader),
  checkUpgrades: (
    targetMc: string,
    targetLoader: string,
    targetLoaderVersion: string,
    preferBeta: boolean
  ) =>
    callApi<UpgradeAnalysisResult>(
      'check_upgrades',
      targetMc,
      targetLoader,
      targetLoaderVersion,
      preferBeta
    ),
  updatePlanAction: (
    uid: string,
    action: string,
    candidateVersionId?: string | null,
    manualJarPath?: string | null
  ) =>
    callApi<UpgradeAnalysisResult>(
      'update_plan_action',
      uid,
      action,
      candidateVersionId ?? null,
      manualJarPath ?? null
    ),
  pickManualJarForMod: (uid: string) =>
    callApi<UpgradeAnalysisResult | null>('pick_manual_jar_for_mod', uid),
  openUrlInBrowser: (url: string) => callApi<boolean>('open_url_in_browser', url),
  startDownload: (skipModrinth: boolean) =>
    callApi<{ task_id: string }>('start_download', skipModrinth),
  cancelDownload: () => callApi<boolean>('cancel_download'),
  getTaskState: () =>
    callApi<{
      running: boolean
      stage: string
      current: number
      total: number
      message: string
      error: string
      report?: unknown
      item_states?: Record<string, ModDownloadItemState>
    }>('get_task_state'),
  exportMrpack: (
    outputPath: string,
    packName: string,
    versionId: string,
    selectedConfigPaths: string[]
  ) =>
    callApi<ExportResult>('export_mrpack', outputPath, packName, versionId, selectedConfigPaths),
  exportBackupZip: (outputPath: string, selectedConfigPaths: string[]) =>
    callApi<{ output_path: string; file_size: number; file_count: number }>(
      'export_backup_zip',
      outputPath,
      selectedConfigPaths
    ),
  revealInExplorer: (path: string) => callApi<boolean>('reveal_in_explorer', path),
}
