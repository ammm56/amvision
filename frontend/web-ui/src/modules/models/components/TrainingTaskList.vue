<template>
  <section class="resource-section">
    <div>
      <h2>{{ t('modelOps.trainingHistoryTitle') }}</h2>
    </div>
    <EmptyState
      v-if="trainingTasks.length === 0"
      :title="t('modelOps.emptyTrainingTitle')"
      :description="t('modelOps.emptyTrainingDescription')"
    />
    <div v-else class="resource-table">
      <table>
        <thead>
          <tr>
            <th>{{ t('modelOps.columns.task') }}</th>
            <th>{{ t('modelOps.columns.state') }}</th>
            <th>{{ t('modelOps.columns.progress') }}</th>
            <th>{{ t('modelOps.columns.outputModel') }}</th>
            <th>{{ t('modelOps.columns.modelVersion') }}</th>
            <th>{{ t('modelOps.columns.createdAt') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in trainingTasks" :key="task.task_id">
            <td>
              <RouterLink :to="`/models/${selectedTaskType}/training-tasks/${task.task_id}`">
                <strong>{{ task.display_name || task.task_id }}</strong>
              </RouterLink>
              <span>{{ task.dataset_export_id || task.dataset_export_manifest_key }}</span>
            </td>
            <td><TaskStateBadge :state="task.state" /></td>
            <td>
              <TaskProgress
                compact
                :percent="progressPercent(task.progress)"
                :aria-label="t('modelOps.columns.progress')"
              />
            </td>
            <td>{{ task.output_model_name || '-' }}</td>
            <td>{{ task.model_version_id || task.latest_checkpoint_model_version_id || '-' }}</td>
            <td>{{ formatSystemDateTime(task.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import type { ModelTaskType, ModelTrainingTaskSummary } from '../services/model.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import TaskProgress from '@/modules/tasks/components/TaskProgress.vue'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'

defineProps<{
  selectedTaskType: ModelTaskType
  trainingTasks: ModelTrainingTaskSummary[]
}>()

const { t } = useI18n()

function progressPercent(progress: Record<string, unknown>): number | null {
  const value = progress.percent ?? progress.progress_percent ?? progress.progress
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}
</script>
