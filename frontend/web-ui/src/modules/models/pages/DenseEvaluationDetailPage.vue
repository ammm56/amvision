<template>
  <section class="page-stack model-workspace dense-report">
    <RouterLink :to="{ path: '/models', query: { tab: 'evaluation', evaluation: kind } }">{{ zh ? '返回评估列表' : 'Back to evaluations' }}</RouterLink>
    <header>
      <div><h1>{{ task?.display_name || (zh ? '评估报告' : 'Evaluation report') }}</h1><TaskStateBadge v-if="task" :state="task.state" /></div>
      <div>
        <Button v-if="semantic && report" @click="openMetricDefinition">{{ zh ? '指标口径' : 'Metric definition' }}</Button>
        <Button v-if="semantic && report" @click="openDifferences">{{ zh ? '查看差异样本' : 'View differences' }}</Button>
        <Button v-if="report" variant="primary" @click="downloadEvaluationJson(`${taskId}-report.json`, report)"><Download :size="16" />{{ zh ? '下载报告' : 'Download report' }}</Button>
        <Button v-if="session.hasScopes(['tasks:write']) && ['queued','running'].includes(task?.state || '')" @click="cancelOpen = true">{{ zh ? '取消任务' : 'Cancel task' }}</Button>
        <Button :loading="loading" @click="revision++">{{ zh ? '刷新' : 'Refresh' }}</Button>
      </div>
    </header>
    <InlineError :message="error || task?.error_message || ''" />
    <div v-if="active" class="resource-section">
      <TaskProgress :percent="task?.progress?.percent" :indeterminate="true"
        :label="task?.state === 'queued' ? (zh ? '等待评估 Worker' : 'Waiting for evaluation worker') : task?.state === 'cancelling' ? (zh ? '正在取消评估' : 'Cancelling evaluation') : (zh ? '正在计算评估指标' : 'Computing evaluation metrics')" />
    </div>
    <ConfirmDialog v-if="cancelOpen" :title="zh ? '取消评估' : 'Cancel evaluation'" :message="zh ? '确认取消这次评估？' : 'Cancel this evaluation?'"
      :confirm-label="zh ? '确认取消' : 'Confirm cancellation'" :cancel-label="zh ? '返回' : 'Back'" :busy="cancelling" @cancel="cancelOpen = false" @confirm="cancel" />
    <template v-if="report">
      <div class="resource-section dense-context">
        <span>{{ report.source_model }}</span><span>{{ report.source_dataset }}</span><span>{{ report.split_name }} · {{ report.sample_count }} {{ zh ? '张' : 'images' }}</span>
        <span>{{ evaluationTypes[kind][zh ? 0 : 1] }}</span>
        <time v-if="task?.finished_at" :datetime="task.finished_at">{{ formatSystemDateTime(task.finished_at, 'minutes') }}</time>
      </div>
      <article v-if="semantic" class="resource-section semantic-summary">
        <div class="semantic-metric"><h2>{{ zh ? 'mIoU（不含背景）' : 'mIoU (excluding background)' }}</h2><strong>{{ metric(report.miou) }}</strong></div>
        <div class="semantic-classes">
          <h2>{{ zh ? '类别 IoU' : 'Class IoU' }}</h2>
          <div class="resource-table"><table>
            <thead><tr><th>{{ zh ? '类别' : 'Class' }}</th><th>IoU</th><th>{{ zh ? '计入均值' : 'Included in mean' }}</th></tr></thead>
            <tbody><tr v-for="item in report.classes" :key="item.name"><th scope="row"><span class="class-color" :style="{ backgroundColor: `rgb(${item.color.join(',')})` }" />{{ item.name }}</th><td>{{ metric(item.iou) }}</td><td>{{ item.included ? (zh ? '是' : 'Yes') : (zh ? '否' : 'No') }}</td></tr></tbody>
          </table></div>
        </div>
        <dl class="semantic-metric">
          <dt>ignore_index <small>{{ zh ? '只读' : 'Read-only' }}</small></dt><dd>{{ report.ignore_index ?? '—' }}</dd>
          <dt>{{ zh ? '有效评估像素' : 'Evaluated pixels' }}</dt><dd>{{ report.valid_pixels?.toLocaleString() ?? '—' }}</dd>
        </dl>
      </article>
      <div v-else class="dense-grid">
        <article class="resource-section"><h2>{{ zh ? '图像级 AUROC' : 'Image AUROC' }}</h2><strong>{{ metric(report.image_auroc) }}</strong><p>{{ zh ? '评估图像' : 'Evaluated images' }} {{ report.sample_count }}</p><p>{{ outcome('normal') }} {{ report.normal_count ?? '—' }} · {{ outcome('anomaly') }} {{ report.anomaly_count ?? '—' }}</p></article>
        <article class="resource-section"><h2>{{ zh ? '像素级 AUROC' : 'Pixel AUROC' }}</h2><strong>{{ metric(report.pixel_auroc) }}</strong><p>{{ zh ? '含有效标注和热图' : 'With annotation and heatmap' }} {{ report.pixel_sample_count ?? '—' }}</p><p v-if="pixelCounts">{{ outcome('normal') }} {{ pixelCounts.normal }} · {{ outcome('anomaly') }} {{ pixelCounts.anomaly }}</p></article>
        <article class="resource-section"><h2>{{ zh ? '判定阈值' : 'Decision threshold' }}</h2><strong>{{ metric(report.threshold) }}</strong></article>
      </div>
      <TabList v-if="!semantic" v-model="activeTab" class="dense-tabs" :tabs="anomalyTabs" :label="zh ? '报告内容' : 'Report sections'" />
      <div v-if="showSamples" :class="['dense-sample-grid', { 'dense-sample-grid--anomaly': !semantic }]">
      <article ref="samplePanel" class="resource-section samples" tabindex="-1">
        <header>
          <h2>{{ semantic ? (zh ? '样本分析' : 'Sample analysis') : (zh ? '检测结果示例' : 'Detection preview') }}</h2>
          <div>
            <Select v-if="semantic" :model-value="filter" :options="filters" :aria-label="zh ? '样本筛选' : 'Filter samples'" @update:model-value="setFilter" />
            <Button size="sm" :disabled="!sample || preview.offset === 0 || sampleLoading" @click="moveSample(-1)">{{ zh ? '上一张' : 'Previous' }}</Button>
            <span class="dense-preview-position" aria-live="polite">{{ previewLabel }}{{ sample ? preview.offset + 1 : 0 }} / {{ previewTotal }}</span>
            <Button size="sm" :disabled="!sample || preview.offset + 1 >= previewTotal || sampleLoading" @click="moveSample(1)">{{ zh ? '下一张' : 'Next' }}</Button>
          </div>
        </header>
        <InlineError :message="sampleError" />
        <Button v-if="sampleError" size="sm" @click="retrySample">{{ zh ? '重试样本' : 'Retry sample' }}</Button>
        <p v-if="!sample && (sampleLoading || listLoading)" role="status">{{ zh ? '正在读取样本…' : 'Loading samples…' }}</p>
        <p v-else-if="!sample && !sampleError" role="status">{{ zh ? '没有符合条件的样本。' : 'No samples match the filter.' }}</p>
        <template v-if="sample">
          <div class="dense-context"><strong>{{ sample.name }}</strong>
            <span v-if="semantic">{{ zh ? '差异像素' : 'Different pixels' }} {{ sample.different_pixels?.toLocaleString() }}</span>
            <template v-else><span>{{ zh ? '标注' : 'Actual' }} · {{ outcome(sample.label) }}</span><span>{{ zh ? '预测' : 'Predicted' }} · {{ outcome(sample.predicted_label) }}</span><span>{{ zh ? '分数' : 'Score' }} · {{ metric(sample.score) }}</span></template>
          </div>
          <div :class="['dense-images', { 'dense-images--two': !semantic }]">
            <figure v-for="layer in layers" :key="layer.id">
              <figcaption>{{ layer.label }}</figcaption>
              <img v-if="images[layer.id]" :src="images[layer.id]!" :alt="layer.label" @error="images[layer.id] = null" />
              <p v-else-if="!layer.available">{{ zh ? '预测包未提供该图层' : 'Layer unavailable in the bundle' }}</p>
              <div v-else-if="images[layer.id] === null" class="dense-layer-status" role="alert">
                {{ zh ? '图层读取失败' : 'Layer could not load' }}
                <Button size="sm" @click="layerRevisions[layer.id]++">{{ zh ? '重试图层' : 'Retry layer' }}</Button>
              </div>
              <p v-else role="status">{{ zh ? '正在读取…' : 'Loading…' }}</p>
              <div v-if="!semantic && layer.id === 'prediction' && images[layer.id]" class="heatmap-scale" :aria-label="zh ? '异常分数 0 至 1' : 'Anomaly score 0 to 1'"><span>1.0</span><span>0.5</span><span>0.0</span></div>
            </figure>
            <div v-if="semantic" class="class-legend">
              <h3>{{ zh ? '类别图例' : 'Class legend' }}</h3>
              <div v-for="item in report.classes" :key="item.name"><span class="class-color" :style="{ backgroundColor: `rgb(${item.color.join(',')})` }" />{{ item.name }}</div>
              <div v-if="report.ignore_index != null"><span class="class-color class-color--ignored" />{{ zh ? '标注忽略值' : 'Ignored in truth' }} {{ report.ignore_index }}</div>
            </div>
          </div>
        </template>
      </article>
      <article v-if="!semantic" class="resource-section samples">
        <header>
          <h2>{{ zh ? '检测结果列表' : 'Detection results' }}</h2>
          <Select v-if="activeTab === 'samples'" :model-value="filter" :options="filters.filter(item => item.value !== 'errors')" :aria-label="zh ? '样本筛选' : 'Filter samples'" @update:model-value="setFilter" />
          <div class="dense-list-pagination">
            <Button size="sm" :disabled="listPage === 0 || listLoading" :aria-label="zh ? '上一页结果' : 'Previous result page'" @click="listPage--"><ChevronLeft :size="16" /></Button>
            <span class="dense-result-page" aria-live="polite">{{ listPageCount ? listPage + 1 : 0 }} / {{ listPageCount }} {{ zh ? '页' : 'pages' }}</span>
            <Button size="sm" :disabled="listPage + 1 >= listPageCount || listLoading" :aria-label="zh ? '下一页结果' : 'Next result page'" @click="listPage++"><ChevronRight :size="16" /></Button>
          </div>
        </header>
        <InlineError :message="listError" />
        <Button v-if="listError" size="sm" @click="listRevision++">{{ zh ? '重试列表' : 'Retry list' }}</Button>
        <p v-if="listLoading && !pageSamples.length" role="status">{{ zh ? '正在读取结果…' : 'Loading results…' }}</p>
        <p v-if="!listLoading && !listError && !pageSamples.length" role="status">{{ zh ? '没有符合条件的结果。' : 'No results match the filter.' }}</p>
        <div class="dense-thumbnails">
          <button v-for="(row, index) in pageSamples" :key="row.index" type="button" :aria-pressed="sample?.index === row.index" :title="row.name" @click="chooseSample(row, index)">
            <img v-if="thumbnails[row.index]" :src="thumbnails[row.index] ?? undefined" alt="" @error="thumbnails[row.index] = null" />
            <span v-else class="thumbnail-placeholder">{{ thumbnails[row.index] === null ? (zh ? '无预览' : 'No preview') : '…' }}</span>
            <span :class="`sample-label sample-label--${row.label}`">{{ outcome(row.label) }}</span>
            <span class="thumbnail-name">{{ row.name }}</span>
          </button>
        </div>
      </article>
      </div>
      <TabList v-if="semantic" v-model="activeTab" class="dense-tabs" :tabs="semanticTabs" :label="zh ? '报告内容' : 'Report sections'" />
      <article v-if="activeTab === 'distribution'" class="resource-section">
        <h2>{{ zh ? '图像分数分布' : 'Image score distribution' }}</h2>
        <div class="resource-table"><table>
          <thead><tr><th>{{ zh ? '分数区间' : 'Score bucket' }}</th><th>{{ outcome('normal') }}</th><th>{{ outcome('anomaly') }}</th></tr></thead>
          <tbody><tr v-for="(count, index) in report.score_distribution?.[0]" :key="index">
            <td>{{ (index / 10).toFixed(1) }}–{{ ((index + 1) / 10).toFixed(1) }}</td>
            <td><div class="score-cell"><strong>{{ count }}</strong><span aria-hidden="true" :style="{ width: scoreBar(count) }" /></div></td>
            <td><div class="score-cell score-cell--anomaly"><strong>{{ report.score_distribution?.[1]?.[index] ?? 0 }}</strong><span aria-hidden="true" :style="{ width: scoreBar(report.score_distribution?.[1]?.[index] ?? 0) }" /></div></td>
          </tr></tbody>
        </table></div>
      </article>
      <article v-else-if="activeTab === 'pixel'" class="resource-section">
        <h2>{{ zh ? '像素级效果' : 'Pixel-level performance' }}</h2>
        <dl class="pixel-metrics">
          <dt>AUROC</dt><dd>{{ metric(report.pixel_auroc) }}</dd>
          <dt>{{ zh ? '有效像素标注图像' : 'Pixel-labeled images' }}</dt><dd>{{ report.pixel_sample_count ?? 0 }} / {{ report.sample_count }}</dd>
        </dl>
        <p>{{ zh ? '像素级 AUROC 只统计同时包含像素标注和异常分数图的样本。' : 'Pixel AUROC uses samples with both a pixel annotation and an anomaly score map.' }}</p>
      </article>
      <article v-else-if="activeTab === 'logs'" class="resource-section">
        <h2>{{ zh ? '运行日志' : 'Run log' }}</h2>
        <InlineError :message="logError" />
        <Button v-if="logError" size="sm" @click="logRevision++">{{ zh ? '重试日志' : 'Retry log' }}</Button>
        <p v-else-if="logLoading" role="status">{{ zh ? '正在读取日志…' : 'Loading log…' }}</p>
        <p v-else-if="!events.length" role="status">{{ zh ? '此任务没有记录日志。' : 'No log events were recorded.' }}</p>
        <ol v-else class="dense-log">
          <li v-for="event in events" :key="event.event_id"><time :datetime="event.created_at ?? undefined">{{ formatSystemDateTime(event.created_at) }}</time><span>{{ event.message }}</span></li>
        </ol>
      </article>
      <article v-else-if="activeTab === 'source'" ref="metricDefinition" class="resource-section" tabindex="-1">
        <h2>{{ zh ? '评估来源' : 'Evaluation provenance' }}</h2>
        <p v-if="semantic">{{ zh ? 'mIoU 对计入均值的前景类别等权平均。真值为 ignore_index 的像素不参与统计。' : 'mIoU averages foreground classes with equal weight. Ground-truth pixels labeled ignore_index are excluded.' }}</p>
        <p>{{ zh ? '输入为独立预测包。包内记录模型与数据来源。' : 'The independent prediction bundle records the model and dataset provenance.' }}</p>
        <p class="asset-hash">SHA-256 · {{ report.input_sha256 }}</p>
        <dl v-if="semantic" class="pixel-metrics">
          <dt>{{ zh ? '评估数据' : 'Evaluation data' }}</dt><dd>{{ report.source_dataset }} · {{ report.split_name }}</dd>
          <dt>{{ zh ? '评估指标' : 'Metric' }}</dt><dd>{{ zh ? 'mIoU（不含背景）' : 'mIoU (excluding background)' }}</dd>
          <template v-if="report.background_index != null"><dt>{{ zh ? '背景类别' : 'Background class' }}</dt><dd>{{ report.classes?.[report.background_index]?.name ?? report.background_index }}</dd></template>
          <dt>ignore_index</dt><dd>{{ report.ignore_index ?? '—' }}</dd>
        </dl>
      </article>
    </template>
    <p v-else-if="task?.state === 'succeeded' && !loading && !error" class="resource-section" role="status">{{ zh ? '评估报告暂不可读取。可刷新后重试。' : 'The evaluation report is unavailable. Refresh to check again.' }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ChevronLeft, ChevronRight, Download } from '@lucide/vue'
