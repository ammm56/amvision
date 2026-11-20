<template>
  <section ref="viewer" class="evaluation-preview" :aria-label="label('评估样本', 'Evaluation sample')" :aria-busy="navigating" tabindex="-1" @keydown.esc.stop="infoOpen ? closeInfo() : emit('close')">
    <header class="evaluation-preview__header">
      <div class="evaluation-preview__tools">
        <Button @click="emit('close')"><ArrowLeft :size="16" />{{ label('返回评估详情', 'Back to evaluation') }}</Button>
        <h1 :title="sample.name">{{ sample.name }}</h1>
      </div>
      <div class="evaluation-preview__tools">
        <Button icon-only :aria-label="label('上一张', 'Previous image')" :disabled="navigating || position <= 1" @click="emit('navigate', -1)"><ChevronLeft :size="16" /></Button>
        <span class="evaluation-preview__position" aria-live="polite">{{ position }} / {{ total }}</span>
        <Button icon-only :aria-label="label('下一张', 'Next image')" :disabled="navigating || position >= total" @click="emit('navigate', 1)"><ChevronRight :size="16" /></Button>
      </div>
    </header>
    <div class="evaluation-preview__toolbar">
      <div class="evaluation-preview__tools">
        <label><input v-model="showGroundTruth" type="checkbox" :disabled="!sample.ground_truth" />{{ label('显示标注', 'Ground truth') }}</label>
        <label><input v-model="showPredictions" type="checkbox" :disabled="!sample.predictions" />{{ label('显示预测', 'Predictions') }}</label>
      </div>
      <div class="evaluation-preview__tools">
        <Button icon-only :aria-label="label('缩小', 'Zoom out')" :disabled="!size" @click="zoomOut"><Minus :size="16" /></Button>
        <output>{{ size ? Math.round(scale * 100) + '%' : '—' }}</output>
        <Button icon-only :aria-label="label('放大', 'Zoom in')" :disabled="!size" @click="zoomIn"><Plus :size="16" /></Button>
        <Button :disabled="!size" @click="fitImage"><Scan :size="16" />{{ label('适应窗口', 'Fit to window') }}</Button>
      </div>
      <Button ref="infoButton" :aria-expanded="infoOpen" aria-controls="evaluation-object-info" @click="infoOpen ? closeInfo() : openInfo()"><Info :size="16" />{{ label('对象信息', 'Object information') }}</Button>
    </div>
    <div v-if="navigationError" class="evaluation-preview__message" role="alert">{{ navigationError }}</div>
    <div class="evaluation-preview__stage">
      <div ref="viewport" class="evaluation-preview__canvas" :class="{ 'is-ready': size }" @wheel="zoomOnWheel" @mousedown="size && startPan($event)" @dblclick="fitImage">
        <div v-if="imageError" class="evaluation-image-state" role="alert">{{ label('图片不可用', 'Image unavailable') }} <Button size="sm" @click="imageRevision++">{{ label('重试', 'Retry') }}</Button></div>
        <div v-else-if="imageUrl" class="evaluation-image" :style="imageFrameStyle">
          <img :src="imageUrl" :alt="sample.name" draggable="false" @load="imageLoaded" @error="readImageError" />
          <template v-if="size">
            <button v-for="(object, index) in visibleObjects" :key="index" type="button" :class="['evaluation-box', object.kind, { 'is-active': object === focusedObject && infoOpen }]"
              :style="boxStyle(object.box)" :aria-label="`${object.kind === 'ground-truth' ? 'GT' : label('预测', 'Prediction')} ${object.box.class_name}`"
              @mousedown.stop @click="openInfo(object)">
              <small>{{ object.box.class_name }}<template v-if="object.box.score != null"> {{ formatModelNumber(object.box.score, 2) }}</template></small>
            </button>
          </template>
        </div>
        <div v-else class="evaluation-image-state" role="status">{{ label('正在读取图片…', 'Loading image…') }}</div>
      </div>
      <aside v-if="infoOpen" id="evaluation-object-info" class="evaluation-preview__info" :aria-label="label('对象信息', 'Object information')">
        <header><h2>{{ label('对象信息', 'Object information') }}</h2><Button icon-only variant="ghost" :aria-label="label('关闭对象信息', 'Close object information')" @click="closeInfo"><X :size="18" /></Button></header>
        <div class="evaluation-preview__info-content">
          <div v-if="objects.length > 1" class="evaluation-preview__object-select">
            <label for="evaluation-object-select">{{ label('选择对象', 'Select object') }}</label>
            <Select id="evaluation-object-select" :model-value="String(focusedIndex)" :options="objectOptions" :aria-label="label('选择对象', 'Select object')" @update:model-value="focusedIndex = Number($event)" />
          </div>
          <dl v-if="focusedObject">
            <dt>{{ label('结果', 'Result') }}</dt><dd><StatusBadge :tone="focusedObject.box.matched ? 'success' : 'danger'">{{ resultLabel(focusedObject) }}</StatusBadge></dd>
            <dt>{{ label('GT 类别', 'GT class') }}</dt><dd>{{ focusedObject.kind === 'ground-truth' ? focusedObject.box.class_name : '—' }}</dd>
            <dt>{{ label('预测类别', 'Predicted class') }}</dt><dd>{{ focusedObject.kind === 'prediction' ? focusedObject.box.class_name : '—' }}</dd>
            <dt>{{ label('预测置信度', 'Prediction confidence') }}</dt><dd>{{ focusedObject.box.score == null ? '—' : formatModelNumber(focusedObject.box.score, 4) }}</dd>
            <dt>{{ label('匹配状态', 'Match status') }}</dt><dd>{{ focusedObject.box.matched ? label('已匹配', 'Matched') : label('未匹配', 'Unmatched') }}</dd>
            <template v-if="sample.localization_pair">
              <dt>{{ label('候选框 IoU', 'Candidate IoU') }}</dt><dd>{{ formatModelNumber(sample.localization_pair.iou) }}</dd>
            </template>
            <dt>{{ label('数据划分', 'Split') }}</dt><dd>{{ split || '—' }}</dd>
          </dl>
          <p v-else>{{ sample.ground_truth || sample.predictions ? label('当前筛选下没有对象。', 'No objects match the current filters.') : label('此报告未保存标注框和预测框。', 'This report did not save ground-truth or prediction boxes.') }}</p>
          <section v-if="diagnosticsAvailable">
            <h3>{{ label('评估规则', 'Evaluation rules') }}</h3>
            <dl>
              <dt>{{ label('置信度阈值', 'Score threshold') }}</dt><dd>{{ scoreThreshold == null ? '—' : formatModelNumber(scoreThreshold, 4) }}</dd>
              <dt>{{ label('匹配 IoU 阈值', 'Matching IoU threshold') }}</dt><dd>0.50</dd>
              <dt>{{ label('类别匹配', 'Class matching') }}</dt><dd>{{ label('同一类别', 'Same class') }}</dd>
            </dl>
          </section>
          <div class="evaluation-preview__legend"><span><i class="ground-truth" />{{ label('GT（真实框）', 'Ground truth') }}</span><span><i class="prediction" />{{ label('预测框', 'Prediction') }}</span></div>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ArrowLeft, ChevronLeft, ChevronRight, Info, Minus, Plus, Scan, X } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import Select from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import { useImageViewerViewport } from '@/shared/ui/image-viewer/useImageViewerViewport'
