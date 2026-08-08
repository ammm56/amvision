<template>
  <div class="task-result-details">
    <div class="summary-grid">
      <div>
        <span>{{ t('inferenceOps.fields.categoryCount') }}</span>
        <strong>{{ result.category_count }}</strong>
      </div>
      <div>
        <span>{{ t('inferenceOps.fields.topCategory') }}</span>
        <strong>{{ categoryName(result.top_category) }}</strong>
      </div>
      <div>
        <span>{{ t('inferenceOps.fields.topProbability') }}</span>
        <strong>{{ formatProbability(result.top_category?.probability) }}</strong>
      </div>
      <div>
        <span>{{ t('inferenceOps.fields.latency') }}</span>
        <strong>{{ result.latency_ms ?? '-' }}</strong>
      </div>
    </div>
    <div v-if="result.categories.length" class="resource-table">
      <table>
        <thead><tr><th>#</th><th>{{ t('inferenceOps.fields.category') }}</th><th>{{ t('inferenceOps.fields.probability') }}</th><th>Logit</th></tr></thead>
        <tbody>
          <tr v-for="(category, index) in result.categories" :key="`${category.class_id}-${index}`">
            <td>{{ index + 1 }}</td>
            <td>{{ categoryName(category) }}</td>
            <td>{{ formatProbability(category.probability) }}</td>
            <td>{{ category.logit ?? '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { ClassificationInferenceCategory, ClassificationInferencePayload } from '../services/inference.service'

defineProps<{ result: ClassificationInferencePayload }>()
const { t } = useI18n()

function categoryName(category: ClassificationInferenceCategory | null | undefined): string {
  if (!category) return '-'
  return category.class_name?.trim() || `#${category.class_id}`
}

function formatProbability(value: number | null | undefined): string {
  return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '-'
}
</script>
