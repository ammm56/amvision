<template>
  <section class="resource-section sample-report">
    <header>
      <h2>
        {{ classification ? (zh ? '分类错误样本' : 'Incorrect classifications') : (zh ? '样本可视化' : 'Sample preview') }}
        <small v-if="classification && available">{{ zh ? `共 ${total} 个` : `${total} total` }}</small>
      </h2>
      <Select v-if="geometry" :model-value="issue" :aria-label="zh ? '错误样本筛选' : 'Filter sample errors'"
        :options="issueOptions" @update:model-value="changeIssue" />
      <div v-if="total > 0" class="sample-navigation">
        <Button size="sm" :disabled="offset === 0 || loading" :aria-label="zh ? '上一页样本' : 'Previous samples'" @click="offset -= pageSize"><ChevronLeft :size="16" /></Button>
        <span>{{ offset + 1 }}<template v-if="pageSize > 1 && offset + 1 < total">–{{ Math.min(offset + pageSize, total) }}</template> / {{ total }}</span>
        <Button size="sm" :disabled="offset + pageSize >= total || loading" :aria-label="zh ? '下一页样本' : 'Next samples'" @click="offset += pageSize"><ChevronRight :size="16" /></Button>
      </div>
    </header>
    <InlineError :message="error" />
    <Button v-if="error" size="sm" @click="revision++">{{ zh ? '重试' : 'Retry' }}</Button>
    <p v-else-if="loading" role="status">{{ zh ? '正在读取评估样本…' : 'Loading evaluation samples…' }}</p>
    <p v-else-if="!sample" role="status">{{ noSampleText }}</p>
    <div v-else-if="classification" class="classification-grid">
      <article v-for="entry in samples" :key="entry.index" class="classification-card">
        <img v-if="classificationImages[entry.index]" :src="classificationImages[entry.index] ?? undefined" :alt="entry.name" @error="categoryImageFailed(entry.index)" />
        <div v-else-if="classificationImages[entry.index] === null" class="sample-placeholder" role="alert">
          {{ zh ? '图片不可用' : 'Image unavailable' }} <Button size="sm" @click="imageRevision++">{{ zh ? '重试' : 'Retry' }}</Button>
        </div>
        <div v-else class="sample-placeholder" role="status">{{ zh ? '正在读取图片…' : 'Loading image…' }}</div>
        <dl>
          <dt>{{ zh ? '文件名' : 'File name' }}</dt><dd>{{ entry.name }}</dd>
          <dt>{{ zh ? '标注' : 'Ground truth' }}</dt><dd>{{ entry.ground_truth_class_name ?? '—' }}</dd>
          <dt>{{ zh ? '预测' : 'Prediction' }}</dt><dd>{{ entry.predicted_top_k?.[0]?.class_name ?? '—' }}</dd>
          <dt>{{ zh ? '置信度' : 'Confidence' }}</dt><dd>{{ entry.predicted_top_k?.[0]?.probability?.toFixed(3) ?? '—' }}</dd>
        </dl>
      </article>
    </div>
    <template v-else>
      <div class="sample-caption">
        <strong>{{ sample.name }}</strong>
        <label v-if="geometry"><input v-model="showGroundTruth" type="checkbox" />{{ zh ? '标注' : 'Ground truth' }}</label>
        <label v-if="geometry"><input v-model="showPrediction" type="checkbox" />{{ zh ? '预测' : 'Prediction' }}</label>
        <div v-if="kind === 'segmentation' && sample.mask_available" class="sample-mask-mode" role="group" :aria-label="zh ? '掩膜显示' : 'Mask display'">
          <Button size="sm" :variant="showMasks ? 'secondary' : 'primary'" :aria-pressed="!showMasks" @click="showMasks = false">{{ zh ? '原图' : 'Original' }}</Button>
          <Button size="sm" :variant="showMasks ? 'primary' : 'secondary'" :aria-pressed="showMasks" @click="showMasks = true">{{ zh ? '叠加结果' : 'Overlays' }}</Button>
        </div>
        <Button v-if="imageUrl && !imageError" size="sm" @click="expandedView = kind === 'segmentation' && showMasks && layers.combined ? 'combined' : 'original'">
          <ZoomIn :size="16" />{{ zh ? '查看样本' : 'View sample' }}
        </Button>
      </div>
      <div v-if="imageError" class="sample-placeholder" role="alert">{{ zh ? '图片不可用' : 'Image unavailable' }} <Button size="sm" @click="imageRevision++">{{ zh ? '重试' : 'Retry' }}</Button></div>
      <div v-else-if="!imageUrl" class="sample-placeholder" role="status">{{ zh ? '正在读取图片…' : 'Loading image…' }}</div>
      <template v-else-if="kind === 'segmentation'">
        <div :class="['mask-grid', { 'mask-grid--single': !showMasks || !sample.mask_available }]">
          <figure><figcaption>{{ zh ? '原图' : 'Original image' }}</figcaption><img :src="imageUrl" :alt="sample.name" @error="imageError = true" /></figure>
          <template v-if="showMasks && sample.mask_available">
            <figure v-for="entry in overlayViews" :key="entry.kind">
              <figcaption>{{ entry.title }}</figcaption>
              <div class="sample-image">
                <img :src="imageUrl" alt="" />
                <img v-if="entry.url" class="mask-overlay" :src="entry.url" :alt="entry.title" @error="layers[entry.kind] = null" />
              </div>
              <div v-if="entry.url === null" class="overlay-status" role="alert">
                {{ zh ? '此图层不可用' : 'Layer unavailable' }}
                <Button size="sm" @click="layerRevisions[entry.kind]++">{{ zh ? '重试图层' : 'Retry layer' }}</Button>
              </div>
              <p v-else-if="entry.url === undefined" class="overlay-status" role="status">{{ zh ? '正在读取图层…' : 'Loading layer…' }}</p>
              <p v-else-if="entry.url === ''" class="overlay-status">{{ zh ? '该样本没有可用的掩膜记录。' : 'This sample has no saved masks.' }}</p>
            </figure>
          </template>
        </div>
        <div v-if="showMasks && sample.mask_available" class="sample-legend">
          <span class="truth">{{ zh ? '标注轮廓' : 'Ground truth outline' }}</span><span class="prediction">{{ zh ? '预测前景' : 'Predicted foreground' }}</span>
          <span class="false-positive">{{ zh ? '多预测的前景' : 'Extra foreground' }}</span><span class="false-negative">{{ zh ? '漏预测的前景' : 'Missed foreground' }}</span>
        </div>
        <p v-else-if="!sample.mask_available">{{ zh ? '该样本没有可用的掩膜记录。' : 'This sample has no saved masks.' }}</p>
      </template>
      <div v-else class="sample-image"><img :src="imageUrl" :alt="sample.name" @load="readSize" @error="imageError = true" />
        <EvaluationGeometryOverlay v-if="size.width" :width="size.width" :height="size.height" :layers="geometryLayers" :definitions="definitions" :show-keypoint-numbers="kind === 'pose'" />
      </div>
      <div v-if="kind === 'pose' || kind === 'obb'" class="sample-legend">
        <span class="truth geometry-truth">{{ zh ? (kind === 'pose' ? '标注关键点' : '标注旋转框') : (kind === 'pose' ? 'Annotated points' : 'Annotated boxes') }} · {{ sample.ground_truth?.length ?? '—' }}</span>
        <span class="prediction geometry-prediction">{{ zh ? (kind === 'pose' ? '预测关键点' : '预测旋转框') : (kind === 'pose' ? 'Predicted points' : 'Predicted boxes') }} · {{ sample.predictions?.length ?? '—' }}</span>
      </div>
      <dl v-if="geometry && sample.errors" class="geometry-counts">
        <template v-for="value in specificIssues" :key="value">
          <dt>{{ issueLabel(value) }}</dt><dd>{{ sample.errors[value] ?? 0 }}</dd>
        </template>
      </dl>
      <Teleport to="body">
        <ConfirmDialog v-if="expandedView && imageUrl" :title="sample.name" size="wide" panel-class="evaluation-sample-dialog" scroll-body
          :show-confirm="false" confirm-label="" :cancel-label="zh ? '关闭' : 'Close'" @cancel="expandedView = null">
          <div v-if="kind === 'segmentation' && sample.mask_available" class="sample-mask-mode" role="group" :aria-label="zh ? '预览图层' : 'Preview layer'">
            <Button size="sm" :aria-pressed="expandedView === 'original'" @click="expandedView = 'original'">{{ zh ? '原图' : 'Original' }}</Button>
            <Button v-for="entry in overlayViews" :key="entry.kind" size="sm" :disabled="!entry.url"
              :aria-pressed="expandedView === entry.kind" @click="expandedView = entry.kind">{{ entry.title }}</Button>
          </div>
          <div class="sample-image sample-image--expanded">
            <img :src="imageUrl" :alt="sample.name" />
            <EvaluationGeometryOverlay v-if="geometry && size.width" :width="size.width" :height="size.height" :layers="geometryLayers" :definitions="definitions" :show-keypoint-numbers="kind === 'pose'" />
            <img v-else-if="expandedView !== 'original' && layers[expandedView]" class="mask-overlay" :src="layers[expandedView]!" alt="" />
          </div>
        </ConfirmDialog>
      </Teleport>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { ChevronLeft, ChevronRight, ZoomIn } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Select from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import {
  fetchModelEvaluationImage, fetchSegmentationEvaluationOverlay, listModelEvaluationSamples,
  type AdditionalEvaluationKind, type GeometryIssue, type ModelEvaluationReport, type ModelEvaluationSample,
} from '../services/model-evaluation.service'
import EvaluationGeometryOverlay from './EvaluationGeometryOverlay.vue'

