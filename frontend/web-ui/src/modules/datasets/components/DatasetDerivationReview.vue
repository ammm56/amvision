<template>
  <div class="dataset-derivation-review">
    <h2>{{ label('检查报告', 'Check report') }}</h2>
    <div class="derivation-check-status">
      <span class="derivation-status-icon" :class="{ failed: result.can_create === false }"><Check v-if="result.can_create !== false" :size="22" /><CircleAlert v-else :size="22" /></span>
      <div><strong :class="result.can_create === false ? 'check-failed' : 'check-passed'">{{ result.can_create === false ? label('预检查未通过', 'Preflight failed') : label('预检查通过', 'Preflight passed') }}</strong><p class="dataset-muted">{{ label('检查完成后才允许创建；源版本及其引用保持不变。', 'Create after checks finish; the source version and its references remain unchanged.') }}</p></div>
    </div>
    <section class="derivation-review-section">
      <h2>{{ label('变更摘要', 'Change summary') }}</h2>
      <div class="derivation-metrics">
        <div v-for="item in metrics" :key="item.label"><component :is="item.icon" :size="28" /><div><span>{{ item.label }}</span><strong>{{ number(item.value) }} {{ item.unit }}</strong><small>{{ item.detail }}</small></div></div>
      </div>
    </section>
    <section class="derivation-review-section">
      <h2>{{ label('数据划分对比', 'Split comparison') }}</h2>
      <ResourceTable class="dataset-table derivation-comparison" :label="label('划分变更', 'Split changes')">
        <thead><tr><th rowspan="2" scope="col">{{ label('划分', 'Split') }}</th><th colspan="3" scope="colgroup">{{ label('图像数量（张）', 'Images') }}</th><th colspan="3" scope="colgroup">{{ label('对象数量（个）', 'Objects') }}</th></tr>
          <tr><template v-for="group in ['samples', 'objects']" :key="group"><th scope="col">{{ label('源版本', 'Source') }}</th><th scope="col">{{ label('新版本', 'New version') }}</th><th scope="col">{{ label('变化', 'Change') }}</th></template></tr></thead>
        <tbody><tr v-for="split in splits" :key="split"><th scope="row">{{ split }}</th><template v-for="kind in ['samples', 'objects']" :key="kind"><td>{{ count(split, kind, true) }}</td><td>{{ count(split, kind, false) }}</td><td :class="deltaClass(delta(split, kind))">{{ signed(delta(split, kind)) }}</td></template></tr></tbody>
      </ResourceTable>
    </section>
    <section class="derivation-review-section">
      <h2>{{ label('数据检查结果', 'Data checks') }}</h2>
      <div class="derivation-checks">
        <div class="derivation-check"><span v-if="result.duplicate_check === 'passed' && result.cross_split_duplicate_count === 0" class="derivation-status-icon"><Check :size="21" /></span><Info v-else :size="28" /><div><div class="derivation-check-title"><strong>{{ label('跨划分重复候选', 'Cross-split duplicates') }}</strong><strong>{{ number(result.cross_split_duplicate_count) }} {{ label('个', 'samples') }}</strong></div><p>{{ duplicateMessage }}</p></div></div>
      </div>
    </section>
    <section v-if="result.category_changes?.length" class="derivation-review-section">
      <h2>{{ label('类别映射变更', 'Class mapping changes') }}</h2>
      <ResourceTable class="dataset-table" :label="label('类别映射变更', 'Class mapping changes')"><thead><tr><th>{{ label('源类别', 'Source class') }}</th><th>{{ label('目标类别', 'Target class') }}</th></tr></thead><tbody><tr v-for="row in result.category_changes" :key="row.category_id"><td>{{ row.before }}</td><td>{{ row.after ?? label('排除标注，保留样本', 'Exclude annotations, keep samples') }}</td></tr></tbody></ResourceTable>
    </section>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import { Check, CircleAlert, Database, FileText, Image, Info, Tag } from '@lucide/vue'
