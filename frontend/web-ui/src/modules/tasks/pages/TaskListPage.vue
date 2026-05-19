<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { RefreshCw } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import TaskStatusBadge from '../components/TaskStatusBadge.vue'
import { getTaskProgressPercent, useTaskStore } from '../stores/task.store'
import { useProjectStore } from '@/app/stores/project.store'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

const taskStore = useTaskStore()
const projectStore = useProjectStore()
const { t } = useI18n()

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
        <p class="page-kicker">{{ t('tasks.kicker') }}</p>
        <h1>{{ t('tasks.title') }}</h1>
      </div>
      <Button variant="secondary" @click="refreshTasks">
        <RefreshCw :size="16" />
        {{ t('common.refresh') }}
      </Button>
    </header>

    <InlineError :message="taskStore.error" />

    <EmptyState
      v-if="!taskStore.loading && taskStore.tasks.length === 0"
      :title="t('tasks.emptyTitle')"
      :description="t('tasks.emptyDescription')"
    />

    <div v-else class="resource-table">
      <table>
        <thead>
          <tr>
            <th>{{ t('tasks.columns.task') }}</th>
            <th>{{ t('tasks.columns.type') }}</th>
            <th>{{ t('tasks.columns.state') }}</th>
            <th>{{ t('tasks.columns.progress') }}</th>
            <th>{{ t('tasks.columns.updatedAt') }}</th>
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