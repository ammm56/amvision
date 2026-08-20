import { apiRequest, apiRequestWithHeaders } from '@/shared/api/http-client'
import { parsePaginationHeaders, type PaginatedResult } from '@/shared/api/pagination'
import type {
  FlowApplication,
  WorkflowApplicationBundleSaveDocument,
  WorkflowApplicationDocument,
  WorkflowApplicationSummary,
  WorkflowApplicationValidationResponse,
  WorkflowAppVersion,
  WorkflowAppVersionComparison,
  WorkflowAppVersionDetail,
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

export interface WorkflowAppVersionPublishInput {
  expectedDraftFingerprint: string
  releaseNotes?: string
  displayVersion?: string | null
  allowDuplicateContent?: boolean
}

export type WorkflowAppVersionStateTransition = 'archive' | 'restore'

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

export function saveWorkflowApplication(
  projectId: string,
  application: FlowApplication,
  template: WorkflowGraphTemplate,
): Promise<WorkflowApplicationBundleSaveDocument>
export function saveWorkflowApplication(
  projectId: string,
  application: FlowApplication,
  template?: undefined,
): Promise<WorkflowApplicationDocument>
export async function saveWorkflowApplication(
  projectId: string,
  application: FlowApplication,
  template?: WorkflowGraphTemplate,
): Promise<WorkflowApplicationDocument | WorkflowApplicationBundleSaveDocument> {
  return apiRequest<WorkflowApplicationDocument | WorkflowApplicationBundleSaveDocument>(
    `/workflows/projects/${encodePathPart(projectId)}/applications/${encodePathPart(application.application_id)}`,
    {
      method: 'PUT',
      body: template === undefined ? { application } : { application, template },
    },
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

export async function publishWorkflowAppVersion(
  projectId: string,
  applicationId: string,
  input: WorkflowAppVersionPublishInput,
): Promise<WorkflowAppVersion> {
  return apiRequest<WorkflowAppVersion>(
    `/workflows/projects/${encodePathPart(projectId)}/applications/${encodePathPart(applicationId)}/versions`,
    {
      method: 'POST',
      body: {
        expected_draft_fingerprint: input.expectedDraftFingerprint,
        release_notes: input.releaseNotes ?? '',
        display_version: input.displayVersion ?? null,
        allow_duplicate_content: input.allowDuplicateContent ?? false,
      },
    },
  )
}

export async function listWorkflowAppVersions(
  projectId: string,
  applicationId: string,
  query: WorkflowApplicationListQuery = {},
): Promise<PaginatedResult<WorkflowAppVersion>> {
  const { payload, headers } = await apiRequestWithHeaders<WorkflowAppVersion[]>(
    `/workflows/projects/${encodePathPart(projectId)}/applications/${encodePathPart(applicationId)}/versions`,
    { query: { offset: query.offset ?? 0, limit: query.limit ?? 100 } },
  )
  return { items: payload, pagination: parsePaginationHeaders(headers) }
}

export async function getWorkflowAppVersion(
  projectId: string,
  applicationId: string,
  workflowAppVersionId: string,
): Promise<WorkflowAppVersionDetail> {
  return apiRequest<WorkflowAppVersionDetail>(
    `/workflows/projects/${encodePathPart(projectId)}/applications/${encodePathPart(applicationId)}/versions/${encodePathPart(workflowAppVersionId)}`,
  )
}

export async function transitionWorkflowAppVersionState(
  projectId: string,
  applicationId: string,
  workflowAppVersionId: string,
  transition: WorkflowAppVersionStateTransition,
): Promise<WorkflowAppVersion> {
  const expectedState = transition === 'archive' ? 'published' : 'archived'
  return apiRequest<WorkflowAppVersion>(
    `/workflows/projects/${encodePathPart(projectId)}/applications/${encodePathPart(applicationId)}/versions/${encodePathPart(workflowAppVersionId)}/${transition}`,
    {
      method: 'POST',
      body: { expected_state: expectedState },
    },
  )
}

export async function compareWorkflowAppVersionToDraft(
  projectId: string,
  applicationId: string,
  workflowAppVersionId: string,
): Promise<WorkflowAppVersionComparison> {
  return apiRequest<WorkflowAppVersionComparison>(
    `/workflows/projects/${encodePathPart(projectId)}/applications/${encodePathPart(applicationId)}/versions/${encodePathPart(workflowAppVersionId)}/compare`,
  )
}
