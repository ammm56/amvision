<template>
  <div class="dataset-sample-structure">
    <nav class="dataset-structure-tree" :aria-label="label('样本结构', 'Sample structure')">
      <h2>{{ label('样本结构', 'Sample structure') }}</h2>
      <div class="dataset-structure-root" :title="workspace.dataset.display_name"><Folder :size="16" /><span>{{ workspace.dataset.display_name }} · v{{ workspace.version_number }}</span></div>
      <template v-for="split in splits" :key="split">
        <button class="dataset-structure-split" :aria-expanded="expanded.has(split)" @click="toggle(split)"><ChevronDown v-if="expanded.has(split)" :size="14" /><ChevronRight v-else :size="14" /><Folder :size="16" />{{ split }} <small>({{ workspace.split_counts[split].toLocaleString() }})</small></button>
        <div v-if="expanded.has(split)" class="dataset-structure-leaves">
          <button v-for="sample in pages[split]?.items || []" :key="sample.sample_id" :title="sample.file_name" :class="{ 'is-selected': selected?.sample_id === sample.sample_id }" @click="selected = sample"><FileImage :size="15" /><span>{{ sample.file_name }}</span></button>
          <span v-if="pending.has(split)" role="status">{{ text('loading') }}</span>
          <button v-else-if="(pages[split]?.items.length || 0) < workspace.split_counts[split]" @click="load(split)">{{ label('加载更多', 'Load more') }}</button>
        </div>
      </template>
    </nav>
    <div class="dataset-structure-main">
      <InlineError v-if="error" :message="error" />
      <template v-if="selected">
        <header><h2 :title="selected.file_name">{{ selected.file_name }}</h2><span>{{ `v${workspace.version_number} / ${selected.split} / ${selected.file_name}` }}</span></header>
        <section class="dataset-structure-summary">
          <DatasetSampleImage :dataset-id="workspace.dataset_id" :sample="selected" :categories="workspace.categories" :show-annotations="true" :selected-object="objectId" :pose-schemas="poseSchemas" />
          <div class="dataset-structure-summary-info">
            <h3>{{ text('sampleInfo') }}</h3>
            <ResourceTable class="dataset-table" :label="text('sampleInfo')"><thead><tr><th style="width:70px">{{ label('内容', 'Content') }}</th><th>{{ label('样本数据', 'Sample data') }}</th><th style="width:92px">{{ text('actions') }}</th></tr></thead><tbody>
              <tr><td>{{ text('image') }}</td><td :title="selected.file_name">{{ selected.file_name }}<small>{{ selected.width }} × {{ selected.height }} px · {{ selected.split }}</small></td><td><button class="dataset-object-name dataset-structure-link" @click="emit('sample', selected)">{{ label('查看大图', 'View image') }}</button></td></tr>
              <tr><td>{{ label('标注', 'Annotations') }}</td><td>{{ selected.annotations.length }} {{ text('object') }}<small>{{ typeof workspace.metadata.format_type === 'string' ? workspace.metadata.format_type.toUpperCase() : workspace.task_type }}</small></td><td><button class="dataset-object-name dataset-structure-link" @click="rawOpen = !rawOpen">{{ text('view') }}</button></td></tr>
            </tbody></ResourceTable>
            <pre v-if="rawOpen" class="dataset-json">{{ JSON.stringify(selected.annotations, null, 2) }}</pre>
          </div>
        </section>
        <section class="resource-section dataset-structure-objects">
          <h3>{{ selected.annotations.length }} {{ text('object') }}<span v-if="categorySummary">：{{ categorySummary }}</span></h3>
          <div class="dataset-object-cards">
            <button v-for="(item, index) in selected.annotations.slice(0, objectLimit)" :key="item.annotation_id" :class="{ 'is-selected': objectId === item.annotation_id }" @click="objectId = item.annotation_id">
              <DatasetSampleImage :dataset-id="workspace.dataset_id" :sample="selected" :categories="workspace.categories" :show-annotations="true" :crop-object="item.annotation_id" :pose-schemas="poseSchemas" />
              <span><strong :style="{ color: annotationColor(item.category_id) }">{{ categoryName(item.category_id) }}</strong><small>#{{ index + 1 }}</small></span>
            </button>
          </div>
          <Button v-if="objectLimit < selected.annotations.length" @click="objectLimit += 12">{{ label('加载更多', 'Load more') }}</Button>
        </section>
      </template>
      <div v-else class="dataset-empty">{{ pending.size ? text('loading') : text('noMatches') }}</div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Folder, FileImage, ChevronDown, ChevronRight } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { annotationColor } from '../annotations'
