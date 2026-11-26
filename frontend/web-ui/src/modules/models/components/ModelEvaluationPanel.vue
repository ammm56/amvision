<template>
  <section class="model-evaluations">
    <DetectionEvaluationPanel v-if="kind === 'detection'" ref="detectionPanelRef" v-bind="props" @focus-mode="setFocusMode">
      <template #task-type>
        <Select :model-value="kind" :options="evaluationTypeOptions(zh)" :aria-label="zh ? '评估任务类型' : 'Evaluation task type'" @update:model-value="changeKind" />
      </template>
    </DetectionEvaluationPanel>
    <AdditionalEvaluationPanel v-else-if="supported" :key="kind" ref="additionalPanelRef" :project-id="projectId" :zh="zh" :can-write="canWrite" :kind="supported" @focus-mode="setFocusMode">
      <template #task-type>
        <Select :model-value="kind" :options="evaluationTypeOptions(zh)" :aria-label="zh ? '评估任务类型' : 'Evaluation task type'" @update:model-value="changeKind" />
      </template>
    </AdditionalEvaluationPanel>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Select from '@/shared/ui/components/Select.vue'
import { evaluationTypeOptions, evaluationTypes } from '../model-evaluation-types'
import { additionalEvaluationKinds, type AdditionalEvaluationKind } from '../services/model-evaluation.service'
import DetectionEvaluationPanel from './DetectionEvaluationPanel.vue'
import AdditionalEvaluationPanel from './AdditionalEvaluationPanel.vue'

const props = defineProps<{ projectId: string; zh: boolean; canWrite: boolean }>()
const emit = defineEmits<{ focusMode: [active: boolean] }>()
const focusMode = ref(false)
const detectionPanelRef = ref<InstanceType<typeof DetectionEvaluationPanel> | null>(null)
const additionalPanelRef = ref<InstanceType<typeof AdditionalEvaluationPanel> | null>(null)
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
watch(kind, () => setFocusMode(false))
const supported = computed(() => additionalEvaluationKinds.find(value => value === kind.value))
function changeKind(value: unknown): void {
  if (typeof value !== 'string') return
  if (value === 'detection' || additionalEvaluationKinds.includes(value as AdditionalEvaluationKind)) {
    void router.replace({ query: { ...route.query, tab: 'evaluation', evaluation: value } })
  }
}
function openCreate(): void {
  if (kind.value === 'detection') void detectionPanelRef.value?.openCreate()
  else additionalPanelRef.value?.openCreate()
}
defineExpose({ openCreate })
</script>

<style scoped>
.model-evaluations { display:grid; gap:16px; min-width:0; }
</style>
