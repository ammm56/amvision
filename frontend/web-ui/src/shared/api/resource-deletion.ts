import { ref } from 'vue'
import { apiRequest } from './http-client'

export type DeletionKind = 'task' | 'dataset' | 'dataset-version' | 'dataset-import' | 'dataset-export'
export interface DeletionStatus {
  operation_id: string
  project_id: string
  resource_kind: string
  resource_id: string
  state: 'prepared' | 'committed' | 'completed' | 'rolled_back'
  error: string | null
}
export const deletionRevision = ref(0)

export async function submitResourceDeletion(kind: DeletionKind, resourceId: string, projectId: string): Promise<DeletionStatus> {
  const result = await apiRequest<DeletionStatus>('/resource-deletions', {
    method: 'POST', body: { format_id: 'amvision.resource-deletion-request.v1', kind, resource_id: resourceId, project_id: projectId },
  })
  deletionRevision.value += 1
  return result
}

export function listResourceDeletions(projectId: string, signal?: AbortSignal): Promise<DeletionStatus[]> {
  return apiRequest('/resource-deletions', { query: { project_id: projectId }, signal })
}

export async function retryResourceDeletion(operationId: string): Promise<void> {
  await apiRequest(`/resource-deletions/${encodeURIComponent(operationId)}/retry`, { method: 'POST', responseType: 'void' })
  deletionRevision.value += 1
}
