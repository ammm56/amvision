<template>
  <section class="model-evaluations">
    <DetectionEvaluationPanel v-if="kind === 'detection'" v-bind="props" @focus-mode="setFocusMode">
      <template #task-type>
        <Select :model-value="kind" :options="evaluationTypeOptions(zh)" :aria-label="zh ? '评估任务类型' : 'Evaluation task type'" @update:model-value="changeKind" />
      </template>
    </DetectionEvaluationPanel>
    <template v-else-if="supported">
      <Select v-show="!focusMode" :model-value="kind" :options="evaluationTypeOptions(zh)" :aria-label="zh ? '评估任务类型' : 'Evaluation task type'" @update:model-value="changeKind" />
      <AdditionalEvaluationPanel :key="kind" :project-id="projectId" :zh="zh" :can-write="canWrite" :kind="supported" />
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Select from '@/shared/ui/components/Select.vue'
import { evaluationTypeOptions, evaluationTypes } from '../model-evaluation-types'
import { additionalEvaluationKinds, type AdditionalEvaluationKind } from '../services/model-evaluation.service'
import DetectionEvaluationPanel from './DetectionEvaluationPanel.vue'
import AdditionalEvaluationPanel from './AdditionalEvaluationPanel.vue'

const props = defineProps<{ projectId: string; zh: boolean; canWrite: boolean }>()
const emit = defineEmits<{ focusMode: [active: boolean] }>()
const focusMode = ref(false)
function setFocusMode(active: boolean): void {
  focusMode.value = active
  emit('focusMode', active)
}
const route = useRoute()
const router = useRouter()
const kind = computed(() => {
  const value = route?.query.evaluation
  return typeof value === 'string' && Object.hasOwn(evaluationTypes, value) ? value : 'detection'
})
const supported = computed(() => additionalEvaluationKinds.find(value => value === kind.value))
function changeKind(value: unknown): void {
  if (typeof value !== 'string') return
  if (value === 'detection' || additionalEvaluationKinds.includes(value as AdditionalEvaluationKind)) {
    void router.replace({ query: { ...route.query, tab: 'evaluation', evaluation: value } })
  }
}
</script>

<style scoped>
.model-evaluations { display:grid; gap:16px; min-width:0; }
.model-evaluations > .ui-select { width:min(100%, 250px); }
</style>
