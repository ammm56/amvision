import { ref } from 'vue'
import { apiRequest } from './http-client'

export type DeletionKind = 'task' | 'dataset' | 'dataset-version' | 'dataset-import' | 'dataset-export' | 'dataset-export-files' | 'model-version' | 'model-build'
export interface DeletionStatus {
  operation_id: string
  project_id: string
  resource_kind: string
  resource_id: string
  state: 'prepared' | 'committed' | 'completed' | 'rolled_back'
  error: string | null
}
export const deletionRevision = ref(0)

export async function submitResourceDeletion(kind: DeletionKind, resourceId: string, projectId: string, expectedRevision?: string): Promise<DeletionStatus> {
  const result = await apiRequest<DeletionStatus>('/resource-deletions', {
    method: 'POST', body: { format_id: 'amvision.resource-deletion-request.v1', kind, resource_id: resourceId, project_id: projectId, ...(expectedRevision ? { expected_revision: expectedRevision } : {}) },
  })
  deletionRevision.value += 1
  return result
}

export interface ModelVersionDeletionPreview {
  blocked: boolean
  reason?: string
  revision?: string
  deleted_models?: Array<{ kind: string; resource_id: string }>
  has_file_cleanup?: boolean
}
export function previewModelVersionDeletion(projectId: string, resourceId: string, signal?: AbortSignal): Promise<ModelVersionDeletionPreview> {
  return apiRequest('/resource-deletions/preview', { signal, query: { kind: 'model-version', project_id: projectId, resource_id: resourceId } })
}

export function previewModelBuildDeletion(projectId: string, resourceId: string): Promise<ModelVersionDeletionPreview> {
  return apiRequest('/resource-deletions/preview', { query: { kind: 'model-build', project_id: projectId, resource_id: resourceId } })
}

export function listResourceDeletions(projectId: string, signal?: AbortSignal): Promise<DeletionStatus[]> {
  return apiRequest('/resource-deletions', { query: { project_id: projectId }, signal })
}

export async function retryResourceDeletion(operationId: string): Promise<void> {
  await apiRequest(`/resource-deletions/${encodeURIComponent(operationId)}/retry`, { method: 'POST', responseType: 'void' })
  deletionRevision.value += 1
}