import { formatModelNumber } from '../model-number-format'
import { fetchDetectionEvaluationImage, type DetectionEvaluationSample, type EvaluationBox } from '../services/model-evaluation.service'

type EvaluationObject = { box: EvaluationBox; kind: 'ground-truth' | 'prediction' }
const props = defineProps<{
  taskId: string
  sample: DetectionEvaluationSample
  objects: EvaluationObject[]
  position: number
  total: number
  split?: string
  scoreThreshold?: number
  diagnosticsAvailable: boolean
  navigating: boolean
  navigationError: string
  zh: boolean
}>()
const emit = defineEmits<{ close: []; navigate: [direction: -1 | 1] }>()
const label = (zh: string, en: string) => props.zh ? zh : en
const viewer = ref<HTMLElement | null>(null)
const infoButton = ref<InstanceType<typeof Button> | null>(null)
const viewport = ref<HTMLElement | null>(null)
const size = ref<{ width: number; height: number }>()
const infoOpen = ref(true)
const imageUrl = ref('')
const imageError = ref(false)
const imageRevision = ref(0)
const focusedIndex = ref(0)
const showGroundTruth = ref(true)
const showPredictions = ref(true)
const focusedObject = computed(() => props.objects[focusedIndex.value])
const visibleObjects = computed(() => props.objects.filter(({ kind }) => kind === 'ground-truth' ? showGroundTruth.value : showPredictions.value))
const objectOptions = computed(() => props.objects.map((item, index) => ({
  value: String(index), label: `${index + 1}. ${item.box.class_name} · ${resultLabel(item)}`,
})))
const reservedRight = computed(() => infoOpen.value && viewportWidth.value > 520 ? Math.min(300, viewportWidth.value * 0.42) + 16 : 0)
const { scale, viewportWidth, viewportHeight, imageFrameStyle, fitImage, zoomIn, zoomOut, handleWheel, startPan, stopPan } = useImageViewerViewport({
  viewportRef: viewport,
  imageWidth: computed(() => size.value?.width ?? 0),
  imageHeight: computed(() => size.value?.height ?? 0),
  reservedRightPx: reservedRight,
})