import type { DatasetJob } from '../services/dataset-workspace.service'
const props = defineProps<{ job: DatasetJob; sourceNumber: number; sourceName: string }>()
const { locale } = useI18n()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const result = computed(() => props.job.result || {})
const number = (value: unknown) => typeof value === 'number' ? value.toLocaleString() : '—'
const signed = (value: number | undefined) => value === undefined ? '—' : value > 0 ? `+ ${number(value)}` : value < 0 ? `− ${number(Math.abs(value))}` : '0'
const change = (value: unknown, source: unknown) => typeof value === 'number' && typeof source === 'number' ? value - source : undefined
const metrics = computed(() => [
  { label: label('图像数量', 'Images'), icon: Image, value: result.value.sample_count, unit: label('张', 'images'), detail: `${label('较源版本', 'From source')} ${signed(change(result.value.sample_count, result.value.source_count))}` },
  { label: label('对象数量', 'Objects'), icon: Database, value: result.value.object_count, unit: label('个', 'objects'), detail: `${label('较源版本', 'From source')} ${signed(change(result.value.object_count, result.value.source_object_count))}` },
  { label: label('类别数量', 'Classes'), icon: Tag, value: result.value.category_count, unit: label('类', 'classes'), detail: `${label('较源版本', 'From source')} ${signed(change(result.value.category_count, result.value.source_category_count))}` },
  { label: label('样本增删', 'Sample changes'), icon: FileText, value: result.value.excluded_count, unit: label('张', 'images'), detail: `${label('新增', 'Added')} 0 / ${label('删除', 'Removed')} ${number(result.value.excluded_count)}` },
])
const splits = computed(() => [...new Set(['train', 'val', 'test', ...Object.keys(result.value.source_split_counts || {}), ...Object.keys(result.value.split_counts || {})])])
function counts(kind: string, source: boolean) {
  return result.value[`${source ? 'source_' : ''}split_${kind === 'objects' ? 'object_' : ''}counts`] as Record<string, number> | undefined
}
function count(split: string, kind: string, source: boolean) {
  const values = counts(kind, source)
  if (!values) return '—'
  if (!(split in values)) return kind === 'samples' ? label('未配置', 'Not configured') : '—'
  return number(values[split])
}
function delta(split: string, kind: string) {
  const before = counts(kind, true), after = counts(kind, false)
  return before && after ? (after[split] ?? 0) - (before[split] ?? 0) : undefined
}
const deltaClass = (value: number | undefined) => value && value > 0 ? 'derivation-delta--positive' : value && value < 0 ? 'derivation-delta--negative' : ''
const duplicateMessage = computed(() => result.value.duplicate_check === 'passed'
  ? result.value.cross_split_duplicate_count > 0 ? label('发现内容相同的跨划分样本，请确认后创建。', 'Identical content appears across splits; review before creating.') : label('未发现跨划分的完全重复候选。', 'No exact duplicates found across splits.')
  : result.value.duplicate_check === 'incomplete' ? label(`${result.value.unreadable_count} 个样本无法读取，请修复后重新检查。`, `${result.value.unreadable_count} unreadable samples; fix and recheck.`) : label('此历史报告未记录重复检查结果。', 'This historical report has no duplicate check result.'))
</script>
<style scoped>
.dataset-derivation-review { display: grid; gap: 14px; min-width: 0; }
h2 { margin: 0; font-size: 16px; font-weight: 600; }
.derivation-check-status { display: flex; gap: 14px; align-items: flex-start; padding: 4px 6px; }
.derivation-status-icon { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; background: var(--am-brand-primary); color: white; flex-shrink: 0; }
.derivation-status-icon.failed { background: var(--am-danger-text); }
.derivation-check-status strong { display: inline-block; padding: 4px 8px; border-radius: 4px; }
.check-passed { color: var(--am-brand-primary); background: var(--am-action-soft); }
.check-failed { color: var(--am-danger-text); }
.derivation-check-status p { margin: 8px 0 0; }
.derivation-review-section { display: grid; gap: 12px; padding: 12px; border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); min-width: 0; }
.derivation-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); padding: 4px 12px; }
.derivation-metrics > div { display: flex; gap: 22px; padding: 0 24px; align-items: flex-start; min-width: 0; }
.derivation-metrics > div:first-child { padding-left: 12px; }
.derivation-metrics > div + div { border-left: 1px solid var(--am-border); }
.derivation-metrics svg { flex-shrink: 0; margin-top: 8px; }
.derivation-metrics > div > div { display: grid; gap: 6px; }
.derivation-metrics span, .derivation-metrics small { color: var(--am-text-muted); font-size: 13px; }
.derivation-metrics strong { font-size: 22px; font-weight: 600; }
.derivation-comparison :deep(table) { border-collapse: collapse; table-layout: fixed; }
.derivation-comparison :deep(th), .derivation-comparison :deep(td) { border: 1px solid var(--am-border); padding: 5px 12px; text-align: center; }
.derivation-comparison :deep(tbody th) { text-align: left; background: transparent; font-weight: 400; }
.derivation-comparison :deep(thead th) { background: var(--am-surface); font-weight: 500; }
.derivation-comparison :deep(td.derivation-delta--positive) { color: var(--am-brand-primary); }
.derivation-comparison :deep(td.derivation-delta--negative) { color: var(--am-danger-text); }
.derivation-checks { display: grid; grid-template-columns: minmax(0, 1fr); }
.derivation-check { display: flex; align-items: center; gap: 16px; padding: 12px 16px; border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); }
.derivation-check > svg { flex-shrink: 0; color: var(--am-text-muted); }
.derivation-check > div { flex: 1; min-width: 0; }
.derivation-check-title { display: flex; justify-content: space-between; gap: 12px; }
.derivation-check strong { font-weight: 600; }
.derivation-check p { margin: 4px 0 0; color: var(--am-text-muted); font-size: 13px; line-height: 1.5; }
@media (max-width: 1200px) {
  .derivation-metrics { padding: 4px 0; }
  .derivation-metrics > div, .derivation-metrics > div:first-child { padding: 0 12px; gap: 12px; }
  .derivation-metrics strong { font-size: 18px; }
  .derivation-checks { gap: 12px; }
  .derivation-check { padding: 12px; gap: 12px; }
}
@media (max-width: 760px) {
  .derivation-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 0; }
  .derivation-metrics > div:nth-child(3) { border-left: 0; }
  .derivation-checks { grid-template-columns: minmax(0, 1fr); }
  .derivation-comparison :deep(th), .derivation-comparison :deep(td) { padding: 6px 4px; font-size: 12px; }
}
</style>
