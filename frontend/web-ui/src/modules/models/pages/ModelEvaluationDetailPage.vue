<template>
  <section class="page-stack task-report model-workspace">
    <RouterLink :to="{ path: '/models', query: { tab: 'evaluation', evaluation: kind } }">{{ zh ? '返回评估列表' : 'Back to evaluations' }}</RouterLink>
    <header>
      <div class="report-heading"><h1>{{ reportTitle }}</h1><TaskStateBadge v-if="task" :state="task.state" /></div>
      <div class="report-actions">
        <Button v-if="report && ['classification','pose','obb'].includes(kind)" @click="showErrors">{{ zh ? '查看错误样本' : 'View errors' }}</Button>
        <Button v-if="report" variant="primary" @click="downloadEvaluationJson(`${taskId}-report.json`, report)"><Download :size="16" />{{ zh ? '下载报告' : 'Download report' }}</Button>
        <Button v-if="session.hasScopes(['tasks:write']) && ['queued', 'running'].includes(task?.state || '')" @click="confirmCancel = true">{{ zh ? '取消任务' : 'Cancel task' }}</Button>
        <Button :loading="loading" @click="revision++">{{ zh ? '刷新' : 'Refresh' }}</Button>
      </div>
    </header>
    <InlineError :message="error || task?.error_message || ''" />
    <dl v-if="task && kind === 'classification'" class="resource-section classification-report-context">
      <div>
        <dt>{{ zh ? '模型版本' : 'Model version' }}</dt>
        <dd>{{ modelVersionName || '—' }}</dd>
      </div>
      <div>
        <dt>{{ zh ? '数据集导出' : 'Dataset export' }}</dt>
        <dd>{{ datasetExportLabel || '—' }}</dd>
      </div>
      <div>
        <dt>{{ zh ? '评估范围' : 'Evaluation scope' }}</dt>
        <dd>{{ evaluationScope || '—' }}</dd>
      </div>
      <div>
        <dt v-if="task.finished_at">{{ zh ? '完成时间' : 'Finished' }}</dt>
        <dt v-else>{{ zh ? '创建时间' : 'Created' }}</dt>
        <dd><time :datetime="task.finished_at || task.created_at">{{ formatSystemDateTime(task.finished_at || task.created_at, 'minutes') }}</time></dd>
      </div>
    </dl>
    <div v-else-if="task" class="resource-section report-context">
      <span>{{ evaluationTypes[kind][zh ? 0 : 1] }}</span>
      <span v-if="modelVersionName">{{ modelVersionName }}</span>
      <span v-if="datasetExportLabel" :title="evaluationDatasetVersionId || undefined">{{ datasetExportLabel }}</span>
      <span v-if="sampleCount != null">{{ evaluationScope }}</span>
      <time :datetime="task.finished_at || task.created_at">{{ formatSystemDateTime(task.finished_at || task.created_at, 'minutes') }}</time>
    </div>
    <p v-if="active" class="resource-section" role="status">{{ activeStatus }}</p>
    <template v-if="report">
      <div class="report-columns" :class="{ 'report-columns--classification': kind === 'classification' }">
        <article v-if="kind === 'classification'" class="resource-section">
          <h2>{{ zh ? '类别分布' : 'Class distribution' }} <small v-if="split">({{ split }})</small></h2>
          <dl class="report-metrics report-metrics--distribution">
            <div v-for="row in report.per_class_metrics" :key="row.class_id"><dt>{{ row.class_name }}</dt><dd>{{ row.sample_count ?? '—' }}</dd></div>
          </dl>
        </article>
        <article v-if="kind !== 'segmentation'" class="resource-section">
          <h2>{{ kind === 'pose' ? (zh ? '关键点精度（OKS）' : 'Keypoint accuracy (OKS)') : kind === 'obb' ? (zh ? '检测精度（Rotated IoU）' : 'Detection accuracy (Rotated IoU)') : (zh ? '评估指标' : 'Evaluation metrics') }}</h2>
          <dl class="report-metrics"><div v-for="metric in mainMetrics" :key="metric.label"><dt>{{ metric.label }}</dt><dd>{{ metric.value }}</dd></div></dl>
        </article>
        <template v-else>
          <article v-for="metric in mainMetrics" :key="metric.label" class="resource-section">
            <h2>{{ metric.label }}</h2>
          <dl class="report-metrics">
            <div><dt>mAP50–95</dt><dd>{{ metric.value }}</dd></div>
            <div><dt>mAP50</dt><dd>{{ metric.ap50 }}</dd></div>
          </dl>
          </article>
        </template>
        <article v-if="kind === 'pose' || kind === 'obb'" class="resource-section">
          <h2>{{ zh ? '评估范围' : 'Evaluation scope' }}</h2>
          <dl class="report-metrics">
            <div><dt>{{ zh ? '已处理图像' : 'Processed images' }}</dt><dd>{{ report.sample_count ?? '—' }}</dd></div>
            <div v-if="kind === 'pose'"><dt>{{ zh ? '每实例关键点数' : 'Keypoints per instance' }}</dt><dd>{{ report.keypoint_count ?? '—' }}</dd></div>
          </dl>
        </article>
      </div>
      <article v-if="kind === 'classification' && report.confusion_matrix" class="resource-section">
        <h2>{{ zh ? '混淆矩阵（行：标注，列：预测）' : 'Confusion matrix (rows: actual, columns: predicted)' }}</h2>
        <EvaluationConfusionMatrix :labels="report.confusion_matrix.labels.map(label => label ?? (zh ? '未识别' : 'Unrecognized'))" :rows="report.confusion_matrix.rows" :zh="zh" />
      </article>
      <component :is="kind === 'segmentation' ? 'article' : 'details'" v-if="kind !== 'classification' && report.per_class_metrics?.length" class="resource-section report-class-results">
        <h2 v-if="kind === 'segmentation'">{{ zh ? '类别结果' : 'Class results' }}</h2>
        <summary v-else>{{ zh ? '类别结果' : 'Class results' }}</summary>
        <div class="resource-table">
          <table>
            <thead><tr><th scope="col">{{ zh ? '类别' : 'Class' }}</th><th scope="col">{{ classHeading }}</th><th scope="col">{{ kind === 'segmentation' ? 'Mask AP50–95' : kind === 'pose' ? 'OKS AP50' : 'Rotated AP50' }}</th></tr></thead>
            <tbody><tr v-for="row in report.per_class_metrics" :key="row.category_id">
              <th scope="row">{{ row.category_name ?? row.class_name ?? row.category_id }}</th>
              <td>{{ decimal(kind === 'segmentation' ? row.bbox_ap50_95 : row.ap50_95) }}</td><td>{{ decimal(kind === 'segmentation' ? row.mask_ap50_95 : row.ap50) }}</td>
            </tr></tbody>
            <tfoot v-if="kind === 'segmentation'">
              <tr><th scope="row">{{ zh ? '平均（mAP50–95）' : 'Mean (mAP50–95)' }}</th><td>{{ decimal(report.map50_95) }}</td><td>{{ decimal(report.mask_map50_95) }}</td></tr>
            </tfoot>
          </table>
        </div>
      </component>
      <div ref="sampleSection" tabindex="-1" :class="{ 'report-columns': kind === 'pose' || kind === 'obb' }">
        <ModelEvaluationSamplePreview v-model:issue="sampleIssue" :key="taskId" :task-id="taskId" :kind="kind" :zh="zh" :definitions="report.keypoint_definitions" />
        <article v-if="kind === 'pose'" class="resource-section pose-spec">
          <h2>{{ zh ? '关键点定义' : 'Keypoint definitions' }}</h2>
          <div v-for="definition in report.keypoint_definitions" :key="definition.id" class="pose-definition">
            <h3>{{ definition.name }} <small v-if="definition.keypoints?.length">· {{ definition.keypoints.length }} {{ zh ? '个关键点' : 'keypoints' }}</small></h3>
            <template v-if="definition.keypoints?.length">
              <ol class="pose-definition__list"><li v-for="(point, index) in definition.keypoints.slice(0, 4)" :key="index">{{ point }}</li></ol>
              <details v-if="definition.keypoints.length > 4">
                <summary>{{ zh ? '全部关键点' : 'All keypoints' }} ({{ definition.keypoints.length }})</summary>
                <ol start="5" class="pose-definition__list"><li v-for="(point, index) in definition.keypoints.slice(4)" :key="index">{{ point }}</li></ol>
              </details>
              <p>{{ definition.skeleton?.length ? (zh ? `记录了 ${definition.skeleton.length} 条骨架连线。` : `${definition.skeleton.length} saved skeleton edges.`) : (zh ? '此定义未保存骨架连线。' : 'This definition has no saved skeleton edges.') }}</p>
            </template>
            <p v-else>{{ zh ? '评估数据未提供关键点名称。' : 'The evaluation data has no keypoint names.' }}</p>
          </div>
          <p v-if="!report.keypoint_definitions?.length" role="status">{{ zh ? '此报告没有保存关键点定义。' : 'This report has no saved keypoint definitions.' }}</p>
          <details v-if="report.evaluation_policy?.oks_sigmas?.length">
            <summary>{{ zh ? '关键点评估参数' : 'Keypoint evaluation parameters' }}</summary>
            <dl class="pose-policy">
              <div v-if="report.evaluation_policy.version"><dt>{{ zh ? '规则版本' : 'Policy version' }}</dt><dd>{{ report.evaluation_policy.version }}</dd></div>
              <div v-if="report.evaluation_policy.score_threshold != null"><dt>{{ zh ? '置信度阈值' : 'Score threshold' }}</dt><dd>{{ formatSmallModelNumber(report.evaluation_policy.score_threshold) }}</dd></div>
              <div v-if="report.evaluation_policy.nms_threshold != null"><dt>NMS</dt><dd>{{ formatSmallModelNumber(report.evaluation_policy.nms_threshold) }}</dd></div>
              <div><dt>OKS sigma</dt><dd>{{ formatSigmas(report.evaluation_policy.oks_sigmas) }}</dd></div>
            </dl>
          </details>
          <details><summary>Bounding Box</summary><p>AP50 · {{ decimal(report.bbox_map50) }} AP50–95 · {{ decimal(report.bbox_map50_95) }}</p></details>
        </article>
        <article v-if="kind === 'obb'" class="resource-section">
          <h2>{{ zh ? '坐标系与评估规则' : 'Coordinates and evaluation rules' }}</h2>
          <div class="obb-coordinates">
            <div class="obb-axes" aria-hidden="true"><span>(0, 0)</span><span>→ X</span><span>↓ Y</span></div>
            <p>{{ zh ? '原点在图像左上角，X 向右，Y 向下。实线为标注，虚线为预测。' : 'The image origin is at the upper left. X points right and Y points down. Solid outlines are labels and dashed outlines are predictions.' }}</p>
          </div>
          <dl class="pose-policy">
            <div><dt>{{ zh ? '匹配方式' : 'Matching rule' }}</dt><dd>Rotated IoU</dd></div>
            <div v-if="report.iou_thresholds?.length"><dt>{{ zh ? '指标 IoU 范围' : 'Metric IoU range' }}</dt><dd>{{ report.iou_thresholds[0].toFixed(2) }}–{{ report.iou_thresholds.at(-1)?.toFixed(2) }}</dd></div>
          </dl>
          <div class="obb-issues">
            <Button size="sm" :aria-pressed="sampleIssue === 'angle'" @click="selectIssue('angle')">{{ zh ? '查看角度偏差' : 'View angle errors' }}</Button>
            <Button size="sm" :aria-pressed="sampleIssue === 'localization'" @click="selectIssue('localization')">{{ zh ? '查看定位偏差' : 'View localization errors' }}</Button>
          </div>
        </article>
      </div>
    </template>
    <p v-else-if="task?.state === 'succeeded' && !loading && !error" class="resource-section" role="status">
      {{ zh ? '评估报告暂不可读取。可刷新后重试。' : 'The evaluation report is unavailable. Refresh to check again.' }}
    </p>
    <ConfirmDialog v-if="confirmCancel && task"
      :title="zh ? '取消评估任务' : 'Cancel evaluation'"
      :message="zh ? '确认取消这次评估？' : 'Cancel this evaluation?'"
      :details="reportTitle"
      :cancel-label="zh ? '返回' : 'Back'"
      :confirm-label="zh ? '确认取消' : 'Confirm cancellation'"
      :busy="cancelling"
      @cancel="confirmCancel = false"
      @confirm="requestCancellation"
    />
  </section>
