export interface AuthProvider {
  provider_id: string
  provider_kind: string
  display_name: string
  enabled: boolean
  login_mode: string
  supports_password_login: boolean
  supports_refresh: boolean
  supports_bootstrap_admin: boolean
  supports_user_management: boolean
  supports_long_lived_tokens: boolean
  issuer_url?: string | null
  metadata?: Record<string, unknown>
}

export interface CurrentUser {
  principal_id: string
  principal_type: string
  project_ids: string[]
  scopes: string[]
  username?: string | null
  display_name?: string | null
  auth_source?: string | null
  auth_provider_id?: string | null
  auth_provider_kind?: string | null
  auth_credential_kind?: string | null
  auth_credential_id?: string | null
  auth_session_id?: string | null
  auth_token_id?: string | null
  auth_token_name?: string | null
  auth_mode?: string | null
}

export interface LocalAuthUser {
  user_id: string
  provider_kind: string
  username: string
  display_name: string
  principal_type: string
  project_ids: string[]
  scopes: string[]
  is_active: boolean
  created_at: string
  updated_at: string
  last_login_at?: string | null
  metadata?: Record<string, unknown>
}

export interface SystemCapabilities {
  project_bootstrap_enabled?: boolean
  dataset_import?: {
    implemented_task_types?: string[]
    format_types_by_task_type?: Record<string, string[]>
  }
  dataset_export?: {
    implemented_formats?: string[]
    default_format?: string
    format_types_by_task_type?: Record<string, string[]>
  }
  project_summary_topics?: string[]
  platform_model_types_by_task_type?: Record<string, string[]>
  [key: string]: unknown
}

export interface SystemBootstrapResponse {
  auth_mode: string
  bearer_auth_enabled: boolean
  websocket_query_token_enabled: boolean
  current_user: CurrentUser | null
  providers: AuthProvider[]
  visible_projects: ProjectCatalogItem[]
  capabilities: SystemCapabilities
}

export interface AuthLoginResponse {
  session_id: string
  access_token: string
  token_type: string
  expires_at: string | null
  refresh_token: string
  refresh_expires_at: string | null
  user: LocalAuthUser
}

export interface ProjectSummaryStatusCounts {
  total?: number
  status_counts?: Record<string, number>
  [key: string]: unknown
}

export interface ProjectSummary {
  project_id: string
  generated_at: string
  datasets?: Record<string, unknown>
  imports?: ProjectSummaryStatusCounts
  exports?: ProjectSummaryStatusCounts
  training?: ProjectSummaryStatusCounts
  validation?: ProjectSummaryStatusCounts
  evaluation?: ProjectSummaryStatusCounts
  conversion?: ProjectSummaryStatusCounts
  inference?: ProjectSummaryStatusCounts
  workflows?: Record<string, unknown>
  deployments?: Record<string, unknown>
  [key: string]: unknown
}

export type ProjectSource = 'configured' | 'local_disk'

export interface ProjectCatalogItem {
  project_id: string
  display_name?: string | null
  description?: string | null
  metadata?: Record<string, unknown>
  project_source?: ProjectSource
  storage_prefix?: string | null
  summary?: ProjectSummary | null
}

export interface ProjectFileMetadata {
  project_id: string
  file_id: string
  object_key: string
  file_name: string
  media_type: string
  size_bytes: number
  last_modified_at?: string | null
  content_url: string
  download_url: string
}

export type TaskState = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown'

export interface TaskEvent {
  task_id?: string
  event_id?: string
  event_type?: string
  sequence?: number
  message?: string | null
  created_at?: string | null
  occurred_at?: string | null
  payload?: Record<string, unknown> | null
  [key: string]: unknown
}

export interface TaskRecord {
  task_id: string
  task_kind?: string | null
  kind?: string | null
  status?: string | null
  state?: string | null
  progress_percent?: number | null
  percent?: number | null
  project_id?: string | null
  created_at?: string | null
  updated_at?: string | null
  error_message?: string | null
  events?: TaskEvent[]
  metadata?: Record<string, unknown>
  [key: string]: unknown
}
