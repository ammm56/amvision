<template>
  <div class="dataset-derivation-review">
    <div class="dataset-review-source">
      <span>{{ label('来源版本', 'Source version') }}</span>
      <strong>{{ sourceName }} · v{{ sourceNumber }}</strong>
    </div>
    <div class="dataset-heading">
      <h2 class="dataset-review-heading"><CircleCheck v-if="result.can_create !== false" :size="22" />{{ result.can_create === false ? label('检查未通过', 'Checks failed') : label('检查通过', 'Checks passed') }}</h2>
    </div>
    <div class="dataset-review-counts">
      <div v-for="item in metrics" :key="item.key">
        <strong>{{ typeof result[item.key] === 'number' ? result[item.key].toLocaleString() : '—' }}</strong
        ><span>{{ item.label }}</span>
      </div>
    </div>
    <h2>{{ label('数据划分', 'Data splits') }}</h2>
    <ResourceTable
      class="dataset-table"
      :label="label('划分变更', 'Split changes')"
    >
      <thead>
        <tr>
          <th>Split</th>
          <th>{{ label('来源版本', 'Source version') }}</th>
          <th>{{ label('新版本', 'New version') }}</th>
          <th>{{ label('变化', 'Change') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="split in ['train', 'val', 'test']" :key="split">
          <td>{{ split }}</td>
          <td>{{ result.source_split_counts?.[split] ?? 0 }}</td>
          <td>{{ result.split_counts?.[split] ?? 0 }}</td>
          <td>{{ delta(split) }}</td>
        </tr>
      </tbody>
    </ResourceTable>
    <template v-if="result.category_changes?.length">
      <h2>{{ label('类别名称变更', 'Class name changes') }}</h2>
      <ResourceTable
        class="dataset-table"
        :label="label('类别名称变更', 'Class name changes')"
        ><thead>
          <tr>
            <th>{{ label('原名称', 'Original') }}</th>
            <th>{{ label('新名称', 'New name') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in result.category_changes" :key="row.category_id">
            <td :title="row.before">{{ row.before }}</td>
            <td :title="row.after">{{ row.after }}</td>
          </tr>
        </tbody></ResourceTable
      >
    </template>
    <p v-if="result.group_key" class="dataset-muted">
      {{ label('分组字段', 'Grouping field') }}：{{ result.group_key }} ·
      {{ result.group_count }} {{ label('组', 'groups') }}
    </p>
    <p v-if="result.description" class="dataset-review-description">
      {{ result.description }}
    </p>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import { CircleCheck } from '@lucide/vue'
import type { DatasetJob } from '../services/dataset-workspace.service'
const props = defineProps<{ job: DatasetJob; sourceNumber: number; sourceName: string }>()
const { locale } = useI18n()
const label = (zh: string, en: string) =>
  locale.value.startsWith('zh') ? zh : en
const result = computed(() => props.job.result || {})
const metrics = computed(() => [
  { key: 'sample_count', label: label('样本', 'Samples') },
  { key: 'object_count', label: label('对象', 'Objects') },
  { key: 'category_count', label: label('类别', 'Classes') },
  { key: 'excluded_count', label: label('未纳入样本', 'Excluded samples') },
])
function delta(split: string) {
  const value =
    (result.value.split_counts?.[split] || 0) -
    (result.value.source_split_counts?.[split] || 0)
  return value > 0 ? `+${value}` : String(value)
}
</script>
<style scoped>
.dataset-derivation-review {
  display: grid;
  gap: 20px;
  min-width: 0;
  margin-bottom: 24px;
}
.dataset-review-counts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 20px;
  padding: 18px;
  background: var(--am-surface-muted);
  border-radius: var(--am-radius-md);
}
.dataset-review-source { display: flex; gap: 16px; align-items: baseline; flex-wrap: wrap; }
.dataset-review-source > span { color: var(--am-text-muted); }
.dataset-review-source > strong { font-weight: 500; overflow-wrap: anywhere; }
.dataset-review-heading { display: flex; align-items: center; gap: 8px; }
.dataset-review-heading svg { color: var(--am-brand-primary); }
.dataset-review-counts > div {
  display: grid;
  gap: 6px;
}
.dataset-review-counts strong {
  font-size: 24px;
  font-weight: 500;
}
.dataset-review-counts span {
  color: var(--am-text-muted);
  font-size: 13px;
}
.dataset-review-description {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: 0;
}
</style>
