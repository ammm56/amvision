<template>
  <section class="resource-section">
    <div class="section-heading">
      <div>
        <h2>{{ t('datasetOps.importHistoryTitle') }}</h2>
      </div>
    </div>
    <EmptyState v-if="imports.length === 0" :title="t('datasetOps.emptyImportsTitle')" :description="t('datasetOps.emptyImportsDescription')" />
    <div v-else class="resource-table">
      <table>
        <thead>
          <tr>
            <th>{{ t('datasetOps.columns.importId') }}</th>
            <th>{{ t('datasetOps.columns.status') }}</th>
            <th>{{ t('datasetOps.columns.version') }}</th>
            <th>{{ t('datasetOps.columns.format') }}</th>
            <th>{{ t('datasetOps.columns.createdAt') }}</th>
            <th>{{ t('datasetOps.columns.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in imports" :key="item.dataset_import_id">
            <td>
              <RouterLink :to="`/datasets/imports/${item.dataset_import_id}`"><strong>{{ item.dataset_import_id }}</strong></RouterLink>
              <span>{{ item.package_path }}</span>
            </td>
            <td><TaskStateBadge :state="item.processing_state || item.status" /></td>
            <td>{{ item.dataset_version_id || '-' }}</td>
            <td>{{ item.format_type || '-' }}</td>
            <td>{{ formatSystemDateTime(item.created_at) }}</td>
            <td><ResourceDeleteButton kind="dataset-import" :resource-id="item.dataset_import_id" :project-id="item.project_id" :disabled="!['completed', 'failed'].includes(item.status)" @accepted="$emit('changed')" /></td>
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
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import ResourceDeleteButton from '@/shared/ui/components/ResourceDeleteButton.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'

defineProps<{
  imports: DatasetImportSummary[]
}>()

defineEmits<{ changed: [] }>()
const { t } = useI18n()
</script>

<style scoped>
.resource-table table { min-width: 800px; }
.resource-table th:first-child { width: 42%; }
.resource-table td:first-child { overflow-wrap: anywhere; }
.resource-table td:nth-child(4), .resource-table td:last-child { white-space: nowrap; }
</style>
