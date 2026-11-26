<template>
  <div class="dataset-comparison">
    <div class="comparison-toolbar">
      <label class="comparison-picker"><span>{{ label('版本（左）', 'Version (left)') }}</span><SelectField :model-value="source.dataset_version_id" :options="options" :disabled="locked" :aria-label="label('左侧版本', 'Left version')" @update:model-value="emit('source', String($event))" /></label>
      <Button class="comparison-swap" :disabled="locked || !target" :aria-label="label('交换比较方向', 'Swap versions')" @click="emit('source', targetId)"><ArrowLeftRight :size="16" /></Button>
      <label class="comparison-picker"><span>{{ label('版本（右）', 'Version (right)') }}</span><SelectField :model-value="targetId" :options="targetOptions" :disabled="locked" :aria-label="label('右侧版本', 'Right version')" @update:model-value="emit('target', String($event))" /></label>
      <div class="comparison-actions">
        <Button @click="emit('version', source.dataset_version_id)">{{ label('查看', 'View') }} v{{ source.version_number }}</Button>
        <Button v-if="target" variant="primary" @click="emit('version', target.dataset_version_id)">{{ label('查看', 'View') }} v{{ target.version_number }}</Button>
      </div>
    </div>
    <slot name="versions" />
    <InlineError v-if="detailError" :message="detailError" />
    <Button v-if="detailError" @click="loadDetails">{{ text('retry') }}</Button>
    <div class="comparison-summaries" :aria-busy="detailsLoading">
      <template v-for="(side, index) in [source, target]" :key="index">
        <ArrowRight v-if="index" class="comparison-direction" :size="18" aria-hidden="true" />
        <section class="comparison-card comparison-version" :class="{ 'comparison-version--target': index === 1 }" :aria-label="index ? label('右侧版本摘要', 'Right version summary') : label('左侧版本摘要', 'Left version summary')">
          <template v-if="side">
            <div class="comparison-version-heading"><strong>v{{ side.version_number }}</strong><div><time>{{ datasetDate(side.created_at) }}</time><span v-if="creator(side)">{{ label('创建者', 'Created by') }} {{ creator(side) }}</span></div></div>
            <dl><div><dd>{{ number(side.sample_count) }}</dd><dt>{{ label('图像数量', 'Images') }}</dt></div><div><dd>{{ number(side.object_count) }}</dd><dt>{{ label('对象数量', 'Objects') }}</dt></div><div><dd>{{ number(side.category_count) }}</dd><dt>{{ label('类别数量', 'Classes') }}</dt></div><div><dd>{{ ['train', 'val', 'test'].map(key => number(side.split_counts[key])).join(' / ') }}</dd><dt>train / val / test</dt></div></dl>
          </template>
          <p v-else class="comparison-placeholder">{{ detailsLoading ? text('loading') : label('选择右侧版本进行比较', 'Select the right version to compare') }}</p>
        </section>
      </template>
    </div>
    <div v-if="!job" class="comparison-start"><span class="dataset-muted">{{ label('按稳定样本标识比较；来源版本保持不变。', 'Compare stable sample identities. Source versions stay unchanged.') }}</span><Button variant="primary" :loading="busy" :disabled="!canWrite || !target || detailsLoading || !!detailError || locked || targetId === source.dataset_version_id" @click="emit('compare')">{{ label('开始比较', 'Compare') }}</Button></div>
    <slot name="status" />
    <template v-if="result">
      <p v-if="stale" class="comparison-notice" role="status">{{ label('来源版本在比较后已更新。差异为当时的结果，下方版本统计和样本详情为当前数据；请重新比较。', 'The source changed after this comparison. Differences are historical; version statistics and sample details reflect current data. Compare again.') }} <Button size="sm" :disabled="locked" @click="emit('target', targetId)">{{ label('重新比较', 'Compare again') }}</Button></p>
      <div class="comparison-filters"><h2>{{ label('差异样本', 'Changed samples') }}</h2><SegmentedButtonGroup v-model="filter" :label="label('差异类型', 'Change type')" :options="filters" /><p>{{ label('按稳定样本标识比较', 'Compared by stable sample identity') }}；{{ label('新增', 'added') }} {{ number(counts.added) }}，{{ label('移除', 'removed') }} {{ number(counts.removed) }}，{{ label('修改', 'modified') }} {{ number(counts.modified) }}。</p></div>
      <section class="comparison-card comparison-changes">
        <div class="comparison-table-heading"><h2>{{ filters.find(item => item.value === filter)?.label }}</h2><time>{{ datasetDate(job?.finished_at || job?.created_at) }}</time></div>
        <ResourceTable class="dataset-table" :label="label('差异样本', 'Changed samples')"><thead><tr><th>{{ text('fileName') }}</th><th>{{ label('划分', 'Split') }}</th><th>{{ label('对象数量', 'Objects') }}</th><th>{{ label('变化', 'Changes') }}</th><th>{{ text('actions') }}</th></tr></thead><tbody>
          <tr v-for="row in pageRows" :key="row.sample_id"><td :title="row.file_name">{{ row.file_name }}</td><td><span class="comparison-split">{{ sampleDetails[rowKey(row)]?.split ?? '—' }}</span></td><td>{{ number(sampleDetails[rowKey(row)]?.annotations.length) }}</td><td :title="row.kinds.map(kindName).join('、')">{{ row.kinds.map(kindName).join('、') }}</td><td><Button size="sm" @click="emit('sample', row.sample_id, rowVersion(row))">{{ label('查看样本', 'View sample') }}</Button></td></tr>
          <tr v-if="!pageRows.length"><td colspan="5" class="comparison-empty">{{ result.truncated && counts[filter as keyof typeof counts] ? label('当前报告保留的前 200 条差异中没有此类记录。', 'No matching records in the first 200 retained differences.') : label('没有此类差异样本', 'No matching differences') }}</td></tr>
        </tbody></ResourceTable>
        <p v-if="sampleError" class="comparison-notice" role="status">{{ sampleError }} <Button size="sm" @click="loadSamples">{{ text('retry') }}</Button></p>
        <PaginationControls :offset="offset" :limit="4" :item-count="pageRows.length" :total-count="filteredRows.length" numbered @previous="offset -= 4" @next="offset += 4" @go="offset = $event"><template #summary>{{ label('共', 'Total') }} {{ number(filteredRows.length) }} {{ label('张 · 4 条/页', 'samples · 4 per page') }}</template></PaginationControls>
        <p v-if="result.truncated" class="dataset-muted comparison-limit">{{ label('报告仅保留前 200 条差异，筛选和分页作用于这些记录；上方数量包含全部差异样本。', 'Only the first 200 differences are retained for filtering and paging. Counts above cover all differences.') }}</p>
      </section>
      <div class="comparison-breakdowns">
        <section class="comparison-card"><h2>{{ label('类别对比', 'Class comparison') }}（{{ categoryRows.length }}）</h2><ResourceTable class="dataset-table" :label="label('类别对比', 'Class comparison')"><thead><tr><th>{{ label('类别', 'Class') }}</th><th>v{{ source.version_number }} {{ label('对象数量', 'objects') }}</th><th>v{{ target?.version_number ?? '—' }} {{ label('对象数量', 'objects') }}</th><th>{{ label('变化', 'Change') }}</th></tr></thead><tbody><tr v-for="row in categoryRows" :key="row.name"><td :title="row.name">{{ row.name }}</td><td>{{ number(row.left) }}</td><td>{{ number(row.right) }}</td><td :class="deltaClass(row.left, row.right)">{{ delta(row.left, row.right) }}</td></tr><tr v-if="!categoryRows.length"><td colspan="4" class="comparison-empty">{{ detailsLoading ? text('loading') : label('无类别数据', 'No class data') }}</td></tr></tbody></ResourceTable></section>
        <section class="comparison-card"><h2>{{ label('数据划分对比', 'Split comparison') }}</h2><ResourceTable class="dataset-table" :label="label('数据划分对比', 'Split comparison')"><thead><tr><th>{{ label('划分', 'Split') }}</th><th>v{{ source.version_number }} {{ label('图像数量', 'images') }}</th><th>v{{ target?.version_number ?? '—' }} {{ label('图像数量', 'images') }}</th><th>{{ label('变化', 'Change') }}</th></tr></thead><tbody><tr v-for="split in splits" :key="split"><td>{{ split }}</td><td>{{ number(source.split_counts[split]) }}</td><td>{{ number(target?.split_counts[split]) }}</td><td :class="deltaClass(source.split_counts[split], target?.split_counts[split])">{{ target && (split in source.split_counts || split in target.split_counts) ? delta(source.split_counts[split] ?? 0, target.split_counts[split] ?? 0) : '—' }}</td></tr></tbody></ResourceTable></section>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeftRight, ArrowRight } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import SegmentedButtonGroup from '@/shared/ui/components/SegmentedButtonGroup.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { datasetDate, datasetError, useDatasetText } from '../dataset-workspace'