function resultLabel({ box, kind }: EvaluationObject): string {
  if (box.matched) return label('匹配', 'Matched')
  if (props.sample.localization_pair) return label('定位偏差', 'Localization error')
  return kind === 'ground-truth' ? label('FN 漏检', 'FN Missed') : label('FP 误检', 'FP Extra')
}

function openInfo(object?: EvaluationObject): void {
  if (object) focusedIndex.value = props.objects.indexOf(object)
  infoOpen.value = true
}

async function closeInfo(): Promise<void> {
  infoOpen.value = false
  await nextTick()
  infoButton.value?.$el.focus()
}

function imageLoaded(event: Event): void {
  const image = event.currentTarget as HTMLImageElement
  size.value = { width: image.naturalWidth, height: image.naturalHeight }
  fitImage()
}

function readImageError(): void {
  size.value = undefined
  imageError.value = true
}

function boxStyle(box: EvaluationBox) {
  const [left, top, right, bottom] = box.bbox_xyxy
  return { left: `${left}px`, top: `${top}px`, width: `${right - left}px`, height: `${bottom - top}px`, '--inverse-zoom': 1 / scale.value }
}

function zoomOnWheel(event: WheelEvent): void {
  if (!size.value) return
  event.preventDefault()
  handleWheel(event)
}

watch([reservedRight, viewportWidth, viewportHeight], () => { if (size.value) fitImage() }, { flush: 'post' })
watch(() => props.sample.image_index, () => { focusedIndex.value = 0 })
watch([() => props.taskId, () => props.sample.image_index, imageRevision], async ([taskId, index], _, onCleanup) => {
  stopPan()
  size.value = undefined
  imageUrl.value = ''
  imageError.value = false
  const controller = new AbortController()
  let objectUrl = ''
  onCleanup(() => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) })
  try {
    const image = await fetchDetectionEvaluationImage(taskId, index, controller.signal)
    if (controller.signal.aborted) return
    objectUrl = URL.createObjectURL(image)
    imageUrl.value = objectUrl
  } catch {
    if (!controller.signal.aborted) readImageError()
  }
}, { immediate: true })
onMounted(() => viewer.value?.focus({ preventScroll: true }))
</script>

