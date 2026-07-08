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
  workflow_runtime_count: number
  trigger_source_count: number
  model_deployment_count: number
  files: SdkConfigPackageFilePreview[]
  warnings: string[]
}

export interface SdkConfigPackageDownload {
  blob: Blob
  fileName?: string
}

export async function listProjects(options: { includeSummary?: boolean } = {}): Promise<PaginatedResult<ProjectCatalogItem>> {
  const { payload, headers } = await apiRequestWithHeaders<ProjectCatalogItem[]>('/projects', {
    query: { include_summary: options.includeSummary ?? false, offset: 0, limit: 100 },
  })
  return { items: payload, pagination: parsePaginationHeaders(headers) }
}

export async function getProjectSummary(projectId: string): Promise<ProjectSummary> {
  return apiRequest<ProjectSummary>(`/projects/${encodeURIComponent(projectId)}/summary`)
}

export async function bootstrapProject(input: ProjectBootstrapInput): Promise<ProjectCatalogItem> {
  return apiRequest<ProjectCatalogItem>('/projects/bootstrap', { method: 'POST', body: input })
}

export async function previewSdkConfigPackage(
  projectId: string,
  input: SdkConfigPackageGenerateInput,
): Promise<SdkConfigPackagePreview> {
  return apiRequest<SdkConfigPackagePreview>(
    `/projects/${encodeURIComponent(projectId)}/sdk-config-packages/preview`,
    { method: 'POST', body: input },
  )
}

export async function downloadSdkConfigPackage(
  projectId: string,
  input: SdkConfigPackageGenerateInput,
): Promise<SdkConfigPackageDownload> {
  const { payload, headers } = await apiRequestWithHeaders<Blob>(
    `/projects/${encodeURIComponent(projectId)}/sdk-config-packages/download`,
    {
      method: 'POST',
      body: input,
      responseType: 'blob',
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
