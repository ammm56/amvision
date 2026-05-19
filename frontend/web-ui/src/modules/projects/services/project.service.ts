import { apiRequest, apiRequestWithHeaders } from '@/shared/api/http-client'
import { parsePaginationHeaders, type PaginatedResult } from '@/shared/api/pagination'
import type { ProjectCatalogItem, ProjectSummary } from '@/shared/contracts'

export interface ProjectBootstrapInput {
  project_id: string
  display_name?: string
  description?: string
  metadata?: Record<string, unknown>
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