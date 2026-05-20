import { apiRequest, apiRequestWithHeaders } from '@/shared/api/http-client'
import { parsePaginationHeaders, type PaginatedResult } from '@/shared/api/pagination'
import type {
  WorkflowGraphTemplate,
  WorkflowTemplateDocument,
  WorkflowTemplateSummary,
  WorkflowTemplateValidationResponse,
  WorkflowTemplateVersionSummary,
} from '../types'

export interface WorkflowListQuery {
  offset?: number
  limit?: number
}

export interface WorkflowTemplateCopyInput {
  targetTemplateId: string
  targetTemplateVersion: string
  displayName?: string
  description?: string
}

function encodePathPart(value: string): string {
  return encodeURIComponent(value)
}

export async function validateWorkflowTemplate(template: WorkflowGraphTemplate): Promise<WorkflowTemplateValidationResponse> {
  return apiRequest<WorkflowTemplateValidationResponse>('/workflows/templates/validate', {
    method: 'POST',
    body: { template },
  })
}

export async function saveWorkflowTemplate(projectId: string, template: WorkflowGraphTemplate): Promise<WorkflowTemplateDocument> {
  return apiRequest<WorkflowTemplateDocument>(
    `/workflows/projects/${encodePathPart(projectId)}/templates/${encodePathPart(template.template_id)}/versions/${encodePathPart(template.template_version)}`,
    { method: 'PUT', body: { template } },
  )
}

export async function listWorkflowTemplates(
  projectId: string,
  query: WorkflowListQuery = {},
): Promise<PaginatedResult<WorkflowTemplateSummary>> {
  const { payload, headers } = await apiRequestWithHeaders<WorkflowTemplateSummary[]>(
    `/workflows/projects/${encodePathPart(projectId)}/templates`,
    { query: { offset: query.offset ?? 0, limit: query.limit ?? 100 } },
  )
  return { items: payload, pagination: parsePaginationHeaders(headers) }
}

export async function listWorkflowTemplateVersions(
  projectId: string,
  templateId: string,
  query: WorkflowListQuery = {},
): Promise<PaginatedResult<WorkflowTemplateVersionSummary>> {
  const { payload, headers } = await apiRequestWithHeaders<WorkflowTemplateVersionSummary[]>(
    `/workflows/projects/${encodePathPart(projectId)}/templates/${encodePathPart(templateId)}/versions`,
    { query: { offset: query.offset ?? 0, limit: query.limit ?? 100 } },
  )
  return { items: payload, pagination: parsePaginationHeaders(headers) }
}

export async function getWorkflowTemplate(projectId: string, templateId: string, templateVersion: string): Promise<WorkflowTemplateDocument> {
  return apiRequest<WorkflowTemplateDocument>(
    `/workflows/projects/${encodePathPart(projectId)}/templates/${encodePathPart(templateId)}/versions/${encodePathPart(templateVersion)}`,
  )
}

export async function getLatestWorkflowTemplate(projectId: string, templateId: string): Promise<WorkflowTemplateDocument> {
  return apiRequest<WorkflowTemplateDocument>(
    `/workflows/projects/${encodePathPart(projectId)}/templates/${encodePathPart(templateId)}/latest`,
  )
}

export async function copyWorkflowTemplateVersion(
  projectId: string,
  templateId: string,
  templateVersion: string,
  input: WorkflowTemplateCopyInput,
): Promise<WorkflowTemplateDocument> {
  return apiRequest<WorkflowTemplateDocument>(
    `/workflows/projects/${encodePathPart(projectId)}/templates/${encodePathPart(templateId)}/versions/${encodePathPart(templateVersion)}/copy`,
    {
      method: 'POST',
      body: {
        target_template_id: input.targetTemplateId,
        target_template_version: input.targetTemplateVersion,
        display_name: input.displayName ?? null,
        description: input.description ?? null,
      },
    },
  )
}

export async function deleteWorkflowTemplateVersion(projectId: string, templateId: string, templateVersion: string): Promise<void> {
  return apiRequest<void>(
    `/workflows/projects/${encodePathPart(projectId)}/templates/${encodePathPart(templateId)}/versions/${encodePathPart(templateVersion)}`,
    { method: 'DELETE', responseType: 'void' },
  )
}