const props = defineProps<{ taskId: string; kind: AdditionalEvaluationKind; zh: boolean; definitions?: ModelEvaluationReport['keypoint_definitions'] }>()
const issue = defineModel<GeometryIssue>('issue', { default: 'all' })
const classification = computed(() => props.kind === 'classification')
const geometry = computed(() => props.kind === 'pose' || props.kind === 'obb')
const specificIssues = computed<GeometryIssue[]>(() =>
  props.kind === 'pose' ? ['keypoints', 'missed', 'extra'] : ['angle', 'localization', 'missed', 'extra'])
const issueCounts = ref<Partial<Record<GeometryIssue, number>>>({})
const labels: Record<GeometryIssue, [string, string]> = {
  all: ['全部样本', 'All samples'],
  errors: ['所有错误', 'All errors'],
  keypoints: ['关键点偏差', 'Keypoint error'],
  angle: ['角度偏差', 'Angle error'],
  localization: ['定位偏差', 'Localization error'],
  missed: ['漏检', 'Missed objects'],
  extra: ['误检', 'Extra detections'],
}
function issueLabel(value: GeometryIssue): string { return labels[value][props.zh ? 0 : 1] }
const issueOptions = computed(() => (['all', 'errors', ...specificIssues.value] as GeometryIssue[]).map(value => ({
  value, label: value !== 'all' && available.value ? `${issueLabel(value)} (${issueCounts.value[value] ?? 0})` : issueLabel(value),
})))
function changeIssue(value: unknown): void {
  const selected = issueOptions.value.find(option => option.value === value)
  if (selected) issue.value = selected.value
}
const samples = ref<ModelEvaluationSample[]>([])
const sample = computed(() => samples.value[0])
const pageSize = computed(() => classification.value ? 2 : 1)
const total = ref(0)
const offset = ref(0)
const revision = ref(0)
const imageRevision = ref(0)
const loading = ref(false)
const available = ref(false)
const error = ref('')
const imageError = ref(false)
const imageUrl = ref('')
const overlayKinds = ['combined', 'difference'] as const
type OverlayKind = typeof overlayKinds[number]
const layers = ref<Partial<Record<OverlayKind, string | null>>>({})
const layerRevisions = ref({ combined: 0, difference: 0 })
const overlaySample = shallowRef<ModelEvaluationSample>()
const expandedView = ref<OverlayKind | 'original' | null>(null)
const classificationImages = ref<Record<number, string | null>>({})
const showMasks = ref(true)
const showGroundTruth = ref(true)
const showPrediction = ref(true)
const size = ref({ width: 0, height: 0 })
const overlayViews = computed(() => overlayKinds.map(kind => ({
  kind, url: layers.value[kind],
  title: kind === 'combined'
    ? (props.zh ? '叠加结果' : 'Ground truth and prediction')
    : (props.zh ? '前景差异' : 'Foreground differences'),
})))
const geometryLayers = computed(() => [
  showGroundTruth.value ? sample.value?.ground_truth ?? [] : [],
  showPrediction.value ? sample.value?.predictions ?? [] : [],
])
const noSampleText = computed(() => available.value && classification.value
  ? (props.zh ? '没有分类错误的样本。' : 'No incorrect predictions.')
  : available.value && geometry.value && issue.value !== 'all'
    ? (props.zh ? '没有符合条件的错误样本。' : 'No samples match this error filter.')
  : (props.zh ? '此报告没有保存可预览的样本。' : 'This report has no saved samples to preview.'))

