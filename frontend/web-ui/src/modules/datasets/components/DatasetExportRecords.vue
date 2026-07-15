<template>
  <section class="resource-section">
    <div class="section-heading">
      <div>
        <p class="page-kicker">{{ t('datasetOps.exportHistoryKicker') }}</p>
        <h2>{{ t('datasetOps.exportHistoryTitle') }}</h2>
      </div>
    </div>
    <EmptyState v-if="!loading && exports.length === 0" :title="t('datasetOps.emptyExportsTitle')" :description="t('datasetOps.emptyExportsDescription')" />
    <div v-else class="resource-table">
      <table>
        <thead>
          <tr>
            <th>{{ t('datasetOps.columns.exportId') }}</th>
            <th>{{ t('datasetOps.columns.status') }}</th>
            <th>{{ t('datasetOps.columns.format') }}</th>
            <th>{{ t('datasetOps.columns.samples') }}</th>
            <th>{{ t('datasetOps.columns.package') }}</th>
            <th>{{ t('datasetOps.columns.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in exports" :key="item.dataset_export_id">
            <td>
              <RouterLink :to="`/datasets/exports/${item.dataset_export_id}`"><strong>{{ item.dataset_export_id }}</strong></RouterLink>
              <span>{{ item.dataset_version_id }}</span>
            </td>
            <td><StatusBadge :tone="statusTone(item.status)">{{ item.status }}</StatusBadge></td>
            <td>{{ item.format_id }}</td>
            <td>{{ item.sample_count }}</td>
            <td>{{ item.package_file_name || item.package_object_key || '-' }}</td>
            <td>
              <div class="table-actions">
                <Button
                  size="sm"
                  variant="secondary"
                  :disabled="!canWriteDatasets || packagingExportId === item.dataset_export_id"
                  @click="$emit('package', item.dataset_export_id)"
                >
                  <PackageCheck :size="14" />
                  {{ t('datasetOps.actions.package') }}
                </Button>
                <Button size="sm" variant="ghost" :disabled="!item.package_object_key" @click="$emit('download', item)">
                  <Download :size="14" />
                  {{ t('datasetOps.actions.download') }}
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  :disabled="!canWriteDatasets || deletingExportId === item.dataset_export_id || !canDeleteExport(item)"
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
import { Download, PackageCheck, Trash2 } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import type { DatasetExportSummary } from '../services/dataset.service'
import Button from '@/shared/ui/components/Button.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'

defineProps<{
  exports: DatasetExportSummary[]
  loading: boolean
  canWriteDatasets: boolean
  packagingExportId: string | null
  deletingExportId: string | null
  statusTone: (status: string | null | undefined) => 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}>()

defineEmits<{
  package: [datasetExportId: string]
  download: [datasetExport: DatasetExportSummary]
  delete: [datasetExport: DatasetExportSummary]
}>()

const { t } = useI18n()

function canDeleteExport(datasetExport: DatasetExportSummary): boolean {
  const normalized = datasetExport.status.toLowerCase()
  return normalized === 'completed' || normalized === 'failed'
}
</script>
