<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Ban, RefreshCw } from '@lucide/vue'

import TaskEventTimeline from '../components/TaskEventTimeline.vue'
import TaskStatusBadge from '../components/TaskStatusBadge.vue'
import { getTaskProgressPercent, normalizeTaskState, useTaskStore } from '../stores/task.store'
import { useTaskEvents } from '../composables/useTaskEvents'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

const route = useRoute()
const taskStore = useTaskStore()
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

<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">Task Detail</p>
        <h1>{{ taskStore.selectedTask?.task_id || taskId }}</h1>
      </div>
      <div class="page-actions">
        <Button variant="secondary" @click="taskStore.loadTask(taskId)">
          <RefreshCw :size="16" />
          刷新
        </Button>
        <Button v-if="canCancel" variant="danger" @click="taskStore.cancelSelectedTask()">
          <Ban :size="16" />
          取消
        </Button>
      </div>
    </header>

    <InlineError :message="taskStore.error" />

    <div v-if="taskStore.selectedTask" class="detail-layout">
      <section class="detail-main">
        <div class="summary-grid">
          <div>
            <span>状态</span>
            <TaskStatusBadge :task="taskStore.selectedTask" />
          </div>
          <div>
            <span>类型</span>
            <strong>{{ taskStore.selectedTask.task_kind || taskStore.selectedTask.kind || '-' }}</strong>
          </div>
          <div>
            <span>进度</span>
            <strong>{{ getTaskProgressPercent(taskStore.selectedTask) }}%</strong>
          </div>
          <div>
            <span>Project</span>
            <strong>{{ taskStore.selectedTask.project_id || '-' }}</strong>
          </div>
        </div>

        <section class="panel-section">
          <h2>事件</h2>
          <TaskEventTimeline :events="taskStore.selectedTaskEvents" />
        </section>
      </section>

      <aside class="detail-side">
        <h2>诊断</h2>
        <dl>
          <dt>WebSocket</dt>
          <dd>{{ taskEvents.streamState.value?.connected ? 'connected' : 'not connected' }}</dd>
          <dt>最近断开</dt>
          <dd>{{ taskEvents.streamState.value?.lastDisconnectReason || '-' }}</dd>
          <dt>错误</dt>
          <dd>{{ taskStore.selectedTask.error_message || '-' }}</dd>
        </dl>
      </aside>
    </div>
  </section>
</template>