import { getDatasetWorkspace, getDatasetCategories, getDatasetSample, type DatasetWorkspace, type DatasetVersion, type DatasetJob, type DatasetSample, type CategoryStatistic } from '../services/dataset-workspace.service'

const props = defineProps<{ source: DatasetWorkspace; targetId: string; versions: DatasetVersion[]; job: DatasetJob | null; busy: boolean; canWrite: boolean; initialFilter?: string; initialOffset?: number }>()
const emit = defineEmits<{ source: [id: string]; target: [id: string]; compare: []; version: [id: string]; sample: [id: string, version: string]; viewState: [state: { filter: string; offset: number }] }>()
const { locale } = useI18n(), text = useDatasetText()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const number = (value: number | null | undefined) => typeof value === 'number' ? value.toLocaleString() : '—'
const creator = (side: DatasetWorkspace) => typeof side.metadata.created_by === 'string' ? side.metadata.created_by : ''
const target = ref<DatasetWorkspace | null>(null), detailsLoading = ref(false), detailError = ref('')
const leftCategories = ref<CategoryStatistic[]>([]), rightCategories = ref<CategoryStatistic[]>([])
const filter = ref(['added', 'removed', 'modified'].includes(props.initialFilter || '') ? props.initialFilter! : 'all'), offset = ref(Number.isFinite(props.initialOffset) ? Math.max(0, Math.floor(props.initialOffset! / 4) * 4) : 0), sampleError = ref(''), sampleDetails = ref<Record<string, DatasetSample>>({})
let generation = 0, sampleGeneration = 0, active = true
const locked = computed(() => props.busy || ['queued', 'running'].includes(props.job?.state || ''))
const options = computed(() => [...new Map([props.source, ...props.versions, ...(target.value ? [target.value] : [])].map(version => [version.dataset_version_id, version])).values()].sort((a, b) => b.version_number - a.version_number).map(version => ({ value: version.dataset_version_id, label: `v${version.version_number}` })))
const targetOptions = computed(() => [{ value: '', label: label('选择版本', 'Select version') }, ...options.value.map(option => ({ ...option, disabled: option.value === props.source.dataset_version_id }))])
const result = computed(() => props.job?.state === 'succeeded' ? props.job.result : null)
const stale = computed(() => !!props.job?.content_revision && props.job.content_revision !== props.source.metadata.content_revision)
const counts = computed(() => { const counts = result.value?.counts || {}; return { all: counts.changed_samples || 0, added: counts.added || 0, removed: counts.removed || 0, modified: Math.max(0, (counts.changed_samples || 0) - (counts.added || 0) - (counts.removed || 0)) } })
const filters = computed(() => [{ value: 'all', label: `${label('全部', 'All')} (${number(counts.value.all)})` }, { value: 'added', label: `${label('新增', 'Added')} (${number(counts.value.added)})` }, { value: 'removed', label: `${label('移除', 'Removed')} (${number(counts.value.removed)})` }, { value: 'modified', label: `${label('修改', 'Modified')} (${number(counts.value.modified)})` }])
type Change = { sample_id: string; source_sample_id?: string; file_name: string; kinds: string[] }
const rows = computed<Change[]>(() => result.value?.changes || [])
const filteredRows = computed(() => rows.value.filter(row => filter.value === 'all' || (filter.value === 'modified' ? !row.kinds.some(kind => ['added', 'removed'].includes(kind)) : row.kinds.includes(filter.value))))
const pageRows = computed(() => filteredRows.value.slice(offset.value, offset.value + 4))
const rowVersion = (row: Change) => row.kinds.includes('removed') ? props.source.dataset_version_id : props.targetId
const rowKey = (row: Change) => `${rowVersion(row)}:${row.sample_id}`
const kindName = (kind: string) => ({ added: label('新增', 'Added'), removed: label('移除', 'Removed'), split: label('划分', 'Split'), annotations: label('标注', 'Annotations'), categories: label('类别', 'Classes'), image: label('图片', 'Image'), cloud: label('点云', 'Point cloud'), depth: label('深度', 'Depth'), mask: label('掩膜', 'Mask'), calibration: label('标定', 'Calibration'), media_metadata: label('媒体信息', 'Media metadata') })[kind] || kind
const splits = computed(() => [...new Set(['train', 'val', 'test', ...Object.keys(props.source.split_counts), ...Object.keys(target.value?.split_counts || {})])])
// 按类别名称对照；类别 ID 在两个版本中可能被重新编号。
const categoryRows = computed(() => [...new Set([...leftCategories.value, ...rightCategories.value].map(row => row.name))].map(name => ({ name, left: leftCategories.value.find(row => row.name === name)?.object_count ?? 0, right: rightCategories.value.find(row => row.name === name)?.object_count ?? 0 })))
const delta = (left: number | undefined, right: number | undefined) => left === undefined || right === undefined ? '—' : `${right > left ? '+' : ''}${number(right - left)}`
const deltaClass = (left: number | undefined, right: number | undefined) => (right ?? 0) > (left ?? 0) ? 'comparison-increase' : (right ?? 0) < (left ?? 0) ? 'comparison-decrease' : ''
async function loadDetails() {
  const current = ++generation
  target.value = null
  leftCategories.value = []; rightCategories.value = []
  detailError.value = ''; detailsLoading.value = true
  try {
    if (!props.targetId) return
    const [workspace, left, right] = await Promise.all([
      getDatasetWorkspace(props.source.dataset_id, props.targetId),
      getDatasetCategories(props.source.dataset_id, props.source.dataset_version_id),
      getDatasetCategories(props.source.dataset_id, props.targetId),
    ])
    if (!active || current !== generation) return
    target.value = workspace; leftCategories.value = left.items; rightCategories.value = right.items
  } catch (error) { if (active && current === generation) detailError.value = datasetError(error) }
  finally { if (active && current === generation) detailsLoading.value = false }
}
async function loadSamples() {
  const current = ++sampleGeneration
  sampleError.value = ''
  const missing = pageRows.value.filter(row => !sampleDetails.value[rowKey(row)])
  const results = await Promise.allSettled(missing.map(async row => ({ key: rowKey(row), sample: await getDatasetSample(props.source.dataset_id, rowVersion(row), row.sample_id) })))
  if (!active || current !== sampleGeneration) return
  for (const item of results) {
    if (item.status === 'fulfilled') sampleDetails.value[item.value.key] = item.value.sample
    else sampleError.value = label('部分样本详情读取失败，划分与对象数量暂不可用。', 'Some sample details could not be loaded. Split and object counts are unavailable.')
  }
}
watch(() => [props.source.dataset_version_id, props.targetId], () => { sampleDetails.value = {}; void loadDetails() }, { immediate: true })
watch(filter, () => { offset.value = 0 })
watch(() => props.job?.task_id, (_, previous) => { if (previous) { filter.value = 'all'; offset.value = 0 }; sampleDetails.value = {} })
watch([filter, offset], () => emit('viewState', { filter: filter.value, offset: offset.value }))
watch(filteredRows, rows => { if (result.value && offset.value >= rows.length) offset.value = Math.max(0, Math.ceil(rows.length / 4) - 1) * 4 })
watch(pageRows, () => void loadSamples(), { immediate: true })
onBeforeUnmount(() => { active = false; generation++; sampleGeneration++ })
</script>

