<template>
  <section class="resource-section">
    <div>
      <p class="page-kicker">{{ t('modelOps.conversionHistoryKicker') }}</p>
      <h2>{{ t('modelOps.conversionHistoryTitle') }}</h2>
    </div>
    <EmptyState
      v-if="!loading && conversionTasks.length === 0"
      :title="t('modelOps.emptyConversionTitle')"
      :description="t('modelOps.emptyConversionDescription')"
    />
    <div v-else class="resource-table">
      <table>
        <thead>
          <tr>
            <th>{{ t('modelOps.columns.task') }}</th>
            <th>{{ t('modelOps.columns.state') }}</th>
            <th>{{ t('modelOps.columns.sourceVersion') }}</th>
            <th>{{ t('modelOps.columns.targetFormat') }}</th>
            <th>{{ t('modelOps.columns.builds') }}</th>
            <th>{{ t('modelOps.columns.createdAt') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in conversionTasks" :key="task.task_id">
            <td>
              <RouterLink :to="`/tasks/${task.task_id}`">
                <strong>{{ task.display_name || task.task_id }}</strong>
              </RouterLink>
              <span>{{ task.task_id }}</span>
            </td>
            <td><StatusBadge :tone="statusTone(task.state)">{{ task.state }}</StatusBadge></td>
            <td>{{ task.source_model_version_id }}</td>
            <td>{{ (task.produced_formats.length ? task.produced_formats : task.target_formats).join(', ') || '-' }}</td>
            <td>{{ task.builds.map((build) => build.model_build_id).join(', ') || '-' }}</td>
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

import type { ModelConversionTaskSummary } from '../services/model.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

defineProps<{
  loading: boolean
  conversionTasks: ModelConversionTaskSummary[]
}>()

const { t } = useI18n()

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('complete') || normalized.includes('success') || normalized.includes('succeed')) return 'success'
  if (normalized.includes('fail') || normalized.includes('error')) return 'danger'
  if (normalized.includes('queue') || normalized.includes('pending')) return 'warning'
  if (normalized.includes('run') || normalized.includes('process')) return 'info'
  return 'neutral'
}
</script>
