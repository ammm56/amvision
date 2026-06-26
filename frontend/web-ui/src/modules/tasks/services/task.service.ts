import { apiRequest, apiRequestWithHeaders } from '@/shared/api/http-client'
import { parsePaginationHeaders, type PaginatedResult } from '@/shared/api/pagination'
import type { TaskEvent, TaskRecord } from '@/shared/contracts'

export interface TaskListQuery {
  projectId?: string | null
  offset?: number
  limit?: number
}

export interface TaskEventListQuery {
  offset?: number
  limit?: number
}

const TASK_EVENT_PAGE_SIZE = 500

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

export async function getTaskEvents(taskId: string, query: TaskEventListQuery = {}): Promise<TaskEvent[]> {
  return apiRequest<TaskEvent[]>(`/tasks/${encodeURIComponent(taskId)}/events`, {
    query: {
      offset: query.offset ?? 0,
      limit: query.limit ?? TASK_EVENT_PAGE_SIZE,
    },
  })
}

export async function getAllTaskEvents(taskId: string): Promise<TaskEvent[]> {
  const events: TaskEvent[] = []
  let offset = 0

  while (true) {
    const page = await getTaskEvents(taskId, {
      offset,
      limit: TASK_EVENT_PAGE_SIZE,
    })
    events.push(...page)
    if (page.length < TASK_EVENT_PAGE_SIZE) {
      return events
    }
    offset += page.length
  }
}

export async function cancelTask(taskId: string): Promise<TaskRecord> {
  return apiRequest<TaskRecord>(`/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}
