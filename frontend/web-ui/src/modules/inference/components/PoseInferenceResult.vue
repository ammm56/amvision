<template>
  <div class="task-result-details">
    <div class="summary-grid">
      <div><span>{{ t('inferenceOps.fields.instanceCount') }}</span><strong>{{ result.instance_count }}</strong></div>
      <div><span>{{ t('inferenceOps.fields.keypointConfidenceThreshold') }}</span><strong>{{ result.keypoint_confidence_threshold }}</strong></div>
      <div><span>{{ t('inferenceOps.fields.inputSize') }}</span><strong>{{ result.image_width }} x {{ result.image_height }}</strong></div>
      <div><span>{{ t('inferenceOps.fields.latency') }}</span><strong>{{ result.latency_ms ?? '-' }}</strong></div>
    </div>
    <div v-if="result.instances.length" class="resource-table">
      <table>
        <thead><tr><th>#</th><th>{{ t('inferenceOps.fields.category') }}</th><th>{{ t('inferenceOps.fields.score') }}</th><th>{{ t('inferenceOps.fields.keypointCount') }}</th><th>{{ t('inferenceOps.fields.visibleKeypointCount') }}</th></tr></thead>
        <tbody>
          <tr v-for="(item, index) in result.instances" :key="`${item.class_id}-${index}`">
            <td>{{ index + 1 }}</td>
            <td>{{ item.class_name?.trim() || `#${item.class_id}` }}</td>
            <td>{{ item.score }}</td>
            <td>{{ item.keypoints.length }}</td>
            <td>{{ visibleKeypointCount(item.keypoints) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { PoseInferenceKeypoint, PoseInferencePayload } from '../services/inference.service'

const props = defineProps<{ result: PoseInferencePayload }>()
const { t } = useI18n()

function visibleKeypointCount(items: PoseInferenceKeypoint[]): number {
  return items.filter((item) => (item.confidence ?? 1) >= props.result.keypoint_confidence_threshold).length
}
</script>