<style scoped>
.dataset-comparison { display: grid; gap: 16px; min-width: 0; }
.comparison-toolbar, .comparison-picker, .comparison-actions, .comparison-start, .comparison-filters, .comparison-table-heading { display: flex; align-items: center; gap: 12px; min-width: 0; }
.comparison-toolbar { flex-wrap: wrap; }
.comparison-picker { color: var(--am-text-muted); white-space: nowrap; }
.comparison-picker :deep(.ui-select) { width: 160px; }
.comparison-swap { padding-inline: 8px; border-color: transparent; background: transparent; }
.comparison-actions { margin-left: auto; }
.comparison-summaries { display: grid; grid-template-columns: minmax(0, 1fr) 20px minmax(0, 1fr); gap: 12px; align-items: center; }
.comparison-card { min-width: 0; padding: 16px; border: 1px solid var(--am-border); border-radius: var(--am-radius-md); background: var(--am-surface); }
.comparison-version { min-height: 134px; }
.comparison-version-heading { display: flex; align-items: center; gap: 14px; min-height: 40px; }
.comparison-version-heading > strong { padding: 6px 18px; background: var(--am-hover-surface); border-radius: var(--am-radius-sm); font-size: 18px; font-weight: 600; }
.comparison-version--target .comparison-version-heading > strong { color: var(--am-brand-primary); background: var(--am-row-selected); }
.comparison-version-heading > div { display: grid; gap: 4px; color: var(--am-text-muted); font-size: 13px; }
.comparison-version dl { display: grid; grid-template-columns: 1fr 1fr .9fr 1.6fr; margin: 16px 0 0; }
.comparison-version dl > div { padding: 0 12px; border-left: 1px solid var(--am-border); min-width: 0; }
.comparison-version dl > div:first-child { border: 0; padding-left: 0; }
.comparison-version dl > div:last-child { padding-right: 0; }
.comparison-version dd { margin: 0 0 6px; font-size: 20px; line-height: 1.4; font-variant-numeric: tabular-nums; white-space: nowrap; }
.comparison-version dt { color: var(--am-text-muted); font-size: 12px; white-space: nowrap; }
.comparison-start { justify-content: space-between; }
.comparison-placeholder { display: grid; min-height: 100px; margin: 0; place-items: center; color: var(--am-text-muted); }
.comparison-filters { flex-wrap: wrap; gap: 12px 20px; margin-top: 4px; }
.comparison-filters p { flex: 1; min-width: 230px; color: var(--am-text-muted); font-size: 13px; margin: 0; }
.comparison-filters :deep(.ui-segment:has(:checked)) { background: var(--am-brand-primary); color: var(--am-text-on-brand, white); }
.comparison-card h2, .comparison-filters h2 { margin: 0; font-size: 16px; font-weight: 600; }
.comparison-table-heading { justify-content: space-between; margin-bottom: 12px; }
.comparison-table-heading time { color: var(--am-text-muted); font-size: 12px; }
.comparison-breakdowns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.comparison-breakdowns h2 { margin-bottom: 12px; }
.comparison-card > .dataset-table { margin: 0; width: 100%; }
.comparison-card :deep(table) { table-layout: fixed; min-width: 0; }
.comparison-card :deep(th), .comparison-card :deep(td) { padding: 10px 14px; }
.comparison-card :deep(th) { background: var(--am-surface); color: var(--am-text-muted); font-weight: 500; }
.comparison-breakdowns :deep(th), .comparison-breakdowns :deep(td) { padding-block: 6px; }
.comparison-changes :deep(th:first-child) { width: 30%; }
.comparison-changes :deep(th:last-child) { width: 120px; }
.comparison-changes :deep(td) { height: 54px; }
.comparison-card :deep(.comparison-empty) { text-align: center; color: var(--am-text-muted); height: 100px; white-space: normal; }
.comparison-split { display: inline-block; padding: 2px 12px; border-radius: var(--am-radius-sm); background: var(--am-hover-surface); }
.comparison-changes :deep(.pagination-controls) { margin-top: 12px; padding: 0; border: 0; border-radius: 0; background: transparent; }
.comparison-changes :deep(.pagination-controls__summary) { font-weight: 400; font-size: 13px; }
.comparison-card :deep(.comparison-increase) { color: var(--am-brand-primary); }
.comparison-card :deep(.comparison-decrease) { color: var(--am-danger-text); }
.comparison-limit, .comparison-notice { font-size: 13px; margin: 0; line-height: 1.7; }
.comparison-limit { margin-top: 12px; }
.comparison-notice { color: var(--am-text-muted); }
@media (max-width: 1100px) {
  .comparison-picker :deep(.ui-select) { width: 130px; }
  .comparison-version dd { font-size: 18px; }
  .comparison-version dl > div { padding-inline: 8px; }
  .comparison-card :deep(th), .comparison-card :deep(td) { padding: 8px 10px; }
}
@media (max-width: 800px) {
  .comparison-summaries, .comparison-breakdowns { grid-template-columns: 1fr; }
  .comparison-direction { display: none; }
  .comparison-version { min-height: auto; }
  .comparison-actions { margin-left: 0; }
}
</style>