function readSize(event: Event): void {
  const image = event.target as HTMLImageElement
  size.value = { width: image.naturalWidth, height: image.naturalHeight }
}

watch(issue, () => { offset.value = 0 }, { flush: 'sync' })
watch([offset, revision, issue], async ([position, , filter], _, onCleanup) => {
  const request = new AbortController()
  onCleanup(() => request.abort())
  loading.value = true; error.value = ''; samples.value = []
  try {
    const response = await listModelEvaluationSamples(props.kind, props.taskId, position, pageSize.value, filter, request.signal)
    if (request.signal.aborted) return
    total.value = response.total
    available.value = response.available
    issueCounts.value = response.issue_counts ?? {}
    samples.value = response.items
  } catch (cause) { if (!request.signal.aborted) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (!request.signal.aborted) loading.value = false }
}, { immediate: true })

watch([sample, imageRevision], async ([entry], _, onCleanup) => {
  imageUrl.value = ''; imageError.value = false; size.value = { width: 0, height: 0 }
  if (!entry || classification.value) return
  const request = new AbortController()
  let url = ''
  onCleanup(() => { request.abort(); if (url) URL.revokeObjectURL(url) })
  try {
    const blob = await fetchModelEvaluationImage(props.kind, props.taskId, entry.index, request.signal)
    if (!request.signal.aborted) { url = URL.createObjectURL(blob); imageUrl.value = url }
  } catch { if (!request.signal.aborted) imageError.value = true }
})

