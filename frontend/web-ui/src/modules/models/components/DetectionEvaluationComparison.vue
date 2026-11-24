<template>
  <section class="evaluation-comparison">
    <PageHeader class="comparison-heading">
      <template #heading>
        <Button size="sm" variant="ghost" class="comparison-back" @click="emit('back')"><ArrowLeft :size="16" />{{ zh ? '返回评估列表' : 'Back to evaluations' }}</Button>
        <h1>{{ zh ? '评估结果比较' : 'Compare evaluations' }}</h1>
      </template>
      <template v-if="reference" #actions>
        <Button v-if="candidate" @click="emit('samples', candidate.task.task_id)"><CircleAlert :size="16" />{{ zh ? '查看错误样本' : 'View sample errors' }}</Button>
        <template v-else>
          <span>{{ zh ? '基线' : 'Baseline' }}</span>
          <Select class="baseline-select" :model-value="baseline" :options="options" :aria-label="zh ? '基线结果' : 'Baseline result'" @update:model-value="emit('baseline', String($event))" />
        </template>
        <Button variant="primary" @click="download"><Download :size="16" />{{ zh ? '下载比较报告' : 'Download comparison' }}</Button>
      </template>
    </PageHeader>
    <section v-if="error || loading" class="resource-section comparison-message">
      <p v-if="error" role="alert">{{ error }} <Button @click="emit('retry')">{{ zh ? '重试' : 'Retry' }}</Button></p>
      <p v-else role="status">{{ zh ? '正在加载报告…' : 'Loading reports…' }}</p>
    </section>
    <template v-else-if="reference && scope">
      <dl class="comparison-scope resource-section">
        <div><Database :size="23" aria-hidden="true" /><div><dt>{{ zh ? '数据集版本' : 'Dataset version' }}</dt><dd :title="scope.version ?? undefined">{{ datasetLabel }}</dd><small>{{ samples(scope) }}</small></div></div>
        <div><dt>{{ zh ? '任务类型' : 'Task type' }}</dt><dd>{{ zh ? '目标检测' : 'Detection' }}</dd></div>
        <div><dt>{{ zh ? '运行后端' : 'Runtime' }}</dt><dd>{{ commonRuntime || (zh ? '见各结果列' : 'See results') }}</dd></div>
        <div><dt>{{ zh ? '评估规则' : 'Evaluation rules' }}</dt><dd>{{ zh ? '相同评估规则' : 'Matching evaluation rules' }}</dd><small>{{ describeComparisonRules(scope) }}</small></div>
        <div><dt>{{ zh ? '预处理' : 'Preprocessing' }}</dt><dd>{{ commonInput || (hasInput ? (zh ? '见配置对比' : 'See configuration') : (zh ? '历史报告未记录' : 'Not recorded')) }}</dd></div>
      </dl>
      <section class="resource-section comparison-section" :aria-label="zh ? '主要指标' : 'Key metrics'">
        <table class="comparison-table comparison-table--metrics">
          <thead><tr><th scope="col">{{ zh ? '指标' : 'Metric' }}</th>
            <th v-for="row in rows" :key="row.task.task_id" scope="col" :class="{ 'is-baseline': row.task.task_id === baseline }">
              <div class="comparison-result">
                <div><strong>{{ row.task.display_name }}</strong><small>{{ evaluationRuntime(row) }} <span v-if="row.task.task_id === baseline" class="baseline-badge">{{ zh ? '基线' : 'Baseline' }}</span></small></div>
                <Button v-if="row.task.task_id !== baseline && rows.length > 2" class="comparison-remove" variant="ghost" size="sm" icon-only :aria-label="`${zh ? '移除' : 'Remove'} ${row.task.display_name}`" @click="emit('remove', row.task.task_id)"><X :size="16" /></Button>
              </div>
            </th>
            <th v-if="candidate" scope="col">{{ zh ? '差值' : 'Difference' }}</th>
          </tr></thead>
          <tbody><tr v-for="key in comparisonMetrics" :key="key">
            <th scope="row">{{ key === 'map50' ? 'mAP50' : 'mAP50–95' }}</th>
            <td v-for="row in rows" :key="row.task.task_id">
              <strong>{{ evaluationMetric(row.report[key]) }}</strong>
              <small v-if="!candidate" :class="evaluationDelta(row.report[key], reference.report[key]).tone">{{ row.task.task_id === baseline ? '—' : evaluationDelta(row.report[key], reference.report[key]).text }}</small>
            </td>
            <td v-if="candidate"><strong :class="evaluationDelta(candidate.report[key], reference.report[key]).tone">{{ evaluationDelta(candidate.report[key], reference.report[key]).text }}</strong></td>
          </tr></tbody>
        </table>
      </section>
      <p class="comparison-note"><Info :size="15" aria-hidden="true" />{{ zh
        ? '差值按原始精度计算，再保留三位小数，可能与表中显示值直接相减的结果不同。'
        : 'Differences are calculated at full precision, then rounded to three decimal places. They may differ from subtracting the displayed values.' }}</p>
      <TabList v-model="activeTab" :tabs="tabs" :label="zh ? '比较明细' : 'Comparison details'" />
      <section class="resource-section comparison-section" role="tabpanel" :aria-label="tabs.find(tab => tab.id === activeTab)?.label">
        <table class="comparison-table">
          <thead><tr><th scope="col">{{ activeTab === 'classes' ? (zh ? '类别' : 'Class') : (zh ? '设置' : 'Setting') }}</th>
            <th v-for="row in rows" :key="row.task.task_id" scope="col" :class="{ 'is-baseline': row.task.task_id === baseline }">
              {{ row.task.display_name }}<small class="comparison-column-runtime">{{ evaluationRuntime(row) }} <span v-if="row.task.task_id === baseline" class="baseline-badge">{{ zh ? '基线' : 'Baseline' }}</span></small>
            </th>
            <th v-if="candidate && activeTab === 'classes'" scope="col">{{ zh ? '差值' : 'Difference' }}</th>
          </tr></thead>
          <template v-if="activeTab === 'classes'">
            <tbody>
              <tr v-for="item in reference.report.per_class_metrics" :key="item.class_id"><th scope="row">{{ item.class_name }}</th>
                <td v-for="row in rows" :key="row.task.task_id">{{ evaluationMetric(classAp(row, item.class_id)) }}</td>
                <td v-if="candidate" :class="evaluationDelta(classAp(candidate, item.class_id), item.ap50_95).tone">{{ evaluationDelta(classAp(candidate, item.class_id), item.ap50_95).text }}</td>
              </tr>
              <tr v-if="!reference.report.per_class_metrics?.length"><td :colspan="rows.length + 1">{{ zh ? '报告没有类别明细。' : 'No class breakdown is available.' }}</td></tr>
            </tbody>
            <tfoot v-if="reference.report.per_class_metrics?.length"><tr>
              <th scope="row">{{ zh ? '类别均值' : 'Class mean' }}</th>
              <td v-for="row in rows" :key="row.task.task_id">{{ evaluationMetric(evaluationClassMean(row)) }}</td>
              <td v-if="candidate" :class="evaluationDelta(evaluationClassMean(candidate), evaluationClassMean(reference)).tone">{{ evaluationDelta(evaluationClassMean(candidate), evaluationClassMean(reference)).text }}</td>
            </tr></tfoot>
          </template>
          <tbody v-else><tr v-for="item in configuration" :key="item.label"><th scope="row">{{ item.label }}</th><td v-for="row in rows" :key="row.task.task_id">{{ item.value(row) }}</td></tr></tbody>
        </table>
      </section>
      <p class="comparison-note"><Info :size="15" aria-hidden="true" />{{ zh ? '耗时受运行设备影响，本页不比较耗时。' : 'Timing depends on the device and is not compared here.' }}</p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ArrowLeft, CircleAlert, Database, Download, Info, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import Button from '@/shared/ui/components/Button.vue'
