import { apiRequest, apiRequestWithHeaders } from '@/shared/api/http-client'
import { parsePaginationHeaders, type PaginatedResult } from '@/shared/api/pagination'
import type {
  FlowApplication,
  WorkflowAppRuntime,
  WorkflowAppRuntimeEvent,
  WorkflowAppRuntimeInstance,
  WorkflowExecutionPolicy,
  WorkflowGraphTemplate,
  WorkflowJsonObject,
  WorkflowPreviewRun,
  WorkflowPreviewRunEvent,
  WorkflowPreviewRunSummary,
  WorkflowRun,
  WorkflowRunEvent,
} from '../types'

export interface WorkflowRuntimeListQuery {
  projectId: string
  offset?: number
  limit?: number
}

export interface WorkflowPreviewRunCreateInput {
  projectId: string
  executionPolicyId?: string | null
  applicationId?: string | null
  application?: FlowApplication | null
  template?: WorkflowGraphTemplate | null
  inputBindings?: WorkflowJsonObject
  executionMetadata?: WorkflowJsonObject
  timeoutSeconds?: number | null
  waitMode?: 'sync' | 'async'
}

export interface WorkflowAppRuntimeCreateInput {
  projectId: string
  applicationId: string
  executionPolicyId?: string | null
  displayName?: string
  requestTimeoutSeconds?: number | null
  heartbeatIntervalSeconds?: number | null
  heartbeatTimeoutSeconds?: number | null
  metadata?: WorkflowJsonObject
}

export interface WorkflowRuntimeInvokeInput {
  inputBindings?: WorkflowJsonObject
  executionMetadata?: WorkflowJsonObject
  timeoutSeconds?: number | null
}

export interface WorkflowExecutionPolicyCreateInput {
  projectId: string
  executionPolicyId: string
  displayName: string
  policyKind: string
  defaultTimeoutSeconds?: number
  maxRunTimeoutSeconds?: number
  traceLevel?: string
  retainNodeRecordsEnabled?: boolean
  retainTraceEnabled?: boolean
  metadata?: WorkflowJsonObject
}

function encodePathPart(value: string): string {
  return encodeURIComponent(value)
}

export async function createWorkflowExecutionPolicy(input: WorkflowExecutionPolicyCreateInput): Promise<WorkflowExecutionPolicy> {
  return apiRequest<WorkflowExecutionPolicy>('/workflows/execution-policies', {
    method: 'POST',
    body: {
      project_id: input.projectId,
      execution_policy_id: input.executionPolicyId,
      display_name: input.displayName,
      policy_kind: input.policyKind,
      default_timeout_seconds: input.defaultTimeoutSeconds ?? 30,
      max_run_timeout_seconds: input.maxRunTimeoutSeconds ?? input.defaultTimeoutSeconds ?? 30,
      trace_level: input.traceLevel ?? 'none',
      retain_node_records_enabled: input.retainNodeRecordsEnabled ?? false,
      retain_trace_enabled: input.retainTraceEnabled ?? false,
      metadata: input.metadata ?? {},
    },
  })
}

export async function listWorkflowExecutionPolicies(query: WorkflowRuntimeListQuery): Promise<PaginatedResult<WorkflowExecutionPolicy>> {
  const { payload, headers } = await apiRequestWithHeaders<WorkflowExecutionPolicy[]>('/workflows/execution-policies', {
    query: { project_id: query.projectId, offset: query.offset ?? 0, limit: query.limit ?? 100 },
  })
  return { items: payload, pagination: parsePaginationHeaders(headers) }
}

export async function getWorkflowExecutionPolicy(executionPolicyId: string): Promise<WorkflowExecutionPolicy> {
  return apiRequest<WorkflowExecutionPolicy>(`/workflows/execution-policies/${encodePathPart(executionPolicyId)}`)
}

