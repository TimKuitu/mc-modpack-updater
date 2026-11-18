export type LoaderType = 'fabric' | 'neoforge' | 'forge' | 'quilt' | 'unknown'
export type SourceType =
  | 'pcl2_dir'
  | 'mrpack'
  | 'curseforge_zip'
  | 'mcbbs_zip'
  | 'multimc_zip'
  | 'generic_zip'
export type ModPlatform = 'modrinth' | 'curseforge' | 'local'
export type CompatStatus =
  | 'upgradable'
  | 'beta_only'
  | 'manual_required'
  | 'unavailable'
  | 'keep_original'
  | 'skipped'

export interface JarMetadata {
  mod_id: string
  name: string
  version: string
  description: string
  authors: string[]
  icon_base64?: string | null
  source_format: string
}

export interface ModEntry {
  uid: string
  filename: string
  local_path?: string | null
  disabled: boolean
  jar_meta?: JarMetadata | null
  platform: ModPlatform
  modrinth_project_id?: string | null
  modrinth_version_id?: string | null
  curseforge_mod_id?: number | null
  curseforge_file_id?: number | null
  slug?: string | null
  display_name: string
  current_version: string
  icon_url?: string | null
  identified_by: string
  is_library: boolean
}

export interface CandidateVersion {
  platform: ModPlatform
  project_id: string
  version_id: string
  version_number: string
  name: string
  release_type: 'release' | 'beta' | 'alpha'
  game_versions: string[]
  loaders: LoaderType[]
  download_url?: string | null
  filename: string
  file_size: number
  allow_distribution: boolean
  website_url?: string | null
}

export interface ModUpgradePlan {
  uid: string
  mod: ModEntry
  status: CompatStatus
  selected_candidate?: CandidateVersion | null
  candidates: CandidateVersion[]
  user_action: 'auto' | 'select_candidate' | 'keep_original' | 'skip' | 'manual_jar'
  manual_jar_path?: string | null
  manual_verified: boolean
  is_auto_dependency: boolean
  required_by: string[]
  conflicts_with: string[]
  note: string
}

export interface ConfigItem {
  rel_path: string
  label: string
  category: string
  file_count: number
  size_bytes: number
  selected: boolean
}

export interface PackAnalysisResult {
  source_path: string
  source_type: SourceType
  pack_name: string
  mc_version: string
  loader: LoaderType
  loader_version: string
  isolation_mode: 'isolated' | 'shared_confirmed' | 'archive' | 'unknown'
  needs_shared_confirmation: boolean
  shared_mods_path?: string | null
  mods: ModEntry[]
  config_items: ConfigItem[]
  warnings: string[]
}

export interface UpgradeAnalysisResult {
  target_mc_version: string
  target_loader: LoaderType
  target_loader_version: string
  plans: ModUpgradePlan[]
  summary_counts: Record<string, number>
  dependency_warnings: string[]
  conflict_warnings: string[]
}

export interface GameVersionOption {
  version: string
  version_type: 'release' | 'snapshot' | 'alpha' | 'beta'
  is_year_based: boolean
  date: string
}

export interface AppSettings {
  curseforge_api_key: string
  use_mcim_mirror: boolean
  proxy_mode: 'system' | 'custom' | 'direct'
  custom_proxy_url: string
  concurrency: number
  include_beta_by_default: boolean
  skip_modrinth_download_for_mrpack: boolean
}

export interface DownloadReport {
  downloaded_files: Record<string, string>
  failed_items: Array<{ uid: string; name: string; error: string }>
  skipped_modrinth_count: number
}

export interface ExportResult {
  output_path: string
  file_size: number
  included_mods_in_index: number
  included_mods_in_overrides: number
  included_config_files: number
  has_non_redistributable_cf: boolean
  warnings: string[]
}

export interface ProgressEvent {
  task_id: string
  stage: string
  current: number
  total: number
  message: string
  detail?: Record<string, unknown>
}
