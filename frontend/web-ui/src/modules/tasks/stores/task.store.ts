import { defineStore } from 'pinia'

import { cancelTask, getTask, getTaskEvents, listTasks } from '../services/task.service'
import type { PaginationMeta } from '@/shared/api/pagination'
import type { TaskEvent, TaskRecord, TaskState } from '@/shared/contracts'
import { translate } from '@/platform/i18n'

export const DEFAULT_TASK_PAGE_SIZE = 50

interface TaskListLoadOptions {
  offset?: number
  limit?: number
  reset?: boolean
}

function createPaginationState(): PaginationMeta {
  return {
    offset: 0,
    limit: DEFAULT_TASK_PAGE_SIZE,
    totalCount: 0,
    hasMore: false,
    nextOffset: null,
  }
}

export function normalizeTaskState(task: TaskRecord): TaskState {
  const rawState = String(task.state ?? task.status ?? '').toLowerCase()
  if (rawState.includes('queue')) return 'queued'
  if (rawState.includes('run')) return 'running'
  if (rawState.includes('complete') || rawState.includes('success') || rawState.includes('succeed')) return 'succeeded'
  if (rawState.includes('fail') || rawState.includes('error')) return 'failed'
  if (rawState.includes('cancel')) return 'cancelled'
  return 'unknown'
}

export function getTaskProgressPercent(task: TaskRecord): number {
  const progress = task.progress as Record<string, unknown> | undefined
  const value = task.progress_percent ?? task.percent ?? progress?.percent ?? progress?.progress_percent ?? progress?.progress
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

export const useTaskStore = defineStore('tasks', {
  state: () => ({
    tasks: [] as TaskRecord[],
    selectedTask: null as TaskRecord | null,
    selectedTaskEvents: [] as TaskEvent[],
    listProjectId: null as string | null,
    pagination: createPaginationState(),
    loading: false,
    detailLoading: false,
    error: null as string | null,
  }),
  actions: {
    async loadTasks(projectId?: string | null, options: TaskListLoadOptions = {}): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const normalizedProjectId = projectId ?? null
        const shouldResetOffset = options.reset === true || normalizedProjectId !== this.listProjectId
        const nextLimit = typeof options.limit === 'number' && options.limit > 0 ? options.limit : this.pagination.limit
        const nextOffset = shouldResetOffset ? 0 : Math.max(0, options.offset ?? this.pagination.offset)
        const response = await listTasks({
          projectId: normalizedProjectId,
          offset: nextOffset,
          limit: nextLimit,
        })
        this.tasks = response.items
        this.listProjectId = normalizedProjectId
        this.pagination = response.pagination
      } catch (error) {
        this.error = error instanceof Error ? error.message : translate('tasks.listLoadFailed')
      } finally {
        this.loading = false
      }
    },
    async loadPreviousTasks(projectId?: string | null): Promise<void> {
      if (this.pagination.offset <= 0) return
      await this.loadTasks(projectId, {
        offset: Math.max(0, this.pagination.offset - this.pagination.limit),
      })
    },
    async loadNextTasks(projectId?: string | null): Promise<void> {
      if (!this.pagination.hasMore) return
      await this.loadTasks(projectId, {
        offset: this.pagination.nextOffset ?? this.pagination.offset + this.pagination.limit,
      })
    },
    async loadTask(taskId: string): Promise<void> {
      this.detailLoading = true
      this.error = null
      try {
        this.selectedTask = await getTask(taskId)
        this.selectedTaskEvents = await getTaskEvents(taskId)
      } catch (error) {
        this.error = error instanceof Error ? error.message : translate('tasks.detailLoadFailed')
      } finally {
        this.detailLoading = false
      }
    },
    appendTaskEvent(event: TaskEvent): void {
      const eventKey = event.sequence ?? event.event_id ?? `${event.event_type}-${event.created_at ?? event.occurred_at}`
      const exists = this.selectedTaskEvents.some((currentEvent) => {
        const currentKey = currentEvent.sequence ?? currentEvent.event_id ?? `${currentEvent.event_type}-${currentEvent.created_at ?? currentEvent.occurred_at}`
        return currentKey === eventKey
      })
      if (!exists) {
        this.selectedTaskEvents.push(event)
      }
    },
    async cancelSelectedTask(): Promise<void> {
      if (!this.selectedTask) return
      this.selectedTask = await cancelTask(this.selectedTask.task_id)
    },
  },
})