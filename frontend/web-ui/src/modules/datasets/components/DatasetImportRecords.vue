<template>
  <section class="resource-section">
    <div class="section-heading">
      <div>
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
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import type { DatasetImportSummary } from '../services/dataset.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'

defineProps<{
  imports: DatasetImportSummary[]
  loading: boolean
  statusTone: (status: string | null | undefined) => 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}>()

const { t } = useI18n()
</script>
