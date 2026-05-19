import { defineStore } from 'pinia'

import { cancelTask, getTask, getTaskEvents, listTasks } from '../services/task.service'
import type { TaskEvent, TaskRecord, TaskState } from '@/shared/contracts'
import { translate } from '@/platform/i18n'

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
    loading: false,
    detailLoading: false,
    error: null as string | null,
  }),
  actions: {
    async loadTasks(projectId?: string | null): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await listTasks(projectId)
        this.tasks = response.items
      } catch (error) {
        this.error = error instanceof Error ? error.message : translate('tasks.listLoadFailed')
      } finally {
        this.loading = false
      }
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