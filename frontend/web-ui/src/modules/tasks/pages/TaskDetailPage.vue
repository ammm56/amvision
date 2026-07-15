<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('tasks.detailKicker') }}</p>
        <h1>{{ taskStore.selectedTask?.task_id || taskId }}</h1>
      </div>
      <div class="page-actions">
        <Button variant="secondary" :disabled="isTaskDetailLoading" @click="loadTaskDetail(taskId)">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
        <Button v-if="canCancel" variant="danger" @click="taskStore.cancelSelectedTask()">
          <Ban :size="16" />
          {{ t('common.cancel') }}
        </Button>
      </div>
    </header>

    <InlineError :message="taskStore.error" />

    <LoadingPanel
      v-if="isTaskDetailLoading && !taskStore.selectedTask"
      :title="t('tasks.loadingDetailTitle')"
      :description="t('tasks.loadingDetailDescription')"
    />

    <div v-else-if="taskStore.selectedTask" class="detail-layout task-detail-layout">
      <section class="detail-main">
        <div class="summary-grid">
          <div>
            <span>{{ t('tasks.columns.state') }}</span>
            <TaskStatusBadge :task="taskStore.selectedTask" />
          </div>
          <div>
            <span>{{ t('tasks.columns.type') }}</span>
            <strong>{{ taskStore.selectedTask.task_kind || taskStore.selectedTask.kind || '-' }}</strong>
          </div>
          <div>
            <span>{{ t('tasks.columns.progress') }}</span>
            <strong>{{ getTaskProgressPercent(taskStore.selectedTask) }}%</strong>
          </div>
          <div>
            <span>{{ t('common.project') }}</span>
            <strong>{{ taskStore.selectedTask.project_id || '-' }}</strong>
          </div>
        </div>

        <section class="panel-section">
          <h2>{{ t('tasks.events') }}</h2>
          <div v-if="isTaskDetailLoading" class="task-detail-loading">
            <LoadingPanel
              compact
              :title="t('tasks.loadingDetailTitle')"
              :description="t('tasks.loadingDetailDescription')"
            />
          </div>
          <TaskEventTimeline v-else :events="taskStore.selectedTaskEvents" />
        </section>
      </section>

      <aside class="detail-side task-diagnostics-panel">
        <div class="task-diagnostics-panel__header">
          <h2>{{ t('tasks.diagnostics') }}</h2>
        </div>
        <dl class="task-diagnostics-panel__list">
          <div>
            <dt>{{ t('common.websocket') }}</dt>
            <dd>
              <span
                class="status-badge"
                :class="taskEvents.streamState.value?.connected ? 'status-badge--success' : 'status-badge--neutral'"
              >
                {{ taskEvents.streamState.value?.connected ? t('tasks.connected') : t('tasks.notConnected') }}
              </span>
            </dd>
          </div>
          <div>
            <dt>{{ t('tasks.lastDisconnect') }}</dt>
            <dd>{{ taskEvents.streamState.value?.lastDisconnectReason || '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('tasks.error') }}</dt>
            <dd>{{ taskStore.selectedTask.error_message || '-' }}</dd>
          </div>
          <div v-if="taskDiagnosticErrorText">
            <dt>{{ t('tasks.errorDetails') }}</dt>
            <dd>
              <pre class="task-diagnostics-panel__error-json">{{ taskDiagnosticErrorText }}</pre>
            </dd>
          </div>
        </dl>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Ban, RefreshCw } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import TaskEventTimeline from '../components/TaskEventTimeline.vue'
import TaskStatusBadge from '../components/TaskStatusBadge.vue'
import { getTaskProgressPercent, normalizeTaskState, useTaskStore } from '../stores/task.store'
import { useTaskEvents } from '../composables/useTaskEvents'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import LoadingPanel from '@/shared/ui/feedback/LoadingPanel.vue'
import type { TaskEvent } from '@/shared/contracts'

type JsonRecord = Record<string, unknown>

const route = useRoute()
const taskStore = useTaskStore()
const { t } = useI18n()
const taskId = computed(() => String(route.params.taskId))
const eventLoadingVisible = ref(false)
const isTaskDetailLoading = computed(() => taskStore.detailLoading || eventLoadingVisible.value)

const MIN_EVENT_LOADING_MS = 1500
let eventLoadingStartedAt = 0
let eventLoadingTimer: ReturnType<typeof window.setTimeout> | null = null
let taskLoadSequence = 0

const taskEvents = useTaskEvents(() => taskId.value, (event) => taskStore.appendTaskEvent(event))

const canCancel = computed(() => {
  if (!taskStore.selectedTask) return false
  const state = normalizeTaskState(taskStore.selectedTask)
  return state === 'queued' || state === 'running'
})

const taskDiagnosticErrorText = computed(() => {
  const errorPayload = resolveTaskDiagnosticError()
  return errorPayload === null ? '' : stringifyDiagnosticValue(errorPayload)
})

function asRecord(value: unknown): JsonRecord | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  return value as JsonRecord
}

