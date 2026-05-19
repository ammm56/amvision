<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { RefreshCw } from '@lucide/vue'

import TaskStatusBadge from '../components/TaskStatusBadge.vue'
import { getTaskProgressPercent, useTaskStore } from '../stores/task.store'
import { useProjectStore } from '@/app/stores/project.store'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

const taskStore = useTaskStore()
const projectStore = useProjectStore()

onMounted(() => {
  void taskStore.loadTasks(projectStore.selectedProjectId)
})

watch(
  () => projectStore.selectedProjectId,
  (projectId) => {
    void taskStore.loadTasks(projectId)
  },
)

function refreshTasks(): void {
  void taskStore.loadTasks(projectStore.selectedProjectId)
}
</script>

<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">Operations</p>
        <h1>任务</h1>
      </div>
      <Button variant="secondary" @click="refreshTasks">
        <RefreshCw :size="16" />
        刷新
      </Button>
    </header>

    <InlineError :message="taskStore.error" />

    <EmptyState v-if="!taskStore.loading && taskStore.tasks.length === 0" title="暂无任务" description="训练、转换、部署、推理和 workflow 调用任务会在这里汇总。" />

    <div v-else class="resource-table">
      <table>
        <thead>
          <tr>
            <th>任务</th>
            <th>类型</th>
            <th>状态</th>
            <th>进度</th>
            <th>更新时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in taskStore.tasks" :key="task.task_id">
            <td>
              <RouterLink :to="`/tasks/${task.task_id}`">{{ task.task_id }}</RouterLink>
            </td>
            <td>{{ task.task_kind || task.kind || '-' }}</td>
            <td><TaskStatusBadge :task="task" /></td>
            <td>{{ getTaskProgressPercent(task) }}%</td>
            <td>{{ task.updated_at || task.created_at || '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>