</template>

<script setup lang="ts">
import { useCatalogVersionLabel } from '../composables/useCatalogVersionLabel'
import { computed, ref, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Download } from '@lucide/vue'
import { getDatasetExportDetail, listDatasetExports, type DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import { getDatasetWorkspace } from '@/modules/datasets/services/dataset-workspace.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import { cancelTask } from '@/modules/tasks/services/task.service'
import { useSessionStore } from '@/app/stores/session.store'
import EvaluationConfusionMatrix from '../components/EvaluationConfusionMatrix.vue'
import ModelEvaluationSamplePreview from '../components/ModelEvaluationSamplePreview.vue'
import { evaluationDatasetExportOptions, isEligibleEvaluationExport, type EvaluationDatasetVersion } from '../evaluation-dataset-exports'
import { formatModelNumber, formatSmallModelNumber } from '../model-number-format'
import { classificationEvaluationExportId, classificationEvaluationTitle, evaluationModelVersionId, evaluationTypes } from '../model-evaluation-types'
import { additionalEvaluationKinds, downloadEvaluationJson, getModelEvaluation, getModelEvaluationReport,
  type GeometryIssue, type ModelEvaluationRecord, type ModelEvaluationReport } from '../services/model-evaluation.service'

const route = useRoute()
const session = useSessionStore()
const { locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const kind = computed(() => additionalEvaluationKinds.find(value => value === route.params.taskType) ?? 'classification')
const taskId = computed(() => String(route.params.taskId || ''))
const task = ref<ModelEvaluationRecord | null>(null)
const modelVersionName = useCatalogVersionLabel(() => [task.value?.project_id, undefined, evaluationModelVersionId(task.value)])
const evaluationExportId = computed(() => {
  const record = task.value
  if (!record) return ''
  if (kind.value === 'classification') return classificationEvaluationExportId(record)
  return record.dataset_export_id || record.metadata?.dataset_export_id || record.result?.dataset_export_id || ''
})
const evaluationDatasetVersionId = computed(() => task.value?.metadata?.dataset_version_id || task.value?.result?.dataset_version_id || '')
const reportTitle = computed(() => {
  if (kind.value === 'classification' && task.value) {
    return classificationEvaluationTitle(task.value, modelVersionName.value, zh.value)
  }
  return task.value?.display_name || (zh.value ? '评估报告' : 'Evaluation report')
})
const datasetSource = shallowRef<{
  exports: DatasetExportSummary[]
  versions: Map<string, EvaluationDatasetVersion>
} | null>(null)
const datasetExportLabel = computed(() => {
  if (!datasetSource.value && evaluationExportId.value) return ''
  const label = datasetSource.value && evaluationDatasetExportOptions(datasetSource.value.exports, datasetSource.value.versions, zh.value)
    .find(option => option.value === evaluationExportId.value)?.label
  if (label) return label
  if (evaluationExportId.value || evaluationDatasetVersionId.value) {
    return zh.value ? '数据集信息暂不可用' : 'Dataset information unavailable'
  }
  return ''
})
const report = ref<ModelEvaluationReport | null>(null)
const sampleSection = ref<HTMLElement | null>(null)
const sampleIssue = ref<GeometryIssue>('all')
function showErrors(): void {
  selectIssue(kind.value === 'classification' ? 'all' : 'errors')
}
function selectIssue(issue: GeometryIssue): void {
  sampleIssue.value = issue
  sampleSection.value?.focus({ preventScroll: true })
  sampleSection.value?.scrollIntoView({ block: 'start' })
}
const loading = ref(false)
const revision = ref(0)
const confirmCancel = ref(false)
const cancelling = ref(false)
const error = ref('')
const active = computed(() => ['queued', 'running', 'cancelling'].includes(task.value?.state || ''))
const activeStatus = computed(() => {
  if (task.value?.state === 'queued') return zh.value ? '等待评估 Worker 执行。' : 'Waiting for an evaluation worker.'
  if (task.value?.state === 'cancelling') return zh.value ? '正在取消评估。' : 'Cancelling evaluation.'
  return zh.value ? '评估 Worker 正在处理任务。' : 'The evaluation worker is processing the task.'
})
const split = computed(() => report.value?.split_name || task.value?.result?.report_summary?.split_name || '')
const sampleCount = computed(() => report.value?.sample_count ?? task.value?.sample_count)
const evaluationScope = computed(() => {
  const count = sampleCount.value
  const samples = count == null ? '' : `${count} ${zh.value ? '张' : 'images'}`
  return [split.value, samples].filter(Boolean).join(' · ')
})
const classHeading = computed(() => kind.value === 'segmentation' ? 'BBox AP50–95' : kind.value === 'pose' ? 'OKS AP50–95' : 'Rotated AP50–95')
function decimal(value?: number): string { return value == null ? '—' : value.toFixed(3) }
function formatSigmas(values: number[]): string {
  return values.every(value => value === values[0])
    ? `${formatSmallModelNumber(values[0])} × ${values.length}`
    : values.map(formatSmallModelNumber).join(' / ')
}

const mainMetrics = computed<Array<{ label: string; value: string | number; ap50?: string }>>(() => {
  const data = report.value
  if (!data) return []
  if (kind.value === 'classification') {
    const accuracy = data.top1_accuracy
    const valid = data.per_class_metrics?.length && data.per_class_metrics.every(row => typeof row.correct_count === 'number')
    const correct = valid ? data.per_class_metrics?.reduce((sum, row) => sum + (row.correct_count ?? 0), 0) : undefined
    return [
      { label: 'Top-1', value: accuracy != null && Number.isFinite(accuracy) ? `${formatModelNumber(accuracy * 100, 2)}%` : '—' },
      { label: zh.value ? '正确' : 'Correct', value: correct ?? '—' },
      { label: zh.value ? '错误' : 'Incorrect', value: correct == null || data.sample_count == null ? '—' : data.sample_count - correct },
      { label: zh.value ? '样本数' : 'Samples', value: data.sample_count ?? '—' },
    ]
  }
  if (kind.value === 'segmentation') return [
    { label: zh.value ? 'BBox 检测指标' : 'Bounding box metrics', value: decimal(data.map50_95), ap50: decimal(data.map50) },
    { label: zh.value ? 'Mask 分割指标' : 'Mask metrics', value: decimal(data.mask_map50_95), ap50: decimal(data.mask_map50) },
  ]
  if (kind.value === 'pose') return [{ label: 'OKS AP50–95', value: decimal(data.oks_ap50_95) }, { label: 'OKS AP50', value: decimal(data.oks_ap50) }]
  return [{ label: 'Rotated mAP50–95', value: decimal(data.map50_95) }, { label: 'Rotated mAP50', value: decimal(data.map50) }]
})

async function requestCancellation(): Promise<void> {
  const id = taskId.value
  if (!session.hasScopes(['tasks:write']) || !id || cancelling.value) return
  cancelling.value = true
  try {
    await cancelTask(id)
    if (id === taskId.value) revision.value++
  } catch (cause) {
    if (id === taskId.value) error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    cancelling.value = false
    confirmCancel.value = false
  }
}

watch([kind, taskId], () => { task.value = null; report.value = null; confirmCancel.value = false; sampleIssue.value = 'all' })
watch(evaluationExportId, async (id, _, onCleanup) => {
  datasetSource.value = null
  if (!id) return
  const request = new AbortController()
  onCleanup(() => request.abort())
  const { signal } = request
  const selected = await getDatasetExportDetail(id, signal).catch(() => null)
  if (signal.aborted) return
  const versions = new Map<string, EvaluationDatasetVersion>()
  if (!selected) {
    datasetSource.value = { exports: [], versions }
    return
  }
  const { dataset_id: datasetId, dataset_version_id: versionId } = selected
  const [siblings, version] = await Promise.all([
    listDatasetExports(datasetId, versionId, signal).catch(() => []),
    !selected.display_name?.trim() || selected.version_number == null
      ? getDatasetWorkspace(datasetId, versionId, signal).catch(() => null)
      : null,
  ])
  if (signal.aborted) return
  if (version) versions.set(versionId, version)
  const exports = siblings.filter(item => item.dataset_export_id !== id && item.status === 'completed'
    && isEligibleEvaluationExport(item, [selected.format_id]))
  datasetSource.value = { exports: [selected, ...exports], versions }
}, { immediate: true })
watch([kind, taskId, revision], async ([type, id], _, onCleanup) => {
  if (!id) return
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  onCleanup(() => { controller.abort(); clearTimeout(timer) })
  loading.value = true
  error.value = ''
  try {
    const detail = await getModelEvaluation(type, id, controller.signal)
    if (controller.signal.aborted) return
    task.value = detail
    if (detail.result?.report_object_key || detail.state === 'succeeded') {
      const response = await getModelEvaluationReport(type, id, controller.signal)
      if (!controller.signal.aborted) report.value = response.file_status === 'ready' ? response.payload : null
    }
  } catch (cause) { if (!controller.signal.aborted) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally {
    if (!controller.signal.aborted) {
      loading.value = false
      if (active.value) timer = setTimeout(() => revision.value++, 2200)
    }
  }
}, { immediate: true })
</script>

<style scoped>
.task-report { min-width:0; }
.task-report header, .report-heading, .report-actions, .report-context { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.task-report header { justify-content:space-between; }
.task-report > a { width:fit-content; color:var(--am-brand-primary); }
.task-report h1 { margin:0; overflow-wrap:anywhere; }
.task-report h2 { margin:0 0 14px; font-size:16px; }
.task-report :deep(.sample-report h2) { margin:0; }
.report-context { color:var(--am-text-muted); }
.report-context > span { max-width:100%; overflow-wrap:anywhere; }
.report-context > * + * { border-inline-start:1px solid var(--am-border); padding-inline-start:12px; }
.classification-report-context {
  display:grid;
  grid-template-columns:minmax(0,1.25fr) minmax(0,1.4fr) minmax(0,.75fr) minmax(0,.9fr);
  align-items:start;
  gap:14px 24px;
  margin:0;
  padding:14px 20px;
}
.classification-report-context > div { min-width:0; }
.classification-report-context dt { color:var(--am-text-muted); font-size:var(--am-type-caption); }
.classification-report-context dd { margin:4px 0 0; color:var(--am-text); font-weight:500; overflow-wrap:anywhere; }
.report-columns { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
.report-columns--classification { grid-template-columns:minmax(0,1fr) minmax(0,1.2fr); }
.report-columns > article { min-width:0; align-content:start; gap:8px; padding:14px 16px; }
.report-columns > article > h2 { margin-block-end:4px; }
.report-metrics { display:flex; flex-wrap:wrap; gap:12px; margin:0; }
.report-metrics div { flex:1 1 min(100%,64px); min-width:0; text-align:center; }
.report-metrics--distribution div { flex-basis:min(100%,75px); }
.report-metrics dt { color:var(--am-text-muted); overflow-wrap:anywhere; }
.report-metrics dd { margin:3px 0 0; font-size:22px; font-weight:600; font-variant-numeric:tabular-nums; }
.report-metrics > div + div { border-inline-start:1px solid var(--am-border); }
.task-report .resource-table tfoot { background:var(--am-surface-muted); font-weight:600; }
.report-class-results:is(details) { padding:12px 16px; }
.pose-spec { display:grid; align-content:start; gap:12px; }
.pose-spec h2, .pose-definition h3, .pose-spec p { margin:0; }
.pose-definition { display:grid; gap:8px; min-width:0; }
.pose-definition h3 small { color:var(--am-text-muted); font-weight:400; }
.pose-definition__list { display:grid; gap:4px; margin:0; padding-inline-start:32px; overflow-wrap:anywhere; }
.pose-definition__list li { padding:4px 8px; border-block-end:1px solid var(--am-border); }
.pose-policy { display:grid; gap:8px; margin-block:8px; }
.pose-policy > div { display:grid; grid-template-columns:minmax(100px,1fr) 2fr; gap:8px; }
.pose-policy dt { color:var(--am-text-muted); }
.pose-policy dd { margin:0; overflow-wrap:anywhere; }
.task-report details > summary { cursor:pointer; }
.task-report details[open] > .resource-table { margin-block-start:12px; }
.obb-coordinates { display:flex; gap:16px; align-items:center; flex-wrap:wrap; }
.obb-coordinates p { flex:1 0 min(100%, 170px); margin:0; }
.obb-axes { display:grid; grid-template-columns:auto auto; gap:0 8px; padding:8px 12px; border-radius:6px; color:var(--am-text-muted); background:var(--am-surface-soft); white-space:nowrap; }
.obb-issues { display:flex; flex-wrap:wrap; gap:8px; }
@media (max-width:790px) {
  .report-columns { grid-template-columns:minmax(0,1fr); }
  .classification-report-context { grid-template-columns:repeat(2,minmax(0,1fr)); }
}
@media (max-width:480px) {
  .classification-report-context { grid-template-columns:minmax(0,1fr); }
}
</style>
