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

    <div v-else-if="taskStore.selectedTask" class="detail-layout">
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

      <aside class="detail-side">
        <h2>{{ t('tasks.diagnostics') }}</h2>
        <dl>
          <dt>{{ t('common.websocket') }}</dt>
          <dd>{{ taskEvents.streamState.value?.connected ? t('tasks.connected') : t('tasks.notConnected') }}</dd>
          <dt>{{ t('tasks.lastDisconnect') }}</dt>
          <dd>{{ taskEvents.streamState.value?.lastDisconnectReason || '-' }}</dd>
          <dt>{{ t('tasks.error') }}</dt>
          <dd>{{ taskStore.selectedTask.error_message || '-' }}</dd>
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

const route = useRoute()
const taskStore = useTaskStore()
const { t } = useI18n()
const taskId = computed(() => String(route.params.taskId))
const eventLoadingVisible = ref(false)
const isTaskDetailLoading = computed(() => taskStore.detailLoading || eventLoadingVisible.value)

const MIN_EVENT_LOADING_MS = 2000
let eventLoadingStartedAt = 0
let eventLoadingTimer: ReturnType<typeof window.setTimeout> | null = null
let taskLoadSequence = 0

const taskEvents = useTaskEvents(() => taskId.value, (event) => taskStore.appendTaskEvent(event))

const canCancel = computed(() => {
  if (!taskStore.selectedTask) return false
  const state = normalizeTaskState(taskStore.selectedTask)
  return state === 'queued' || state === 'running'
})

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
})
</script>

<style scoped>
.task-detail-loading {
  margin: 12px 0 16px;
}
</style>
