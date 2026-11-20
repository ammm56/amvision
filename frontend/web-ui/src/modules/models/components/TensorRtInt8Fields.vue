<template>
  <div class="int8-fields">
    <section class="int8-panel">
      <div class="int8-heading">
        <h3>{{ zh ? '输入形状（动态）' : 'Input shapes (dynamic)' }}</h3>
        <span>NCHW</span>
      </div>
      <table class="int8-profile">
        <thead>
          <tr><th scope="col">{{ zh ? '范围' : 'Profile' }}</th><th scope="col">N</th><th scope="col">C</th><th scope="col">H</th><th scope="col">W</th></tr>
        </thead>
        <tbody>
          <tr v-for="label in profiles" :key="label">
            <th scope="row">{{ shapeLabel(label) }}</th>
            <td v-for="(axis, index) in axes" :key="axis">
              <input
                type="number"
                required
                :aria-label="`${label} ${axis}`"
                :min="index === 0 ? 1 : index === 1 ? 3 : 64"
                :max="index === 0 ? 4 : index === 1 ? 3 : 1280"
                :step="index < 2 ? 1 : 32"
                :readonly="index === 1 || (index === 0 && label !== 'max')"
                :value="modelValue.input_profile[label][index]"
                @input="changeShape(label, index, $event)"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </section>
    <Int8SampleFields
      :model-value="modelValue" :dataset-exports="datasetExports" :zh="zh"
      @update:model-value="emit('update:modelValue', { ...modelValue, ...$event })"
    />
  </div>
</template>

<script setup lang="ts">
import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import Int8SampleFields from './Int8SampleFields.vue'
import type { TensorRtInt8Settings, TensorRtShape } from '../services/model.service'

const props = defineProps<{
  modelValue: TensorRtInt8Settings
  datasetExports: DatasetExportSummary[]
  zh: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [settings: TensorRtInt8Settings] }>()
const profiles = ['min', 'opt', 'max'] as const
const axes = ['N', 'C', 'H', 'W'] as const
function shapeLabel(label: typeof profiles[number]): string {
  if (!props.zh) return label
  return `${{ min: '最小', opt: '最优', max: '最大' }[label]} (${label})`
}

function changeShape(label: typeof profiles[number], index: number, event: Event): void {
  const shape: TensorRtShape = [...props.modelValue.input_profile[label]]
  shape[index] = (event.target as HTMLInputElement).valueAsNumber
  emit('update:modelValue', { ...props.modelValue, input_profile: { ...props.modelValue.input_profile, [label]: shape } })
}

</script>

<style scoped>
.int8-fields, .int8-panel { display: grid; gap: 10px; min-width: 0; }
.int8-panel { padding: 12px; border: 1px solid var(--am-border); border-radius: 8px; }
.int8-heading { display: flex; align-items: center; gap: 10px; }
.int8-heading span { padding: 2px 8px; border-radius: 4px; background: var(--am-surface-soft); color: var(--am-text-muted); }
.int8-panel h3, .int8-panel p { margin: 0; }
.int8-panel p { color: var(--am-text-muted); }
.int8-profile { border-collapse: collapse; width: 100%; table-layout: fixed; text-align: left; }
.int8-profile thead { background: var(--am-surface-soft); }
.int8-profile :is(th, td) { padding: 4px 8px; }
.int8-profile input { width: min(100%, 108px); min-width: 0; min-height: 32px; padding-block: 4px; }
.int8-profile input[readonly] { background: var(--am-surface-soft); color: var(--am-text-muted); }
</style>