import Select from '@/shared/ui/components/Select.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'
import PageHeader from '@/shared/ui/layout/PageHeader.vue'
import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import { comparisonMetrics, comparisonScope, describeComparisonRules, evaluationClassMean, evaluationDelta, evaluationInputDescription, evaluationMetric, evaluationRuntime, type EvaluationComparisonRow } from '../detection-evaluation-comparison'
import { formatModelNumber } from '../model-number-format'
import { downloadEvaluationJson } from '../services/model-evaluation.service'

const props = defineProps<{ zh: boolean; rows: EvaluationComparisonRow[]; baseline: string; error: string; loading: boolean; datasets: DatasetExportSummary[]; versionNames?: ReadonlyMap<string, string> }>()
const emit = defineEmits<{ back: []; retry: []; baseline: [id: string]; remove: [id: string]; samples: [id: string] }>()
const activeTab = ref('classes')
const reference = computed(() => props.rows.find(row => row.task.task_id === props.baseline))
const candidate = computed(() => props.rows.length === 2 ? props.rows.find(row => row.task.task_id !== props.baseline) : undefined)
const scope = computed(() => reference.value ? comparisonScope(reference.value) : null)
const datasetLabel = computed(() => {
  const dataset = props.datasets.find(item => item.dataset_export_id === scope.value?.exportId)
  if (dataset?.display_name) return `${dataset.display_name}${dataset.version_number != null ? ` · v${dataset.version_number}` : ''}`
  return scope.value?.version ?? scope.value?.exportId ?? '—'
})
const commonRuntime = computed(() => {
  const runtimes = new Set(props.rows.map(evaluationRuntime))
  return runtimes.size === 1 ? [...runtimes][0] : ''
})
const hasInput = computed(() => props.rows.some(row => evaluationInputDescription(row)))
const commonInput = computed(() => {
  const descriptions = new Set(props.rows.map(evaluationInputDescription))
  // 完整的契约必须都有记录并相同，摘要才能代表所有结果列。
  const contracts = props.rows.map(row => row.report.execution?.model_input_spec)
  const sameContract = contracts.every(spec => spec && JSON.stringify(spec) === JSON.stringify(contracts[0]))
  return sameContract && descriptions.size === 1 ? [...descriptions][0] : ''
})
const options = computed(() => props.rows.map(row => ({ value: row.task.task_id, label: row.task.display_name })))
const tabs = computed(() => [{ id: 'classes', label: props.zh ? '按类别 AP50–95' : 'AP50–95 by class' }, { id: 'config', label: props.zh ? '配置对比' : 'Configuration' }])
const configuration = computed(() => [
  { label: props.zh ? '模型版本' : 'Model version', value: (row: EvaluationComparisonRow) => props.versionNames?.get(row.task.model_version_id) || row.task.model_type || '—' },
  { label: props.zh ? '数据集导出' : 'Dataset export', value: (row: EvaluationComparisonRow) => comparisonScope(row).exportId ?? '—' },
  { label: props.zh ? '样本范围' : 'Sample scope', value: (row: EvaluationComparisonRow) => samples(comparisonScope(row)) },
  { label: props.zh ? '运行后端' : 'Runtime', value: evaluationRuntime },
  { label: props.zh ? '预处理' : 'Preprocessing', value: (row: EvaluationComparisonRow) => evaluationInputDescription(row) || '—' },
  { label: props.zh ? '置信度阈值' : 'Score threshold', value: (row: EvaluationComparisonRow) => displayRule(comparisonScope(row).score) },
  { label: props.zh ? 'NMS 阈值' : 'NMS threshold', value: (row: EvaluationComparisonRow) => displayRule(comparisonScope(row).nms) },
])