function categoryImageFailed(index: number): void { classificationImages.value[index] = null }

watch([samples, imageRevision], async ([entries], _, onCleanup) => {
  if (!classification.value) return
  classificationImages.value = {}
  const request = new AbortController()
  const urls: string[] = []
  onCleanup(() => { request.abort(); urls.forEach(url => URL.revokeObjectURL(url)) })
  await Promise.all(entries.map(async entry => {
    try {
      const blob = await fetchModelEvaluationImage(props.kind, props.taskId, entry.index, request.signal)
      if (request.signal.aborted) return
      const url = URL.createObjectURL(blob)
      urls.push(url)
      classificationImages.value[entry.index] = url
    } catch { if (!request.signal.aborted) categoryImageFailed(entry.index) }
  }))
})

watch(sample, () => { expandedView.value = null })
watch([sample, showMasks], ([entry, enabled], [previous]) => {
  if (enabled || entry !== previous) overlaySample.value = enabled ? entry : undefined
})
for (const kind of overlayKinds) {
  watch([overlaySample, () => layerRevisions.value[kind]], async ([entry], _, onCleanup) => {
    layers.value[kind] = undefined
    if (props.kind !== 'segmentation' || !entry?.mask_available) return
    const request = new AbortController()
    let url: string | undefined
    onCleanup(() => {
      request.abort()
      if (url) URL.revokeObjectURL(url)
    })
    try {
      const blob = await fetchSegmentationEvaluationOverlay(props.taskId, entry.index, kind, request.signal)
      if (request.signal.aborted) return
      url = blob?.size ? URL.createObjectURL(blob) : undefined
      layers.value[kind] = url ?? ''
    } catch {
      if (!request.signal.aborted) layers.value[kind] = null
    }
  })
}
</script>

