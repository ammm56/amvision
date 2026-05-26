import { apiRequest, apiRequestWithHeaders } from '@/shared/api/http-client'
import { parsePaginationHeaders, type PaginatedResult } from '@/shared/api/pagination'
import type { TaskEvent, TaskRecord } from '@/shared/contracts'

export interface TaskListQuery {
  projectId?: string | null
  offset?: number
  limit?: number
}

export async function listTasks(query: TaskListQuery = {}): Promise<PaginatedResult<TaskRecord>> {
  const { payload, headers } = await apiRequestWithHeaders<TaskRecord[]>('/tasks', {
    query: {
      project_id: query.projectId || undefined,
      offset: query.offset ?? 0,
      limit: query.limit ?? 50,
    },
  })
  return { items: payload, pagination: parsePaginationHeaders(headers) }
}

export async function getTask(taskId: string): Promise<TaskRecord> {
  return apiRequest<TaskRecord>(`/tasks/${encodeURIComponent(taskId)}`)
}

export async function getTaskEvents(taskId: string): Promise<TaskEvent[]> {
  return apiRequest<TaskEvent[]>(`/tasks/${encodeURIComponent(taskId)}/events`)
}

export async function cancelTask(taskId: string): Promise<TaskRecord> {
  return apiRequest<TaskRecord>(`/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}