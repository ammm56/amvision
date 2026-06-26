<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('tasks.detailKicker') }}</p>
        <h1>{{ taskStore.selectedTask?.task_id || taskId }}</h1>
      </div>
      <div class="page-actions">
        <Button variant="secondary" :disabled="taskStore.detailLoading" @click="taskStore.loadTask(taskId)">
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
      v-if="taskStore.detailLoading && !taskStore.selectedTask"
      :title="t('tasks.loadingDetailTitle')"
      :description="t('tasks.loadingDetailDescription')"
    />

    <div v-else-if="taskStore.selectedTask" class="detail-layout">
      <section class="detail-main">
        <div v-if="taskStore.detailLoading" class="task-detail-loading">
          <LoadingPanel
            compact
            :title="t('tasks.loadingDetailTitle')"
            :description="t('tasks.loadingDetailDescription')"
          />
        </div>

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
          <TaskEventTimeline :events="taskStore.selectedTaskEvents" />
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
import { computed, onMounted, watch } from 'vue'
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

const taskEvents = useTaskEvents(() => taskId.value, (event) => taskStore.appendTaskEvent(event))

const canCancel = computed(() => {
  if (!taskStore.selectedTask) return false
  const state = normalizeTaskState(taskStore.selectedTask)
  return state === 'queued' || state === 'running'
})

onMounted(async () => {
  await taskStore.loadTask(taskId.value)
  taskEvents.start()
})

watch(taskId, async (nextTaskId) => {
  taskEvents.stop()
  await taskStore.loadTask(nextTaskId)
  taskEvents.start()
})
</script>

<style scoped>
.task-detail-loading {
  margin-bottom: 16px;
}
</style>
