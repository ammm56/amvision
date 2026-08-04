<template>
  <section class="page-stack">
    <PageHeader :title="taskStore.selectedTask?.task_id || taskId">
      <template #actions>
        <Button variant="secondary" :disabled="isTaskDetailLoading" :loading="isTaskDetailLoading" @click="loadTaskDetail(taskId)">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
        <Button v-if="canCancel" variant="danger" @click="taskStore.cancelSelectedTask()">
          <Ban :size="16" />
          {{ t('common.cancel') }}
        </Button>
      </template>
    </PageHeader>

    <InlineError :message="taskStore.error" />
    <InlineMessage
      v-if="showStreamWarning"
      tone="warning"
      :title="t('tasks.streamInterruptedTitle')"
      :message="t('tasks.streamInterruptedDescription')"
    />

    <LoadingPanel
      v-if="isTaskDetailLoading && !taskStore.selectedTask"
      :title="t('tasks.loadingDetailTitle')"
      :description="t('tasks.loadingDetailDescription')"
    />

    <div
      v-else-if="taskStore.selectedTask"
      class="detail-layout task-detail-layout"
      :class="{ 'task-detail-layout--with-error': hasTaskError }"
    >
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
            <TaskProgress
              compact
              :percent="getTaskProgressPercent(taskStore.selectedTask)"
              :aria-label="t('tasks.columns.progress')"
            />
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

      <aside v-if="hasTaskError" class="detail-side task-error-panel">
        <h2>{{ t('tasks.error') }}</h2>
        <InlineMessage
          v-if="taskStore.selectedTask.error_message"
          tone="danger"
          :message="taskStore.selectedTask.error_message"
        />
        <div v-if="taskStatusErrorText" class="task-error-panel__details">
          <h3>{{ t('tasks.errorDetails') }}</h3>
          <pre class="task-status-panel__error-json">{{ taskStatusErrorText }}</pre>
        </div>
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
import TaskProgress from '../components/TaskProgress.vue'
import TaskStatusBadge from '../components/TaskStatusBadge.vue'
import { getTaskProgressPercent, normalizeTaskState, useTaskStore } from '../stores/task.store'
import { useTaskEvents } from '../composables/useTaskEvents'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'
import LoadingPanel from '@/shared/ui/feedback/LoadingPanel.vue'
import PageHeader from '@/shared/ui/layout/PageHeader.vue'
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

const showStreamWarning = computed(() => {
  const streamState = taskEvents.streamState.value
  if (!streamState || streamState.connected) return false
  if (!streamState.stale && !streamState.lastDisconnectReason && !streamState.lastError) return false
  const task = taskStore.selectedTask
  if (!task) return false
  const state = normalizeTaskState(task)
  return state === 'queued' || state === 'running'
})

const taskStatusErrorText = computed(() => {
  const errorPayload = resolveTaskStatusError()
  return errorPayload === null ? '' : stringifyStatusValue(errorPayload)
})
const hasTaskError = computed(() => Boolean(taskStore.selectedTask?.error_message || taskStatusErrorText.value))

function asRecord(value: unknown): JsonRecord | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  return value as JsonRecord
}

function resolveTaskStatusError(): unknown | null {
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

  return resolveLatestEventStatusError(taskStore.selectedTaskEvents)
}

function resolveLatestEventStatusError(events: TaskEvent[]): unknown | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const errorPayload = resolveEventStatusError(events[index])
    if (errorPayload !== null) {
      return errorPayload
    }
  }
  return null
}

function resolveEventStatusError(event: TaskEvent): unknown | null {
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

function stringifyStatusValue(value: unknown): string {
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
  grid-template-columns: minmax(0, 1fr);
}

.task-detail-layout--with-error {
  grid-template-columns: minmax(0, 1fr) minmax(260px, 300px);
}

.task-detail-loading {
  margin: 12px 0 16px;
}

.task-error-panel {
  display: grid;
  gap: var(--am-space-lg);
  align-self: start;
  padding: 16px;
}

.task-error-panel h2,
.task-error-panel h3 {
  margin: 0;
}

.task-error-panel h3 {
  color: var(--am-text-muted);
  font-size: 13px;
}

.task-error-panel__details {
  display: grid;
  gap: var(--am-space-sm);
}

.task-status-panel__error-json {
  max-height: 360px;
  margin: 0;
  padding: 10px;
  overflow: auto;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-surface);
  color: var(--am-text);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.45;
  white-space: pre-wrap;
}

@media (max-width: 900px) {
  .task-detail-layout--with-error {
    grid-template-columns: 1fr;
  }
}
</style>