function resolveTaskDiagnosticError(): unknown | null {
  const task = taskStore.selectedTask
  if (!task) {
    return null
  }

  const taskResult = asRecord(task.result)
  const resultError = asRecord(taskResult?.error)
  if (resultError) {
    return resultError
  }
  if (taskResult?.error_details !== undefined && taskResult.error_details !== null) {
    return {
      error_message: taskResult.error_message ?? task.error_message ?? null,
      details: taskResult.error_details,
    }
  }

  const metadataError = asRecord(task.metadata?.error)
  if (metadataError) {
    return metadataError
  }

  return resolveLatestEventDiagnosticError(taskStore.selectedTaskEvents)
}

function resolveLatestEventDiagnosticError(events: TaskEvent[]): unknown | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const errorPayload = resolveEventDiagnosticError(events[index])
    if (errorPayload !== null) {
      return errorPayload
    }
  }
  return null
}

function resolveEventDiagnosticError(event: TaskEvent): unknown | null {
  const payload = asRecord(event.payload)
  if (!payload) {
    return null
  }

  const directError = asRecord(payload.error)
  if (directError) {
    return directError
  }

  const result = asRecord(payload.result)
  const resultError = asRecord(result?.error)
  if (resultError) {
    return resultError
  }

  const metadata = asRecord(payload.metadata)
  const metadataError = asRecord(metadata?.error)
  if (metadataError) {
    return metadataError
  }

  if (payload.error_details !== undefined && payload.error_details !== null) {
    return {
      error_message: payload.error_message ?? event.message ?? null,
      details: payload.error_details,
    }
  }
  return null
}

function stringifyDiagnosticValue(value: unknown): string {
  if (typeof value === 'string') {
    return value
  }
  try {
    return JSON.stringify(value, null, 2) ?? ''
  } catch {
    return String(value)
  }
}

function clearEventLoadingTimer(): void {
  if (eventLoadingTimer !== null) {
    window.clearTimeout(eventLoadingTimer)
    eventLoadingTimer = null
  }
}

function showEventLoading(): void {
  clearEventLoadingTimer()
  eventLoadingStartedAt = Date.now()
  eventLoadingVisible.value = true
}

function hideEventLoadingAfterMinimum(loadSequence: number): void {
  const elapsed = Date.now() - eventLoadingStartedAt
  const remaining = Math.max(0, MIN_EVENT_LOADING_MS - elapsed)
  eventLoadingTimer = window.setTimeout(() => {
    if (loadSequence === taskLoadSequence) {
      eventLoadingVisible.value = false
    }
    eventLoadingTimer = null
  }, remaining)
}

async function loadTaskDetail(nextTaskId: string): Promise<void> {
  const loadSequence = ++taskLoadSequence
  showEventLoading()
  await taskStore.loadTask(nextTaskId)
  hideEventLoadingAfterMinimum(loadSequence)
}

onMounted(async () => {
  await loadTaskDetail(taskId.value)
  taskEvents.start()
})

watch(taskId, async (nextTaskId) => {
  taskEvents.stop()
  await loadTaskDetail(nextTaskId)
  taskEvents.start()
})

onBeforeUnmount(() => {
  clearEventLoadingTimer()
  taskEvents.stop()
})
</script>

<style scoped>
.task-detail-layout {
  align-items: start;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 300px);
}

.task-detail-loading {
  margin: 12px 0 16px;
}

.task-diagnostics-panel {
  align-self: start;
  padding: 16px;
}

.task-diagnostics-panel__header h2 {
  margin: 0;
  margin-bottom: 14px;
}

.task-diagnostics-panel__list {
  display: grid;
  gap: 10px;
  margin: 0;
}

.task-diagnostics-panel__list > div {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--summary-bg);
}

.task-diagnostics-panel__list dt {
  display: block;
  margin-bottom: 4px;
  color: var(--muted);
  font-size: 12px;
}

.task-diagnostics-panel__list dd {
  margin: 0;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.task-diagnostics-panel__error-json {
  max-height: 360px;
  margin: 0;
  padding: 10px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.45;
  white-space: pre-wrap;
}

@media (max-width: 900px) {
  .task-detail-layout {
    grid-template-columns: 1fr;
  }
}
</style>
