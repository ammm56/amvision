<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('tasks.kicker') }}</p>
        <h1>{{ t('tasks.title') }}</h1>
      </div>
      <Button variant="secondary" :disabled="taskStore.loading" @click="refreshTasks">
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
            <td>{{ formatSystemDateTime(task.updated_at || task.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <PaginationControls
      v-if="taskStore.tasks.length > 0"
      class="task-list__pagination"
      :offset="taskStore.pagination.offset"
      :limit="taskStore.pagination.limit"
      :item-count="taskStore.tasks.length"
      :total-count="taskStore.pagination.totalCount"
      :has-more="taskStore.pagination.hasMore"
      :disabled="taskStore.loading"
      @previous="loadPreviousPage"
      @next="loadNextPage"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useRoute, useRouter } from 'vue-router'
import { RefreshCw } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import TaskStatusBadge from '../components/TaskStatusBadge.vue'
import { DEFAULT_TASK_PAGE_SIZE, getTaskProgressPercent, useTaskStore } from '../stores/task.store'
import { useProjectStore } from '@/app/stores/project.store'
import Button from '@/shared/ui/components/Button.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'

const taskStore = useTaskStore()
const projectStore = useProjectStore()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const currentPage = computed(() => parsePositiveInteger(route.query.page, 1))

watch(
  () => [projectStore.selectedProjectId, currentPage.value] as const,
  (currentValue, previousValue) => {
    const [projectId, page] = currentValue
    const previousProjectId = previousValue?.[0]
    if (projectId !== previousProjectId && page !== 1) {
      void updatePageQuery(1)
      return
    }
    void taskStore.loadTasks(projectId, {
      offset: Math.max(0, (page - 1) * DEFAULT_TASK_PAGE_SIZE),
      limit: DEFAULT_TASK_PAGE_SIZE,
      reset: projectId !== previousProjectId,
    })
  },
  { immediate: true },
)

function refreshTasks(): void {
  void taskStore.loadTasks(projectStore.selectedProjectId, {
    offset: Math.max(0, (currentPage.value - 1) * DEFAULT_TASK_PAGE_SIZE),
    limit: DEFAULT_TASK_PAGE_SIZE,
  })
}

function loadPreviousPage(): void {
  void updatePageQuery(Math.max(1, currentPage.value - 1))
}

function loadNextPage(): void {
  void updatePageQuery(currentPage.value + 1)
}

function parsePositiveInteger(value: unknown, fallback: number): number {
  const normalizedValue = Array.isArray(value) ? value[0] : value
  const parsedValue = Number(normalizedValue)
  return Number.isInteger(parsedValue) && parsedValue > 0 ? parsedValue : fallback
}

async function updatePageQuery(page: number): Promise<void> {
  await router.replace({
    query: {
      ...route.query,
      page: page > 1 ? String(page) : undefined,
    },
  })
}
</script>

<style scoped>
.task-list__pagination {
  margin-top: 16px;
}
</style>