import DatasetSampleImage from './DatasetSampleImage.vue'
import { listDatasetSamples, type DatasetWorkspace, type DatasetSample, type DatasetPage } from '../services/dataset-workspace.service'
import { datasetError, useDatasetText } from '../dataset-workspace'
const props = defineProps<{ workspace: DatasetWorkspace }>()
const emit = defineEmits<{ sample: [sample: DatasetSample] }>()
const text = useDatasetText(), { locale } = useI18n()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const splits = computed(() => ['train', 'val', 'test', ...Object.keys(props.workspace.split_counts).filter(key => !['train', 'val', 'test'].includes(key))].filter(key => props.workspace.split_counts[key] > 0))
const poseSchemas = computed(() => (props.workspace.metadata.pose_category_schemas || {}) as Record<string, unknown>)
const pages = ref<Record<string, DatasetPage<DatasetSample>>>({}), expanded = ref(new Set<string>()), pending = ref(new Set<string>()), selected = ref<DatasetSample | null>(null), objectId = ref(''), error = ref('')
let controller = new AbortController(), generation = 0
function categoryName(id: number | null) { return props.workspace.categories.find(c => c.category_id === id)?.name || String(id ?? '—') }
const rawOpen = ref(false), objectLimit = ref(12)
const categorySummary = computed(() => {
  const counts = new Map<string, number>()
  for (const item of selected.value?.annotations || []) { const name = categoryName(item.category_id); counts.set(name, (counts.get(name) || 0) + 1) }
  return [...counts].map(([name, count]) => `${name} × ${count}`).join('、')
})
watch(selected, () => { objectId.value = ''; rawOpen.value = false; objectLimit.value = 12 })
async function load(split: string) {
  if (pending.value.has(split)) return
  const request = generation
  pending.value.add(split); error.value = ''
  try {
    const result = await listDatasetSamples(props.workspace.dataset_id, props.workspace.dataset_version_id, { split, offset: pages.value[split]?.items.length || 0, limit: 40, sort: 'filename' }, controller.signal)
    if (request !== generation) return
    pages.value[split] = { ...result, items: [...(pages.value[split]?.items || []), ...result.items] }
    if (!selected.value) selected.value = result.items[0] || null
  } catch (e) { if (request === generation && !controller.signal.aborted) error.value = datasetError(e) }
  finally { if (request === generation) pending.value.delete(split) }
}
function toggle(split: string) { if (expanded.value.has(split)) expanded.value.delete(split); else { expanded.value.add(split); if (!pages.value[split]) void load(split) } }
watch(() => props.workspace, () => {
  generation++; controller.abort(); controller = new AbortController(); pages.value = {}; pending.value = new Set(); expanded.value = new Set(); selected.value = null
  if (splits.value[0]) toggle(splits.value[0])
}, { immediate: true })
onBeforeUnmount(() => { generation++; controller.abort() })
</script>
<style scoped>
.dataset-sample-structure { display:grid; grid-template-columns:280px minmax(0,1fr); gap:20px; min-width:0; }
.dataset-structure-tree { background:var(--am-surface); border:1px solid var(--am-border); border-radius:var(--am-radius-md); padding:68px 12px 16px; align-self:stretch; max-height:680px; min-height:520px; overflow:auto; }
.dataset-structure-tree h2 { font-size:14px; margin:4px 0 16px; }
.dataset-structure-root,.dataset-structure-tree button { display:flex; align-items:center; gap:8px; min-width:0; }
.dataset-structure-root { font-size:13px; padding:8px 0; }
.dataset-structure-root span,.dataset-structure-leaves button span { overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.dataset-structure-tree svg { flex-shrink:0; }
.dataset-structure-tree button { width:100%; border:0; border-radius:var(--am-radius-sm); padding:9px 6px; text-align:left; color:var(--am-text); background:none; cursor:pointer; font-size:13px; }
.dataset-structure-tree button:hover { background:var(--am-hover-surface); }
.dataset-structure-tree button.is-selected { background:var(--am-row-selected); color:var(--am-brand-primary); }
.dataset-structure-leaves { padding-left:25px; }
.dataset-structure-leaves > span { font-size:12px; color:var(--am-text-muted); }
.dataset-structure-main { display:grid; align-content:start; gap:16px; min-width:0; }
.dataset-structure-main h2 { font-size:20px; margin:0 0 6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.dataset-structure-main header > span { display:block; color:var(--am-text-muted); font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.dataset-structure-summary { display:grid; grid-template-columns:minmax(180px,.85fr) minmax(0,1.6fr); gap:20px; padding:16px; background:var(--am-surface); border:1px solid var(--am-border); border-radius:var(--am-radius-md); }
.dataset-structure-summary :deep(.dataset-sample-image) { height:250px; border-radius:var(--am-radius-sm); }
.dataset-structure-summary-info { min-width:0; display:grid; gap:16px; align-content:start; justify-items:stretch; }
.dataset-structure-main h3 { font-size:14px; margin:0; }
.dataset-structure-summary .dataset-details { margin:0; grid-template-columns:65px minmax(0,1fr); font-size:13px; }
.dataset-object-name { border:0; padding:0; background:none; color:inherit; cursor:pointer; max-width:100%; overflow:hidden; text-overflow:ellipsis; }
@media(max-width:1200px) { .dataset-sample-structure { grid-template-columns:220px minmax(0,1fr); gap:14px; } .dataset-structure-summary { gap:12px; padding:12px; } }
.dataset-structure-summary-info :deep(td) { padding:16px 10px; }
.dataset-structure-summary-info small { display:block; margin-top:8px; color:var(--am-text-muted); font-size:12px; }
.dataset-structure-link { color:var(--am-brand-primary); }
.dataset-structure-objects { display:grid; gap:16px; }
.dataset-structure-objects h3 { line-height:1.7; overflow-wrap:anywhere; }
.dataset-object-cards { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.dataset-object-cards > button { display:flex; align-items:flex-start; gap:12px; min-width:0; padding:10px; background:var(--am-surface); color:var(--am-text); border:1px solid var(--am-border); border-radius:var(--am-radius-sm); text-align:left; cursor:pointer; }
.dataset-object-cards > button:hover { background:var(--am-hover-surface); }
.dataset-object-cards > button.is-selected { border-color:var(--am-brand-primary); }
.dataset-object-cards :deep(.dataset-sample-image) { width:92px; height:92px; flex:0 0 92px; border-radius:var(--am-radius-sm); }
.dataset-object-cards > button > span { min-width:0; }
.dataset-object-cards strong { display:block; overflow-wrap:anywhere; font-size:13px; font-weight:500; }
.dataset-object-cards small { display:block; color:var(--am-text-muted); margin-top:8px; }
@media(max-width:1350px) { .dataset-object-cards { grid-template-columns:repeat(2,minmax(0,1fr)); } .dataset-structure-summary { grid-template-columns: minmax(140px,.7fr) minmax(0,1fr); } }
@media(max-width:1100px) { .dataset-structure-summary { grid-template-columns:1fr; } .dataset-structure-summary :deep(.dataset-sample-image) { height:180px; } }
</style>
