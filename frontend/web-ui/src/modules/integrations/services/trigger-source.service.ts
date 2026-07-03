import { apiRequest, apiRequestWithHeaders } from '@/shared/api/http-client'
import { parsePaginationHeaders, type PaginatedResult } from '@/shared/api/pagination'
import type { WorkflowJsonObject } from '@/workflows/workflow-editor/types'

export interface InputBindingMappingItem {
  source?: string | null
  value?: unknown
  required?: boolean
  payload_type_id?: string | null
  metadata?: WorkflowJsonObject
}

export interface TriggerResultMapping {
  result_binding: string
  result_mode: string
  reply_timeout_seconds?: number | null
  metadata?: WorkflowJsonObject
}

export interface WorkflowTriggerSource {
  format_id: string
  trigger_source_id: string
  project_id: string
  display_name: string
  trigger_kind: string
  workflow_runtime_id: string
  submit_mode: string
  enabled: boolean
  desired_state: string
  observed_state: string
  transport_config: WorkflowJsonObject
  match_rule: WorkflowJsonObject
  input_binding_mapping: Record<string, InputBindingMappingItem>
  result_mapping: TriggerResultMapping
  default_execution_metadata: WorkflowJsonObject
  ack_policy: string
  result_mode: string
  reply_timeout_seconds?: number | null
  debounce_window_ms?: number | null
  idempotency_key_path?: string | null
  last_triggered_at?: string | null
  last_error?: WorkflowJsonObject | string | null
  health_summary: WorkflowJsonObject
  metadata: WorkflowJsonObject
  created_at: string
  updated_at: string
}

export interface WorkflowTriggerSourceHealthSummary {
  adapter_configured: boolean
  adapter_running: boolean
  request_count: number
  request_count_rollover_count: number
  success_count: number
  success_count_rollover_count: number
  error_count: number
  error_count_rollover_count: number
  timeout_count: number
  timeout_count_rollover_count: number
  recent_error?: WorkflowJsonObject | string | null
  supervisor: WorkflowJsonObject
}

export interface WorkflowTriggerSourceHealth {
  trigger_source_id: string
  enabled: boolean
  desired_state: string
  observed_state: string
  last_triggered_at?: string | null
  last_error?: WorkflowJsonObject | string | null
  health_summary: WorkflowTriggerSourceHealthSummary
}

export interface WorkflowTriggerSourceCreateInput {
  projectId: string
  triggerSourceId: string
  displayName: string
  triggerKind: string
  workflowRuntimeId: string
  submitMode: string
  enabled?: boolean
  transportConfig?: WorkflowJsonObject
  matchRule?: WorkflowJsonObject
  inputBindingMapping?: Record<string, InputBindingMappingItem>
  resultMapping?: Partial<TriggerResultMapping>
  defaultExecutionMetadata?: WorkflowJsonObject
  ackPolicy?: string
  resultMode?: string
  replyTimeoutSeconds?: number | null
  debounceWindowMs?: number | null
  idempotencyKeyPath?: string | null
  metadata?: WorkflowJsonObject
}

function encodePathPart(value: string): string {
  return encodeURIComponent(value)
}

export async function listWorkflowTriggerSources(query: { projectId: string; offset?: number; limit?: number }): Promise<PaginatedResult<WorkflowTriggerSource>> {
  const { payload, headers } = await apiRequestWithHeaders<WorkflowTriggerSource[]>('/workflows/trigger-sources', {
    query: { project_id: query.projectId, offset: query.offset ?? 0, limit: query.limit ?? 100 },
  })
  return { items: payload, pagination: parsePaginationHeaders(headers) }
}

export async function getWorkflowTriggerSource(triggerSourceId: string): Promise<WorkflowTriggerSource> {
  return apiRequest<WorkflowTriggerSource>(`/workflows/trigger-sources/${encodePathPart(triggerSourceId)}`)
}

export async function createWorkflowTriggerSource(input: WorkflowTriggerSourceCreateInput): Promise<WorkflowTriggerSource> {
  return apiRequest<WorkflowTriggerSource>('/workflows/trigger-sources', {
    method: 'POST',
    body: {
      trigger_source_id: input.triggerSourceId,
      project_id: input.projectId,
      display_name: input.displayName,
      trigger_kind: input.triggerKind,
      workflow_runtime_id: input.workflowRuntimeId,
      submit_mode: input.submitMode,
      enabled: input.enabled ?? false,
      transport_config: input.transportConfig ?? {},
      match_rule: input.matchRule ?? {},
      input_binding_mapping: input.inputBindingMapping ?? {},
      result_mapping: input.resultMapping ?? {},
      default_execution_metadata: input.defaultExecutionMetadata ?? {},
      ack_policy: input.ackPolicy ?? 'ack-after-run-finished',
      result_mode: input.resultMode ?? 'sync-reply',
      reply_timeout_seconds: input.replyTimeoutSeconds ?? null,
      debounce_window_ms: input.debounceWindowMs ?? null,
      idempotency_key_path: input.idempotencyKeyPath ?? null,
      metadata: input.metadata ?? {},
    },
  })
}

export async function enableWorkflowTriggerSource(triggerSourceId: string): Promise<WorkflowTriggerSource> {
  return apiRequest<WorkflowTriggerSource>(`/workflows/trigger-sources/${encodePathPart(triggerSourceId)}/enable`, { method: 'POST' })
}

export async function disableWorkflowTriggerSource(triggerSourceId: string): Promise<WorkflowTriggerSource> {
  return apiRequest<WorkflowTriggerSource>(`/workflows/trigger-sources/${encodePathPart(triggerSourceId)}/disable`, { method: 'POST' })
}

export async function deleteWorkflowTriggerSource(triggerSourceId: string): Promise<void> {
  return apiRequest<void>(`/workflows/trigger-sources/${encodePathPart(triggerSourceId)}`, { method: 'DELETE', responseType: 'void' })
}

export async function getWorkflowTriggerSourceHealth(triggerSourceId: string): Promise<WorkflowTriggerSourceHealth> {
  return apiRequest<WorkflowTriggerSourceHealth>(`/workflows/trigger-sources/${encodePathPart(triggerSourceId)}/health`)
}
