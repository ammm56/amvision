<template>
    <div class="int8-samples" :class="{ 'int8-samples--stacked': stacked }">
      <section v-for="source in sources" :key="source.key" class="int8-panel">
        <div class="int8-heading">
          <h3>{{ source.title }}</h3>
          <span v-if="!stacked">{{ source.split }}</span>
        </div>
        <div class="int8-source-fields">
          <label class="field">
            <span>{{ zh ? '数据来源' : 'Dataset source' }}</span>
            <SelectField
              :aria-label="source.title"
              :model-value="modelValue[source.key].dataset_export_id"
              :options="optionsFor(source.split)"
              :placeholder="zh ? '选择 COCO 数据集导出' : 'Select a COCO dataset export'"
              @update:model-value="changeSource(source.key, String($event || ''))"
            />
          </label>
          <label v-if="stacked" class="field">
            <span>{{ zh ? '划分' : 'Split' }}</span>
            <input :value="source.split" readonly />
          </label>
          <label class="field">
            <span>{{ zh ? '样本数量' : 'Samples' }}</span>
            <input type="number" min="1" :max="source.limit" required :value="modelValue[source.key].sample_count" @input="changeCount(source.key, $event)" />
          </label>
        </div>
        <p v-if="!optionsFor(source.split).length">
          {{ zh ? '当前项目没有可用的 COCO 导出。' : 'No eligible COCO exports in this project.' }}
        </p>
      </section>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import SelectField from '@/shared/ui/components/Select.vue'
import type { Int8SampleSettings } from '../services/model.service'

const props = defineProps<{
  modelValue: Int8SampleSettings
  datasetExports: DatasetExportSummary[]
  datasetExportLabels?: ReadonlyMap<string, string>
  zh: boolean
  stacked?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [settings: Int8SampleSettings] }>()
type SourceKey = 'int8_calibration' | 'int8_validation'
const sources = computed(() => [
  { key: 'int8_calibration' as const, split: 'train', limit: 200, title: props.zh ? (props.stacked ? '校准数据' : '校准数据（INT8 必需）') : 'INT8 calibration' },
  { key: 'int8_validation' as const, split: 'val', limit: 100, title: props.zh ? (props.stacked ? '输出校验' : '输出一致性校验') : 'Output validation' },
])

function optionsFor(split: string) {
  return props.datasetExports
    .filter(item => item.task_type === 'detection' && item.format_id === 'coco-detection-v1'
      && item.status === 'completed' && !item.metadata.files_cleaned_at && item.split_names.includes(split))
    .map(item => ({ value: item.dataset_export_id, label: item.display_name || props.datasetExportLabels?.get(item.dataset_export_id) || item.dataset_export_id }))
}

function changeSource(key: SourceKey, id: string): void {
  emit('update:modelValue', { ...props.modelValue, [key]: { ...props.modelValue[key], dataset_export_id: id } })
}

function changeCount(key: SourceKey, event: Event): void {
  emit('update:modelValue', { ...props.modelValue, [key]: {
    ...props.modelValue[key], sample_count: (event.target as HTMLInputElement).valueAsNumber,
  } })
}
</script>

<style scoped>
.int8-panel { display: grid; gap: 10px; min-width: 0; }
.int8-panel { padding: 12px; border: 1px solid var(--am-border); border-radius: 8px; }
.int8-heading { display: flex; align-items: center; gap: 10px; }
.int8-heading span { padding: 2px 8px; border-radius: 4px; background: var(--am-surface-soft); color: var(--am-text-muted); }
.int8-panel h3, .int8-panel p { margin: 0; }
.int8-panel p { color: var(--am-text-muted); }
.int8-samples { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.int8-source-fields { display: grid; grid-template-columns: minmax(0, 1fr) 86px; gap: 12px; }
.int8-source-fields input { width: 100%; }
.int8-samples--stacked { grid-template-columns: minmax(0, 1fr); gap: 8px; }
.int8-samples--stacked .int8-panel { grid-template-columns: 104px minmax(0, 1fr); align-items: center; }
.int8-samples--stacked .int8-source-fields { grid-template-columns: minmax(0, 1fr) 82px 94px; }
.int8-samples--stacked .int8-panel p { grid-column: 2; }
@media (max-width: 650px) {
  .int8-samples--stacked .int8-panel { grid-template-columns: minmax(0, 1fr); }
  .int8-samples--stacked .int8-panel p { grid-column: 1; }
}
@media (max-width: 810px) { .int8-samples { grid-template-columns: minmax(0, 1fr); } }
</style>
