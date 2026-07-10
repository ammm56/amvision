import { apiRequest, apiRequestWithHeaders } from '@/shared/api/http-client'
import { parsePaginationHeaders, type PaginatedResult } from '@/shared/api/pagination'
import type {
  FlowApplication,
  WorkflowApplicationDocument,
  WorkflowApplicationSummary,
  WorkflowApplicationValidationResponse,
  WorkflowGraphTemplate,
} from '../types'

export interface WorkflowApplicationListQuery {
  offset?: number
  limit?: number
}

export interface WorkflowApplicationCopyInput {
  targetApplicationId: string
  displayName?: string
  description?: string
}

export interface WorkflowApplicationMetadataUpdateInput {
  displayName?: string
  description?: string
}

function encodePathPart(value: string): string {
  return encodeURIComponent(value)
}

export async function validateWorkflowApplication(
  projectId: string,
  application: FlowApplication,
  template?: WorkflowGraphTemplate | null,
): Promise<WorkflowApplicationValidationResponse> {
  return apiRequest<WorkflowApplicationValidationResponse>('/workflows/applications/validate', {
    method: 'POST',
    body: { project_id: projectId, application, template: template ?? null },
  })
}

export async function saveWorkflowApplication(projectId: string, application: FlowApplication): Promise<WorkflowApplicationDocument> {
  return apiRequest<WorkflowApplicationDocument>(
    `/workflows/projects/${encodePathPart(projectId)}/applications/${encodePathPart(application.application_id)}`,
    { method: 'PUT', body: { application } },
  )
}

export async function updateWorkflowApplicationMetadata(
  projectId: string,
  applicationId: string,
  input: WorkflowApplicationMetadataUpdateInput,
): Promise<WorkflowApplicationDocument> {
  return apiRequest<WorkflowApplicationDocument>(
    `/workflows/projects/${encodePathPart(projectId)}/applications/${encodePathPart(applicationId)}`,
    {
      method: 'PATCH',
      body: {
        display_name: input.displayName ?? null,
        description: input.description ?? null,
      },
    },
  )
}

export async function listWorkflowApplications(
  projectId: string,
  query: WorkflowApplicationListQuery = {},
): Promise<PaginatedResult<WorkflowApplicationSummary>> {
  const { payload, headers } = await apiRequestWithHeaders<WorkflowApplicationSummary[]>(
    `/workflows/projects/${encodePathPart(projectId)}/applications`,
    { query: { offset: query.offset ?? 0, limit: query.limit ?? 100 } },
  )
  return { items: payload, pagination: parsePaginationHeaders(headers) }
}

export async function getWorkflowApplication(projectId: string, applicationId: string): Promise<WorkflowApplicationDocument> {
  return apiRequest<WorkflowApplicationDocument>(
    `/workflows/projects/${encodePathPart(projectId)}/applications/${encodePathPart(applicationId)}`,
  )
}

export async function copyWorkflowApplication(
  projectId: string,
  applicationId: string,
  input: WorkflowApplicationCopyInput,
): Promise<WorkflowApplicationDocument> {
  return apiRequest<WorkflowApplicationDocument>(
    `/workflows/projects/${encodePathPart(projectId)}/applications/${encodePathPart(applicationId)}/copy`,
    {
      method: 'POST',
      body: {
        target_application_id: input.targetApplicationId,
        display_name: input.displayName ?? null,
        description: input.description ?? null,
      },
    },
  )
}

export async function deleteWorkflowApplication(projectId: string, applicationId: string): Promise<void> {
  return apiRequest<void>(
    `/workflows/projects/${encodePathPart(projectId)}/applications/${encodePathPart(applicationId)}`,
    { method: 'DELETE', responseType: 'void' },
  )
}