export async function createWorkflowPreviewRun(input: WorkflowPreviewRunCreateInput): Promise<WorkflowPreviewRun> {
  return apiRequest<WorkflowPreviewRun>('/workflows/preview-runs', {
    method: 'POST',
    body: {
      project_id: input.projectId,
      execution_policy_id: input.executionPolicyId ?? null,
      application_ref: input.applicationId ? { application_id: input.applicationId } : null,
      application: input.application ?? null,
      template: input.template ?? null,
      input_bindings: input.inputBindings ?? {},
      execution_metadata: input.executionMetadata ?? {},
      timeout_seconds: input.timeoutSeconds ?? null,
      wait_mode: input.waitMode ?? 'sync',
    },
  })
}

export async function listWorkflowPreviewRuns(
  query: WorkflowRuntimeListQuery & { state?: string; createdFrom?: string; createdTo?: string },
): Promise<PaginatedResult<WorkflowPreviewRunSummary>> {
  const { payload, headers } = await apiRequestWithHeaders<WorkflowPreviewRunSummary[]>('/workflows/preview-runs', {
    query: {
      project_id: query.projectId,
      state: query.state,
      created_from: query.createdFrom,
      created_to: query.createdTo,
      offset: query.offset ?? 0,
      limit: query.limit ?? 100,
    },
  })
  return { items: payload, pagination: parsePaginationHeaders(headers) }
}

export async function getWorkflowPreviewRun(previewRunId: string): Promise<WorkflowPreviewRun> {
  return apiRequest<WorkflowPreviewRun>(`/workflows/preview-runs/${encodePathPart(previewRunId)}`)
}

export async function getWorkflowPreviewRunEvents(previewRunId: string, afterSequence?: number, limit?: number): Promise<WorkflowPreviewRunEvent[]> {
  return apiRequest<WorkflowPreviewRunEvent[]>(`/workflows/preview-runs/${encodePathPart(previewRunId)}/events`, {
    query: { after_sequence: afterSequence, limit },
  })
}

export async function readWorkflowPreviewRunArtifactBlob(previewRunId: string, objectKey: string): Promise<Blob> {
  return apiRequest<Blob>(`/workflows/preview-runs/${encodePathPart(previewRunId)}/artifacts/content`, {
    query: { object_key: objectKey },
    responseType: 'blob',
  })
}

export async function readProjectObjectContentBlob(projectId: string, objectKey: string): Promise<Blob> {
  return apiRequest<Blob>(`/projects/${encodePathPart(projectId)}/files/content`, {
    query: { object_key: objectKey },
    responseType: 'blob',
  })
}

export async function cancelWorkflowPreviewRun(previewRunId: string): Promise<WorkflowPreviewRun> {
  return apiRequest<WorkflowPreviewRun>(`/workflows/preview-runs/${encodePathPart(previewRunId)}/cancel`, { method: 'POST' })
}

export async function deleteWorkflowPreviewRun(previewRunId: string): Promise<void> {
  return apiRequest<void>(`/workflows/preview-runs/${encodePathPart(previewRunId)}`, { method: 'DELETE', responseType: 'void' })
}

export async function createWorkflowAppRuntime(input: WorkflowAppRuntimeCreateInput): Promise<WorkflowAppRuntime> {
  return apiRequest<WorkflowAppRuntime>('/workflows/app-runtimes', {
    method: 'POST',
    body: {
      project_id: input.projectId,
      application_id: input.applicationId,
      execution_policy_id: input.executionPolicyId ?? null,
      display_name: input.displayName ?? '',
      request_timeout_seconds: input.requestTimeoutSeconds ?? null,
      heartbeat_interval_seconds: input.heartbeatIntervalSeconds ?? null,
      heartbeat_timeout_seconds: input.heartbeatTimeoutSeconds ?? null,
      metadata: input.metadata ?? {},
    },
  })
}

export async function listWorkflowAppRuntimes(query: WorkflowRuntimeListQuery): Promise<PaginatedResult<WorkflowAppRuntime>> {
  const { payload, headers } = await apiRequestWithHeaders<WorkflowAppRuntime[]>('/workflows/app-runtimes', {
    query: { project_id: query.projectId, offset: query.offset ?? 0, limit: query.limit ?? 100 },
  })
  return { items: payload, pagination: parsePaginationHeaders(headers) }
}

export async function getWorkflowAppRuntime(workflowRuntimeId: string): Promise<WorkflowAppRuntime> {
  return apiRequest<WorkflowAppRuntime>(`/workflows/app-runtimes/${encodePathPart(workflowRuntimeId)}`)
}

