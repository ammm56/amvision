<template>
  <section class="resource-section">
    <div class="section-heading">
      <div>
        <p class="page-kicker">{{ t('datasetOps.importHistoryKicker') }}</p>
        <h2>{{ t('datasetOps.importHistoryTitle') }}</h2>
      </div>
    </div>
    <EmptyState v-if="!loading && imports.length === 0" :title="t('datasetOps.emptyImportsTitle')" :description="t('datasetOps.emptyImportsDescription')" />
    <div v-else class="resource-table">
      <table>
        <thead>
          <tr>
            <th>{{ t('datasetOps.columns.importId') }}</th>
            <th>{{ t('datasetOps.columns.status') }}</th>
            <th>{{ t('datasetOps.columns.version') }}</th>
            <th>{{ t('datasetOps.columns.format') }}</th>
            <th>{{ t('datasetOps.columns.createdAt') }}</th>
            <th>{{ t('datasetOps.columns.task') }}</th>
            <th>{{ t('datasetOps.columns.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in imports" :key="item.dataset_import_id">
            <td>
              <RouterLink :to="`/datasets/imports/${item.dataset_import_id}`"><strong>{{ item.dataset_import_id }}</strong></RouterLink>
              <span>{{ item.package_path }}</span>
            </td>
            <td><StatusBadge :tone="statusTone(item.processing_state || item.status)">{{ item.processing_state || item.status }}</StatusBadge></td>
            <td>{{ item.dataset_version_id || '-' }}</td>
            <td>{{ item.format_type || '-' }}</td>
            <td>{{ formatSystemDateTime(item.created_at) }}</td>
            <td>
              <RouterLink v-if="item.task_id" :to="`/tasks/${item.task_id}`">{{ item.task_id }}</RouterLink>
              <span v-else>-</span>
            </td>
            <td>
              <div class="table-actions">
                <Button
                  size="sm"
                  variant="danger"
                  :disabled="!canWriteDatasets || deletingImportId === item.dataset_import_id || !canDeleteImport(item)"
                  @click="$emit('delete', item)"
                >
                  <Trash2 :size="14" />
                  {{ t('datasetOps.actions.delete') }}
                </Button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { Trash2 } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import type { DatasetImportSummary } from '../services/dataset.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'

defineProps<{
  imports: DatasetImportSummary[]
  loading: boolean
  canWriteDatasets: boolean
  deletingImportId: string | null
  statusTone: (status: string | null | undefined) => 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}>()

defineEmits<{
  delete: [datasetImport: DatasetImportSummary]
}>()

const { t } = useI18n()

function canDeleteImport(datasetImport: DatasetImportSummary): boolean {
  const normalized = (datasetImport.processing_state || datasetImport.status || '').toLowerCase()
  return normalized === 'completed' || normalized === 'failed'
}
</script>