<style scoped>
.sample-report { display:grid; gap:12px; min-width:0; align-content:start; }
.sample-report header, .sample-caption, .sample-navigation, .sample-legend { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
.sample-report header { justify-content:space-between; }
.sample-report :is(h2,p,figure,dl) { margin:0; }
.sample-report h2 small { margin-inline-start:4px; color:var(--am-text-muted); font-size:var(--am-type-caption); font-weight:400; }
.sample-caption strong { margin-inline-end:auto; overflow-wrap:anywhere; }
.sample-image { position:relative; width:fit-content; max-width:100%; }
.sample-report img { display:block; max-width:100%; max-height:420px; border-radius:5px; }
.sample-image--expanded { margin:8px auto 0; }
.sample-image--expanded img { display:block; max-width:100%; max-height:63vh; }
:global(.evaluation-sample-dialog .confirm-dialog__header > div) { min-width:0; }
:global(.evaluation-sample-dialog .confirm-dialog__header h2) { overflow-wrap:anywhere; }
:global(.evaluation-sample-dialog .confirm-dialog__close) { flex:none; }
:global(.evaluation-sample-dialog .confirm-dialog__content) { grid-template-columns:minmax(0,1fr); }
.sample-mask-mode { display:flex; flex-wrap:wrap; gap:6px; }
.mask-overlay { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }
.mask-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.mask-grid--single { grid-template-columns:minmax(0,1fr); }
.mask-grid figure { padding:8px; border:1px solid var(--am-border); border-radius:6px; }
.mask-grid figcaption { margin-block-end:6px; color:var(--am-text-muted); }
.overlay-status { display:flex; align-items:center; flex-wrap:wrap; gap:6px; padding-block-start:6px; color:var(--am-text-muted); }
.classification-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.classification-card { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); align-items:start; gap:12px; border:1px solid var(--am-border); border-radius:6px; padding:10px; }
.classification-card img { width:100%; height:auto; max-height:175px; object-fit:contain; background:var(--am-surface-soft); }
.sample-report dl { display:grid; gap:8px; grid-template-columns:max-content minmax(0,1fr); align-content:start; }
.sample-report dd { margin:0; overflow-wrap:anywhere; }
.sample-report dt { color:var(--am-text-muted); }
.sample-report .geometry-counts { display:flex; flex-wrap:wrap; gap:4px 12px; }
.geometry-counts dd { margin-inline-end:6px; font-variant-numeric:tabular-nums; }
.sample-placeholder { padding:24px; color:var(--am-text-muted); background:var(--am-surface-soft); border-radius:6px; }
.sample-legend span::before { display:inline-block; width:.75em; height:.75em; margin-inline-end:6px; border-radius:2px; background:var(--swatch,currentColor); content:''; }
.sample-legend .truth { --swatch:#00dc7d; }
.sample-legend .prediction { --swatch:#ff9824; }
.sample-legend .false-positive { --swatch:#ff5050; }
.sample-legend .false-negative { --swatch:#2e7aff; }
.sample-legend .geometry-prediction::before { border:1px dashed var(--swatch); background:transparent; }
@media (max-width:690px) { .mask-grid, .classification-grid { grid-template-columns:minmax(0,1fr); } }
</style>