import { useSessionStore } from '@/app/stores/session.store'
import { cancelTask, getTaskEvents } from '@/modules/tasks/services/task.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import type { TaskEvent } from '@/shared/contracts'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import TaskProgress from '@/modules/tasks/components/TaskProgress.vue'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Select from '@/shared/ui/components/Select.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { evaluationTypes } from '../model-evaluation-types'
import {
  downloadEvaluationJson, fetchDenseLayer, getDenseReport, getModelEvaluation, listDenseSamples,
  type DenseEvaluationKind, type DenseEvaluationReport, type DenseEvaluationSample,
  type DenseSampleFilter, type DenseSampleLayer, type ModelEvaluationRecord,
} from '../services/model-evaluation.service'

const route = useRoute()
const session = useSessionStore()
const { locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const kind = computed<DenseEvaluationKind>(() => route.params.taskType === 'anomaly' ? 'anomaly' : 'semantic')
const taskId = computed(() => String(route.params.taskId))
const semantic = computed(() => kind.value === 'semantic')
const task = ref<ModelEvaluationRecord>()
const report = ref<DenseEvaluationReport>()
const error = ref('')
const revision = ref(0)
const loading = ref(false)
const cancelOpen = ref(false)
const cancelling = ref(false)
const active = computed(() => ['queued', 'running', 'cancelling'].includes(task.value?.state || ''))
const activeTab = ref(semantic.value ? 'source' : 'samples')
const semanticTabs = computed(() => [
  { id: 'source', label: zh.value ? '评估配置' : 'Configuration' },
  { id: 'logs', label: zh.value ? '运行日志' : 'Run log' },
])
const anomalyTabs = computed(() => [
  { id: 'samples', label: zh.value ? '样本分析' : 'Samples' },
  { id: 'errors', label: zh.value ? '错误样本' : 'Errors' },
  { id: 'distribution', label: zh.value ? '分数分布' : 'Score distribution' },
  { id: 'pixel', label: zh.value ? '像素级效果' : 'Pixel-level performance' },
  { id: 'source', label: zh.value ? '评估配置' : 'Configuration' },
])
const showSamples = computed(() => semantic.value || activeTab.value === 'samples' || activeTab.value === 'errors')
const hasReport = computed(() => Boolean(report.value))
const samplePanel = ref<HTMLElement>()
const metricDefinition = ref<HTMLElement>()
const events = shallowRef<TaskEvent[]>([])
const logError = ref('')
const logLoading = ref(false)
const logRevision = ref(0)

interface SamplePosition { filter: DenseSampleFilter; offset: number }
const filter = ref<DenseSampleFilter>('all')
const pageSize = 8
const listPage = ref(0)
const listTotal = ref(0)
const listPageCount = computed(() => Math.ceil(listTotal.value / pageSize))
const pageSamples = shallowRef<DenseEvaluationSample[]>([])
const thumbnails = ref<Partial<Record<number, string | null>>>({})
const listLoading = ref(false)
const listError = ref('')
const listRevision = ref(0)
const preview = ref<SamplePosition>({ filter: 'all', offset: 0 })
const requestedSample = shallowRef<SamplePosition>()
const previewTotal = ref(0)
const sampleLoading = ref(false)
const sampleError = ref('')
const sample = shallowRef<DenseEvaluationSample>()
const images = ref<Partial<Record<DenseSampleLayer, string | null>>>({})
const layerRevisions = ref({ original: 0, truth: 0, prediction: 0 })
const previewLabel = computed(() => {
  const scope = preview.value.filter
  if (semantic.value || (scope !== 'normal' && scope !== 'anomaly')) return ''
  return zh.value ? `${outcome(scope)}样本 · ` : `${outcome(scope)} samples · `
})
const filters = computed(() => [
  { value: 'all', label: zh.value ? '全部样本' : 'All samples' },
  ...(!semantic.value ? [{ value: 'normal', label: outcome('normal') }, { value: 'anomaly', label: outcome('anomaly') }] : []),
  { value: 'errors', label: zh.value ? (semantic.value ? '差异样本' : '判定错误') : (semantic.value ? 'Differences' : 'Incorrect decisions') },
])
const layers = computed<{ id: DenseSampleLayer; label: string; available: boolean }[]>(() => [
  { id: 'original', label: zh.value ? '原图' : 'Original', available: true },
  ...(semantic.value ? [{ id: 'truth' as const, label: zh.value ? '标注掩码' : 'Ground truth mask', available: !!sample.value?.has_truth }] : []),
  { id: 'prediction', label: semantic.value ? (zh.value ? '预测掩码' : 'Predicted mask') : (zh.value ? '异常热图' : 'Anomaly heatmap'), available: !!sample.value?.has_prediction },
])
const pixelCounts = computed(() => {
  const current = report.value
  if (!current) return null
  if (current.pixel_normal_count != null && current.pixel_anomaly_count != null) {
    return { normal: current.pixel_normal_count, anomaly: current.pixel_anomaly_count }
  }
  if (current.pixel_sample_count === current.sample_count && current.normal_count != null && current.anomaly_count != null) {
    return { normal: current.normal_count, anomaly: current.anomaly_count }
  }
  return null
})

function metric(value?: number | null): string { return value == null ? '—' : value.toFixed(3) }
const maxScoreBucket = computed(() => Math.max(1, ...(report.value?.score_distribution?.flat() ?? [])))
function scoreBar(count: number): string { return `${count / maxScoreBucket.value * 100}%` }
function outcome(value?: string): string {
  if (value === 'anomaly') return zh.value ? '异常' : 'Anomaly'
  return value === 'normal' ? (zh.value ? '正常' : 'Normal') : '—'
}
function setFilter(value: unknown): void {
  if (value === 'all' || value === 'normal' || value === 'anomaly' || value === 'errors') filter.value = value
}
function chooseSample(row: DenseEvaluationSample, index: number): void {
  requestedSample.value = undefined
  sampleError.value = ''
  sample.value = row
  const classTotal = row.label === 'normal' ? report.value?.normal_count : report.value?.anomaly_count
  if (filter.value === 'all' && row.label && row.label_index != null && classTotal != null) {
    preview.value = { filter: row.label, offset: row.label_index }
    previewTotal.value = classTotal
  } else {
    preview.value = { filter: filter.value, offset: listPage.value * pageSize + index }
    previewTotal.value = listTotal.value
  }
}
function moveSample(direction: 1 | -1): void {
  const offset = preview.value.offset + direction
  if (!sampleLoading.value && offset >= 0 && offset < previewTotal.value) {
    requestedSample.value = { ...preview.value, offset }
  }
}
function retrySample(): void {
  if (requestedSample.value) requestedSample.value = { ...requestedSample.value }
}
async function openMetricDefinition(): Promise<void> {
  activeTab.value = 'source'
  await nextTick()
  metricDefinition.value?.focus({ preventScroll: true })
  metricDefinition.value?.scrollIntoView({ block: 'nearest' })
}
function openDifferences(): void {
  setFilter('errors')
  samplePanel.value?.focus({ preventScroll: true })
  samplePanel.value?.scrollIntoView({ block: 'nearest' })
}
async function cancel(): Promise<void> {
  cancelling.value = true
  try { await cancelTask(taskId.value); revision.value++ }
  catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { cancelling.value = false; cancelOpen.value = false }
}

watch([taskId, kind], () => {
  task.value = undefined
  report.value = undefined
  filter.value = 'all'
  activeTab.value = semantic.value ? 'source' : 'samples'
  cancelOpen.value = false
})
watch(activeTab, (section) => {
  if (section === 'errors') setFilter('errors')
  else if (!semantic.value && section === 'samples' && filter.value === 'errors') setFilter('all')
})
watch([taskId, kind, revision], async ([id, type], _, onCleanup) => {
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  onCleanup(() => { controller.abort(); clearTimeout(timer) })
  loading.value = true
  error.value = ''
  try {
    const current = await getModelEvaluation(type, id, controller.signal)
    if (controller.signal.aborted) return
    task.value = current
    if (current.result?.report_object_key || current.state === 'succeeded') {
      const response = await getDenseReport(type, id, controller.signal)
      if (!controller.signal.aborted) report.value = response.file_status === 'ready' ? response.payload : undefined
    }
  } catch (cause) { if (!controller.signal.aborted) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally {
    if (!controller.signal.aborted) {
      loading.value = false
      if (active.value) timer = setTimeout(() => revision.value++, 1800)
    }
  }
}, { immediate: true })

watch([hasReport, taskId, filter], ([ready, , applied]) => {
  sample.value = undefined
  sampleError.value = ''
  preview.value = { filter: applied, offset: 0 }
  previewTotal.value = 0
  listPage.value = 0
  listTotal.value = 0
  requestedSample.value = ready && semantic.value ? { ...preview.value } : undefined
}, { flush: 'sync' })

watch(requestedSample, async (position, _, onCleanup) => {
  sampleLoading.value = Boolean(position)
  if (!position) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  sampleError.value = ''
  try {
    const result = await listDenseSamples(kind.value, taskId.value, position.offset, position.filter, controller.signal)
    if (controller.signal.aborted) return
    preview.value = position
    previewTotal.value = result.total
    sample.value = result.items[0]
  } catch (cause) { if (!controller.signal.aborted) sampleError.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (!controller.signal.aborted) sampleLoading.value = false }
})

watch([hasReport, taskId, listPage, filter, listRevision], async ([ready, id, page, applied], _, onCleanup) => {
  pageSamples.value = []
  thumbnails.value = {}
  listError.value = ''
  listLoading.value = ready && !semantic.value
  if (!listLoading.value) return
  const controller = new AbortController()
  const urls: string[] = []
  onCleanup(() => { controller.abort(); urls.forEach(url => URL.revokeObjectURL(url)) })
  try {
    const result = await listDenseSamples('anomaly', id, page * pageSize, applied, controller.signal, pageSize)
    if (controller.signal.aborted) return
    listTotal.value = result.total
    pageSamples.value = result.items
    if (!sample.value && result.items.length) {
      const index = applied === 'all' ? result.items.findIndex(row => row.label === 'anomaly') : 0
      chooseSample(result.items[Math.max(0, index)], Math.max(0, index))
    }
    listLoading.value = false
    const results = await Promise.allSettled(result.items.map(async ({ index }) => {
      try {
        const blob = await fetchDenseLayer('anomaly', id, index, 'original', controller.signal)
        if (controller.signal.aborted) return
        const url = URL.createObjectURL(blob)
        urls.push(url)
        thumbnails.value[index] = url
      } catch (cause) {
        if (!controller.signal.aborted) thumbnails.value[index] = null
        throw cause
      }
    }))
    if (!controller.signal.aborted && results.some(result => result.status === 'rejected')) {
      listError.value = zh.value ? '部分缩略图读取失败。' : 'Some thumbnails could not load.'
    }
  } catch (cause) { if (!controller.signal.aborted) listError.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (!controller.signal.aborted) listLoading.value = false }
}, { immediate: true })

for (const layer of ['original', 'truth', 'prediction'] as const) {
  watch([sample, () => layerRevisions.value[layer]], async ([row], _, onCleanup) => {
    images.value[layer] = undefined
    if (!row || !layers.value.some(item => item.id === layer && item.available)) return
    const controller = new AbortController()
    let url = ''
    onCleanup(() => {
      controller.abort()
      if (url) URL.revokeObjectURL(url)
    })
    try {
      const blob = await fetchDenseLayer(kind.value, taskId.value, row.index, layer, controller.signal)
      if (!controller.signal.aborted) {
        url = URL.createObjectURL(blob)
        images.value[layer] = url
      }
    } catch {
      if (!controller.signal.aborted) images.value[layer] = null
    }
  })
}

watch([taskId, activeTab, logRevision], async ([id, tab], _, onCleanup) => {
  if (tab !== 'logs') return
  let stale = false
  onCleanup(() => { stale = true })
  events.value = []
  logError.value = ''
  logLoading.value = true
  try {
    const result = await getTaskEvents(id)
    if (!stale) events.value = result
  } catch (cause) {
    if (!stale) logError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (!stale) logLoading.value = false
  }
})
</script>

<style scoped>
.dense-report { gap:14px; min-width:0; }
.dense-report header, .dense-report header > div, .dense-context { display:flex; align-items:center; flex-wrap:wrap; gap:12px; }
.dense-report header { justify-content:space-between; }
.dense-report :is(h1,h2,figure) { margin:0; }
.dense-report h2 { font-size:16px; }
.dense-report > a { width:fit-content; color:var(--am-brand-primary); }
.dense-context, .asset-hash { overflow-wrap:anywhere; }
.dense-context > :not(:first-child) { border-inline-start:1px solid var(--am-border); padding-inline-start:12px; }
.dense-context > * { min-width:0; }
.dense-report > .dense-context { padding:12px 16px; }
.dense-grid, .dense-images { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }
.dense-grid .resource-section { display:block; padding:13px 16px; }
.dense-grid article > strong { display:block; margin-top:5px; font-size:24px; }
.dense-grid article p { margin:5px 0 0; color:var(--am-text-muted); }
.dense-tabs { border-bottom:1px solid var(--am-border); }
.dense-tabs :deep(.local-tabs__tab) { border-radius:0; border-bottom:2px solid transparent; }
.dense-tabs :deep(.local-tabs__tab.is-active) { background:transparent; border-bottom-color:var(--am-brand-primary); }
.semantic-summary { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,2fr) minmax(0,.85fr); gap:12px; align-items:center; padding:14px 16px; }
.semantic-classes { min-width:0; padding-inline:12px; border-inline:1px solid var(--am-border); }
.semantic-classes table { width:100%; table-layout:fixed; }
.semantic-classes :is(th,td) { overflow-wrap:anywhere; }
.semantic-classes :is(th,td):first-child { width:43%; }
.semantic-classes h2 { margin-bottom:8px; }
.semantic-metric { text-align:center; margin:0; }
.semantic-metric small { color:var(--am-text-muted); font-weight:400; }
.semantic-metric strong,.semantic-metric dd { display:block; margin:4px 0 12px; font-size:24px; font-weight:600; }
.dense-images:not(.dense-images--two) { grid-template-columns:repeat(3,minmax(0,1fr)) minmax(76px,130px); }
.dense-images--two { grid-template-columns:repeat(2,minmax(0,1fr)); }
.dense-images figure { position:relative; min-width:0; background:var(--am-surface-soft); padding:8px; border-radius:6px; }
.dense-images figcaption { margin-bottom:8px; font-size:13px; }
.dense-images img { display:block; width:100%; max-height:350px; object-fit:contain; border-radius:4px; }
.dense-images:not(.dense-images--two) img { max-height:clamp(155px,26dvh,260px); }
.samples { display:grid; gap:12px; min-width:0; align-content:start; padding:14px 16px; }
.dense-sample-grid { display:grid; gap:14px; }
.dense-sample-grid--anomaly { grid-template-columns:minmax(0,3fr) minmax(0,2fr); }
.dense-thumbnails { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }
.dense-thumbnails button { display:grid; min-width:0; gap:4px; text-align:start; padding:4px; border:1px solid var(--am-border); border-radius:6px; background:var(--am-surface-soft); color:inherit; cursor:pointer; }
.dense-thumbnails button[aria-pressed="true"] { border-color:var(--am-brand-primary); }
.dense-thumbnails img { width:100%; aspect-ratio:1; object-fit:cover; border-radius:3px; }
.thumbnail-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; }
.thumbnail-placeholder { display:grid; place-items:center; aspect-ratio:1; color:var(--am-text-muted); font-size:var(--am-type-caption); }
.dense-list-pagination,.dense-layer-status { display:flex; align-items:center; flex-wrap:wrap; gap:6px 8px; }
.dense-layer-status { margin-top:8px; color:var(--am-text-muted); }
.dense-log { display:grid; gap:8px; margin:0; padding:0; list-style:none; }
.dense-log li { display:grid; grid-template-columns:minmax(0,175px) minmax(0,1fr); gap:4px 12px; overflow-wrap:anywhere; }
.dense-log time { color:var(--am-text-muted); }
.sample-label { font-size:12px; }
.sample-label--anomaly { color:var(--am-danger-text); }
.score-cell { display:grid; grid-template-columns:35px minmax(0,1fr); gap:8px; align-items:center; }
.score-cell span { display:block; height:8px; background:var(--am-brand-primary); border-radius:var(--am-radius-pill); }
.score-cell--anomaly span { background:var(--am-danger-icon); }
.pixel-metrics { display:grid; grid-template-columns:max-content 1fr; gap:8px 20px; }
.pixel-metrics dd { margin:0; font-weight:600; }
.class-legend { overflow-wrap:anywhere; font-size:13px; align-self:start; }
.class-legend h3 { font-size:13px; margin:0 0 8px; }
.class-legend > div { margin-block:4px; }
.heatmap-scale { position:absolute; inset-block:21% 12%; inset-inline-end:12px; display:flex; flex-direction:column; justify-content:space-between; padding-inline-start:13px; color:white; font-size:11px; text-shadow:0 1px 3px black; }
.heatmap-scale::before { content:''; position:absolute; inset:0 auto 0 0; width:8px; border:1px solid white; background:linear-gradient(#800000,red,yellow,cyan,blue,#000080); }
.class-color { display:inline-block; width:12px; height:12px; margin-inline-end:8px; border-radius:2px; }
.class-color--ignored { background:#7a7a7a; }
@media (max-width:1100px) {
  .dense-images:not(.dense-images--two) { grid-template-columns:repeat(3,minmax(0,1fr)); }
  .class-legend { grid-column:1 / -1; display:flex; flex-wrap:wrap; align-items:baseline; gap:0 14px; }
}
@media (max-width:720px) {
  .dense-grid,.dense-images,.dense-images:not(.dense-images--two),.semantic-summary,.dense-sample-grid--anomaly { grid-template-columns:minmax(0,1fr); }
  .semantic-classes { padding-inline:0; border-inline:0; }
}
</style>