function samples(value: ReturnType<typeof comparisonScope>): string {
  return `${value.split ?? '—'} · ${value.count ?? '—'} ${props.zh ? '张' : 'images'}`
}
function displayRule(value: number | null): string { return value === null ? '—' : formatModelNumber(value, 4) }
function classAp(row: EvaluationComparisonRow, classId: number): number | undefined {
  return row.report.per_class_metrics?.find(item => item.class_id === classId)?.ap50_95
}
function download(): void {
  if (!reference.value) return
  downloadEvaluationJson('detection-evaluation-comparison.json', {
    baseline_task_id: props.baseline,
    results: props.rows.map(({ task, report }) => ({ task_id: task.task_id, model_type: task.model_type,
      model_version_id: task.model_version_id, dataset_export_id: task.dataset_export_id,
      dataset_version_id: task.dataset_version_id, display_name: task.display_name, metrics: {
        map50_95: report.map50_95, map50: report.map50, per_class: report.per_class_metrics,
        class_mean_ap50_95: evaluationClassMean({ task, report }),
      }, runtime: evaluationRuntime({ task, report }), execution: report.execution,
      configuration: comparisonScope({ task, report }) })),
  })
}
</script>

<style scoped>
.evaluation-comparison { display:grid; gap:14px; min-width:0; }
.comparison-heading { align-items:flex-end; }
.comparison-heading h1 { display:block; margin:0; }
.comparison-back { justify-self:start; }
.baseline-select { width:min(228px, 28vw); }
.comparison-scope { display:grid; grid-template-columns:minmax(0,1.45fr) repeat(4,minmax(0,1fr)); padding:14px; margin:0; }
.comparison-scope > div { padding:0 12px; border-inline-start:1px solid var(--am-border); min-width:0; }
.comparison-scope > div:first-child { display:flex; align-items:center; gap:10px; border:0; }
.comparison-scope svg { flex:none; }
.comparison-scope :is(dt,small),.comparison-result small,.comparison-note,.comparison-column-runtime { color:var(--am-text-muted); }
.comparison-scope dd { margin:2px 0; font-weight:600; overflow-wrap:anywhere; }
.comparison-section { padding:12px; min-width:0; }
.comparison-table { width:100%; table-layout:fixed; border-collapse:separate; border-spacing:0; border:1px solid var(--am-border); border-radius:6px; overflow:hidden; }
.comparison-table th:first-child { width:18%; text-align:start; }
.comparison-table :is(th,td) { padding:8px 10px; border-inline-end:1px solid var(--am-border); border-block-end:1px solid var(--am-border); text-align:center; overflow-wrap:anywhere; white-space:normal; }
.comparison-table :is(th,td):last-child { border-inline-end:0; }
.comparison-table :is(tbody,tfoot):last-child tr:last-child > * { border-block-end:0; }
.comparison-table :is(thead,tfoot) { background:var(--am-surface-muted); }
.comparison-table .is-baseline { background:var(--am-success-surface); }
.comparison-table tbody th { font-weight:500; }
.comparison-result { display:flex; align-items:flex-start; justify-content:space-between; gap:4px; text-align:start; }
.comparison-result > div { flex:1; min-width:0; }
.comparison-result small,.comparison-table--metrics td small,.comparison-column-runtime { display:block; }
.comparison-table--metrics td strong { font-size:var(--am-type-section); }
.comparison-table--metrics td small { color:var(--am-text-muted); }
.comparison-table .positive { color:var(--am-success-text); }
.comparison-table .negative { color:var(--am-danger-text); }
.comparison-remove { flex:none; }
.comparison-table tfoot td { font-weight:700; }
.baseline-badge { flex:none; white-space:nowrap; padding:1px 4px; border:1px solid var(--am-success-border); border-radius:4px; font-size:var(--am-type-caption); }
:deep(.local-tabs) { border-bottom:1px solid var(--am-border); padding:0; border-radius:0; background:transparent; }
:deep(.local-tabs__tab) { border-radius:0; border-bottom:2px solid transparent; }
:deep(.local-tabs__tab.is-active) { background:transparent; color:var(--am-success-text); border-bottom-color:var(--am-brand-primary); }
.comparison-note { display:flex; align-items:center; gap:6px; margin:0; }
.comparison-message p { margin:0; }
@media (max-width: 800px) {
  .comparison-scope { grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
  .comparison-scope > div:nth-child(odd) { border:0; }
  .comparison-table :is(th,td) { padding:6px 4px; }
  .comparison-heading :deep(.page-actions) { max-width:100%; }
}
</style>