export async function getWorkflowAppRuntimeEvents(workflowRuntimeId: string, afterSequence?: number, limit?: number): Promise<WorkflowAppRuntimeEvent[]> {
  return apiRequest<WorkflowAppRuntimeEvent[]>(`/workflows/app-runtimes/${encodePathPart(workflowRuntimeId)}/events`, {
    query: { after_sequence: afterSequence, limit },
  })
}

export async function startWorkflowAppRuntime(workflowRuntimeId: string): Promise<WorkflowAppRuntime> {
  return apiRequest<WorkflowAppRuntime>(`/workflows/app-runtimes/${encodePathPart(workflowRuntimeId)}/start`, { method: 'POST' })
}

export async function stopWorkflowAppRuntime(workflowRuntimeId: string): Promise<WorkflowAppRuntime> {
  return apiRequest<WorkflowAppRuntime>(`/workflows/app-runtimes/${encodePathPart(workflowRuntimeId)}/stop`, { method: 'POST' })
}

export async function restartWorkflowAppRuntime(workflowRuntimeId: string): Promise<WorkflowAppRuntime> {
  return apiRequest<WorkflowAppRuntime>(`/workflows/app-runtimes/${encodePathPart(workflowRuntimeId)}/restart`, { method: 'POST' })
}

export async function getWorkflowAppRuntimeHealth(workflowRuntimeId: string): Promise<WorkflowAppRuntime> {
  return apiRequest<WorkflowAppRuntime>(`/workflows/app-runtimes/${encodePathPart(workflowRuntimeId)}/health`)
}

export async function listWorkflowAppRuntimeInstances(workflowRuntimeId: string): Promise<WorkflowAppRuntimeInstance[]> {
  return apiRequest<WorkflowAppRuntimeInstance[]>(`/workflows/app-runtimes/${encodePathPart(workflowRuntimeId)}/instances`)
}

export async function deleteWorkflowAppRuntime(workflowRuntimeId: string): Promise<void> {
  return apiRequest<void>(`/workflows/app-runtimes/${encodePathPart(workflowRuntimeId)}`, { method: 'DELETE', responseType: 'void' })
}

export async function createWorkflowRun(workflowRuntimeId: string, input: WorkflowRuntimeInvokeInput = {}): Promise<WorkflowRun> {
  return apiRequest<WorkflowRun>(`/workflows/app-runtimes/${encodePathPart(workflowRuntimeId)}/runs`, {
    method: 'POST',
    body: {
      input_bindings: input.inputBindings ?? {},
      execution_metadata: input.executionMetadata ?? {},
      timeout_seconds: input.timeoutSeconds ?? null,
    },
  })
}

export async function invokeWorkflowAppRuntime(workflowRuntimeId: string, input: WorkflowRuntimeInvokeInput = {}): Promise<WorkflowRun> {
  return apiRequest<WorkflowRun>(`/workflows/app-runtimes/${encodePathPart(workflowRuntimeId)}/invoke`, {
    method: 'POST',
    query: { response_mode: 'run' },
    body: {
      input_bindings: input.inputBindings ?? {},
      execution_metadata: input.executionMetadata ?? {},
      timeout_seconds: input.timeoutSeconds ?? null,
    },
  })
}

export async function getWorkflowRun(workflowRunId: string): Promise<WorkflowRun> {
  return apiRequest<WorkflowRun>(`/workflows/runs/${encodePathPart(workflowRunId)}`, {
    query: { response_mode: 'run' },
  })
}

export async function getWorkflowRunEvents(workflowRunId: string, afterSequence?: number, limit?: number): Promise<WorkflowRunEvent[]> {
  return apiRequest<WorkflowRunEvent[]>(`/workflows/runs/${encodePathPart(workflowRunId)}/events`, {
    query: { after_sequence: afterSequence, limit },
  })
}

export async function cancelWorkflowRun(workflowRunId: string): Promise<WorkflowRun> {
  return apiRequest<WorkflowRun>(`/workflows/runs/${encodePathPart(workflowRunId)}/cancel`, { method: 'POST' })
}