<style scoped>
.evaluation-preview { display:grid; grid-template-rows:auto auto auto minmax(280px,1fr); gap:12px; min-width:0; min-height:calc(100dvh - 56px); }
.evaluation-preview__header,.evaluation-preview__toolbar,.evaluation-preview__tools { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; min-width:0; }
.evaluation-preview__header { justify-content:space-between; }
.evaluation-preview__header h1 { margin:0; font-size:20px; min-width:0; overflow-wrap:anywhere; }
.evaluation-preview__toolbar { padding-block:2px; }
.evaluation-preview__toolbar label { display:flex; align-items:center; gap:6px; }
.evaluation-preview__toolbar input { accent-color:var(--am-brand-primary); }
.evaluation-preview__toolbar output,.evaluation-preview__position { min-width:52px; text-align:center; font-variant-numeric:tabular-nums; }
.evaluation-preview__message { color:var(--am-danger-text); overflow-wrap:anywhere; }
.evaluation-preview__stage { position:relative; grid-row:4; display:grid; min-width:0; min-height:0; }
.evaluation-preview__canvas { position:relative; overflow:hidden; min-height:0; border:1px solid var(--am-border); border-radius:var(--am-radius-md); background:var(--am-surface-muted); }
.evaluation-preview__canvas.is-ready { cursor:grab; }
.evaluation-preview__canvas.is-ready:active { cursor:grabbing; }
.evaluation-image { position:absolute; top:50%; left:50%; transform-origin:center; }
.evaluation-image img { display:block; width:100%; height:100%; max-width:none; user-select:none; }
.evaluation-image-state { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; gap:8px; color:var(--am-text-muted); }
.evaluation-box { position:absolute; padding:0; border:calc(2px * var(--inverse-zoom)) solid currentColor; background:transparent; cursor:pointer; }
.ground-truth { color:var(--am-brand-primary); }
.prediction { color:#f79235; border-style:dashed; }
.evaluation-box.is-active,.evaluation-box:focus-visible { outline:calc(1px * var(--inverse-zoom)) solid currentColor; outline-offset:calc(2px * var(--inverse-zoom)); }
.evaluation-box small { position:absolute; top:0; left:0; padding:2px 4px; white-space:nowrap; color:#161819; background:var(--am-brand-primary); transform:scale(var(--inverse-zoom)); transform-origin:left top; }
.evaluation-box.prediction small { background:#f79235; }
.evaluation-preview__info { position:absolute; z-index:1; inset:12px 12px auto auto; display:grid; grid-template-rows:auto minmax(0,1fr); width:min(300px,42%); max-height:calc(100% - 24px); border:1px solid var(--am-border); border-radius:var(--am-radius-md); background:var(--am-surface-raised); box-shadow:var(--am-shadow-modal); }
.evaluation-preview__info header { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 14px; border-block-end:1px solid var(--am-border); }
.evaluation-preview__info h2,.evaluation-preview__info h3 { margin:0; font-size:15px; }
.evaluation-preview__info-content { display:grid; gap:14px; padding:14px; overflow-y:auto; }
.evaluation-preview__info-content section { display:grid; gap:10px; padding-block:12px; border-block:1px solid var(--am-border); }
.evaluation-preview__info-content dl { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:10px; margin:0; }
.evaluation-preview__info-content :is(dt,dd,p) { margin:0; overflow-wrap:anywhere; }
.evaluation-preview__info-content dt { color:var(--am-text-muted); }
.evaluation-preview__object-select { display:grid; gap:6px; min-width:0; }
.evaluation-preview__legend,.evaluation-preview__legend span { display:flex; align-items:center; flex-wrap:wrap; gap:6px; }
.evaluation-preview__legend { gap:8px 12px; font-size:12px; }
.evaluation-preview__legend i { width:18px; height:12px; border-width:2px; border-color:currentColor; border-style:solid; }
.evaluation-preview__legend .prediction { border-style:dashed; }
@media (max-width:660px) {
  .evaluation-preview__info { width:min(300px,calc(100% - 24px)); }
}
</style>
