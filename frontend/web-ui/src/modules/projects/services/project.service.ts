import { apiRequest, apiRequestWithHeaders } from '@/shared/api/http-client'
import { parsePaginationHeaders, type PaginatedResult } from '@/shared/api/pagination'
import type { ProjectCatalogItem, ProjectSummary } from '@/shared/contracts'

export interface ProjectBootstrapInput {
  project_id: string
  display_name?: string
  description?: string
  metadata?: Record<string, unknown>
}

export interface SdkConfigPackageGenerateInput {
  include_access_token?: boolean
  model_runtime_modes?: Array<'sync' | 'async'>
  include_disabled_trigger_sources?: boolean
  runtime_ids?: string[]
  trigger_source_ids?: string[]
  deployment_ids?: string[]
  expected_revision?: string
}

export interface SdkConfigPackageFilePreview {
  path: string
  kind: string
  count: number
  runtime_key?: string | null
  trigger_source_count: number
}

export interface SdkConfigPackagePreview {
  project_id: string
  generated_at: string
  package_name: string
  base_api_url: string
  contains_access_token: boolean
  configuration_revision: string
  workflow_runtime_count: number
  trigger_source_count: number
  model_deployment_count: number
  files: SdkConfigPackageFilePreview[]
  warnings: string[]
  notes: string[]
}

export interface SdkConfigPackageDownload {
  blob: Blob
  fileName?: string
}

export interface ProjectDeletionBlocker {
  display_name?: string
  resource_kind: string
  resource_id: string
  state: string
}

export interface ProjectDeletionPreview {
  project_id: string
  project_source: 'configured' | 'local_disk'
  protected: boolean
  can_delete: boolean
  blockers: ProjectDeletionBlocker[]
  resource_counts: Record<string, number>
}

export interface ProjectDeletionResult {
  project_id: string
  operation_id: string
  state: 'cleanup_pending' | 'cleanup_failed' | 'deleted' | 'deleting' | 'failed'
  cleanup_error?: string
  resource_counts: Record<string, number>
}

export async function listProjects(options: { includeSummary?: boolean; offset?: number; limit?: number; q?: string } = {}): Promise<PaginatedResult<ProjectCatalogItem>> {
  const { payload, headers } = await apiRequestWithHeaders<ProjectCatalogItem[]>('/projects', {
    query: { include_summary: options.includeSummary ?? false, offset: options.offset ?? 0, limit: options.limit ?? 100, q: options.q || undefined },
  })
  return { items: payload, pagination: parsePaginationHeaders(headers) }
}

export interface ProjectOverviewItem { resource_id: string; target_id?: string; name: string; kind: string; state: string; occurred_at: string; runtime_mode?: 'sync' | 'async'; progress?: { stage?: string; percent?: number } }
export interface ProjectOverview { recent: ProjectOverviewItem[]; active: ProjectOverviewItem[]; total: number; offset: number; limit: number; checked_at: string; access: Record<string, boolean> }
export interface SdkResource { id: string; name: string; kind: 'runtime' | 'trigger' | 'deployment'; runtime_id: string | null }
export const getProject = (id: string, signal?: AbortSignal) => apiRequest<ProjectCatalogItem>(`/projects/${encodeURIComponent(id)}`, { signal })
export const getProjectOverview = (id: string, options: { limit?: number; offset?: number; q?: string; kind?: string } = {}, signal?: AbortSignal) => apiRequest<ProjectOverview>(`/projects/${encodeURIComponent(id)}/overview`, { query: options, signal })
export const createProject = (body: { request_id: string; display_name: string; description: string | null }) => apiRequest<ProjectCatalogItem>('/projects', { method: 'POST', body })
export const updateProject = (id: string, body: { display_name: string; description: string | null; expected_revision: string }) => apiRequest<ProjectCatalogItem>(`/projects/${encodeURIComponent(id)}`, { method: 'PATCH', body })
export async function listSdkResources(id: string, signal?: AbortSignal): Promise<SdkResource[]> {
  // 分页只读取轻量目录；校验完整性后再允许“全部资源”预览。
  const items: SdkResource[] = []
  let expected: number | null = null
  for (let offset = 0; offset <= 30_000;) {
    const { payload, headers } = await apiRequestWithHeaders<SdkResource[]>(`/projects/${encodeURIComponent(id)}/sdk-config-packages/resources`, { query: { offset, limit: 200 }, signal })
    const page = parsePaginationHeaders(headers)
    if (page.totalCount === null || page.totalCount > 30_000 || (expected !== null && expected !== page.totalCount)) throw new Error('资源列表已变化或超过支持容量，请刷新后重新选择')
    expected = page.totalCount; items.push(...payload)
    if (!page.hasMore) {
      if (new Set(items.map(item => item.id)).size !== expected || items.length !== expected) throw new Error('资源列表不完整，请刷新后重新选择')
      return items
    }
    if (!payload.length || page.nextOffset === null || page.nextOffset <= offset) throw new Error('资源分页无效，请刷新后重试')
    offset = page.nextOffset
  }
  throw new Error('资源超过支持容量，请拆分项目后导出')
}
export const getProjectDeletionResult = (id: string, operation: string) => apiRequest<ProjectDeletionResult>(`/projects/${encodeURIComponent(id)}/deletion-operations/${encodeURIComponent(operation)}`)

export async function getProjectSummary(projectId: string): Promise<ProjectSummary> {
  return apiRequest<ProjectSummary>(`/projects/${encodeURIComponent(projectId)}/summary`)
}

export async function bootstrapProject(input: ProjectBootstrapInput): Promise<ProjectCatalogItem> {
  return apiRequest<ProjectCatalogItem>('/projects/bootstrap', { method: 'POST', body: input })
}

export async function previewProjectDeletion(projectId: string): Promise<ProjectDeletionPreview> {
  return apiRequest<ProjectDeletionPreview>(
    `/projects/${encodeURIComponent(projectId)}/deletion-preview`,
  )
}

export async function deleteProject(
  projectId: string,
  confirmation: string,
): Promise<ProjectDeletionResult> {
  return apiRequest<ProjectDeletionResult>(`/projects/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
    body: { confirmation },
  })
}

export async function previewSdkConfigPackage(
  projectId: string,
  input: SdkConfigPackageGenerateInput,
  signal?: AbortSignal,
): Promise<SdkConfigPackagePreview> {
  return apiRequest<SdkConfigPackagePreview>(
    `/projects/${encodeURIComponent(projectId)}/sdk-config-packages/preview`,
    { method: 'POST', body: input, signal },
  )
}

export async function downloadSdkConfigPackage(
  projectId: string,
  input: SdkConfigPackageGenerateInput,
  signal?: AbortSignal,
): Promise<SdkConfigPackageDownload> {
  const { payload, headers } = await apiRequestWithHeaders<Blob>(
    `/projects/${encodeURIComponent(projectId)}/sdk-config-packages/download`,
    {
      method: 'POST',
      body: input,
      responseType: 'blob',
      signal,
    },
  )
  return {
    blob: payload,
    fileName: parseContentDispositionFileName(headers.get('content-disposition')),
  }
}

function parseContentDispositionFileName(value: string | null): string | undefined {
  if (!value) {
    return undefined
  }
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(value)
  if (utf8Match) {
    return decodeURIComponent(utf8Match[1].replace(/"/g, ''))
  }
  const plainMatch = /filename="?([^";]+)"?/i.exec(value)
  return plainMatch?.[1]
}
