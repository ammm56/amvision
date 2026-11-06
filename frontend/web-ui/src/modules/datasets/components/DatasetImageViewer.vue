<template>
  <section v-if="open && image" class="dataset-image-workspace" :aria-busy="busy" @keydown.esc.stop="infoOpen ? emit('close-info') : emit('close')">
    <header class="dataset-image-heading">
      <Button @click="emit('close')"><ArrowLeft :size="16" />{{ text('back') }}</Button>
      <h1 :title="`${datasetName} / ${version} / ${image.title}`">{{ datasetName }} <span>/ {{ version }} /</span> {{ image.title }}</h1>
      <span class="dataset-image-split">{{ split }}</span>
      <span class="dataset-image-meta">{{ image.width }} × {{ image.height }}</span>
      <span class="dataset-image-meta">{{ objectCount }} {{ text('object') }}</span>
    </header>
    <div class="dataset-image-toolbar">
      <div class="dataset-actions dataset-image-tool-group">
        <Button :disabled="busy || !hasPrevious" @click="emit('previous')"><ChevronLeft :size="16" />{{ text('previous') }}</Button>
        <Button :disabled="busy || !hasNext" @click="emit('next')">{{ text('next') }}<ChevronRight :size="16" /></Button>
      </div>
      <div class="dataset-actions dataset-image-tool-group">
        <Button icon-only :aria-label="label('缩小', 'Zoom out')" @click="zoomOut"><Minus :size="16" /></Button>
        <SelectField class="dataset-image-zoom" :model-value="String(Math.round(scale * 100))" :aria-label="label('缩放比例', 'Zoom')" :options="zoomOptions" @update:model-value="setZoom" />
        <Button icon-only :aria-label="label('放大', 'Zoom in')" @click="zoomIn"><Plus :size="16" /></Button>
        <Button @click="fitImage"><Scan :size="16" />{{ label('适配', 'Fit') }}</Button>
      </div>
      <div class="dataset-actions dataset-image-tool-group">
      <label v-if="task !== 'classification'" class="dataset-image-annotations"><input type="checkbox" role="switch" :checked="annotations" @change="emit('annotations', ($event.target as HTMLInputElement).checked)" />{{ text('showAnnotations') }}</label>
      <Button class="dataset-image-info" @click="emit('info')"><Info :size="16" />{{ text('objects') }}</Button>
      </div>
    </div>
    <div class="dataset-image-viewport" :aria-label="image.title" @wheel.prevent="handleWheel" @mousedown="startPan" @dblclick="fitImage" @keydown.left.prevent="!busy && hasPrevious && emit('previous')" @keydown.right.prevent="!busy && hasNext && emit('next')">
      <div ref="viewportRef" class="dataset-image-canvas" tabindex="0">
      <div class="dataset-image-frame" :style="imageFrameStyle"><img :src="image.src" :alt="image.title" :style="imageElementStyle" draggable="false" @load="imageLoaded" /></div>
      <span v-if="busy" class="dataset-image-loading" role="status">{{ text('loading') }}</span>
      </div>
    </div>
    <p v-if="invalid" class="dataset-muted">{{ invalid }} {{ text('invalidAnnotations') }}</p>
  </section>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, ChevronLeft, ChevronRight, Minus, Plus, Scan, Info } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import { useImageViewerViewport } from '@/shared/ui/image-viewer/useImageViewerViewport'
import { useDatasetText } from '../dataset-workspace'
const props = defineProps<{
  open: boolean
  image: { id?: string; title: string; src: string; width: number; height: number; mediaType?: string } | null
  datasetName: string
  version: string
  split: string
  objectCount: number
  annotations: boolean
  busy: boolean
  hasPrevious: boolean
  hasNext: boolean
  invalid: number
  infoOpen?: boolean
  focusedBounds?: number[] | null
  task?: string
}>()
const emit = defineEmits<{ close: []; 'close-info': []; previous: []; next: []; info: []; annotations: [value: boolean] }>()
const text = useDatasetText(), { locale } = useI18n()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const viewportRef = ref<HTMLElement | null>(null)
const { scale, offsetX, offsetY, viewportWidth, imageFrameStyle, imageElementStyle, fitImage, zoomIn, zoomOut, handleWheel, startPan, stopPan } = useImageViewerViewport({
  viewportRef, imageWidth: computed(() => props.image?.width || 1), imageHeight: computed(() => props.image?.height || 1),
})
// 抽屉覆盖画布时只平移图像，保留比例；关闭后还原阅读位置。
let savedOffset: { x: number; y: number } | null = null
watch([() => props.infoOpen, () => props.focusedBounds], ([open]) => {
  if (open) {
    savedOffset ??= { x: offsetX.value, y: offsetY.value }
    const reserved = Math.min(520, viewportWidth.value - 80)
    const box = props.focusedBounds
    const valid = box?.length === 4 && box.every(Number.isFinite)
    const x = valid ? box[0] + box[2] / 2 : (props.image?.width || 1) / 2
    const y = valid ? box[1] + box[3] / 2 : (props.image?.height || 1) / 2
    offsetX.value = -reserved / 2 - (x - (props.image?.width || 1) / 2) * scale.value
    offsetY.value = -(y - (props.image?.height || 1) / 2) * scale.value
  } else if (savedOffset) { offsetX.value = savedOffset.x; offsetY.value = savedOffset.y; savedOffset = null }
})
const zoomOptions = computed(() => [...new Set([25, 50, 75, 100, 150, 200, Math.round(scale.value * 100)])].sort((a, b) => a - b).map(value => ({ value: String(value), label: `${value}%` })))
function setZoom(value: string | number | boolean | null) { const n = Number(value); if (Number.isFinite(n)) scale.value = Math.min(8, Math.max(.05, n / 100)) }
let needsFit = true
watch([() => props.open, () => props.image?.id || props.image?.title], async () => { needsFit = true; stopPan(); await nextTick(); fitImage(); viewportRef.value?.focus({ preventScroll: true }) }, { immediate: true })
// 标注开关只替换图像，不重置用户当前的缩放和平移。
function imageLoaded() { if (needsFit) { fitImage(); needsFit = false } }
</script>
<style scoped>
.dataset-image-workspace { display:grid; grid-template-rows:auto auto minmax(300px,1fr); gap:16px; min-width:0; height:calc(100dvh - 2 * clamp(var(--am-space-xl), 2vw, var(--am-space-3xl))); }
.dataset-image-heading { display:flex; align-items:center; gap:14px; min-width:0; }
.dataset-image-heading h1 { flex:0 1 auto; min-width:0; font-size:18px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin:0; }
.dataset-image-heading h1 span { color:var(--am-text-muted); font-weight:400; }
.dataset-image-meta { color:var(--am-text-muted); white-space:nowrap; font-size:13px; }
.dataset-image-split { background:var(--am-surface-muted); border-radius:var(--am-radius-sm); padding:4px 8px; font-size:13px; }
.dataset-image-toolbar { display:flex; align-items:center; flex-wrap:wrap; gap:16px; background:var(--am-surface); border:1px solid var(--am-border); border-radius:var(--am-radius-md); padding:12px; }
.dataset-image-zoom { width:84px; }
.dataset-image-tool-group { flex-wrap:nowrap; gap:8px; }
.dataset-image-tool-group + .dataset-image-tool-group { border-left:1px solid var(--am-border); padding-left:20px; }
.dataset-image-tool-group:last-child { gap:16px; }
.dataset-image-info { margin-left:0; }
.dataset-image-viewport { position:relative; overflow:hidden; min-width:0; min-height:0; background:var(--am-surface-muted); border:1px solid var(--am-border); border-radius:var(--am-radius-md); cursor:grab; touch-action:none; }
.dataset-image-viewport:active { cursor:grabbing; }
.dataset-image-canvas { position:absolute; inset:16px; overflow:hidden; outline:none; }
.dataset-image-frame { position:absolute; top:50%; left:50%; transform-origin:center; }
.dataset-image-frame img { display:block; max-width:none; user-select:none; }
.dataset-image-loading { position:absolute; top:12px; left:12px; padding:6px 10px; border-radius:var(--am-radius-sm); background:var(--am-surface); }
.dataset-image-annotations { display:flex; align-items:center; gap:8px; white-space:nowrap; font-size:13px; }
.dataset-image-annotations input { appearance:none; width:30px; height:18px; border:0; border-radius:20px; position:relative; background:var(--am-border-strong); cursor:pointer; }
.dataset-image-annotations input:after { content:''; position:absolute; width:12px; height:12px; top:3px; left:3px; background:white; border-radius:50%; transition:transform .16s ease; }
.dataset-image-annotations input:checked { background:var(--am-brand-primary); }
.dataset-image-annotations input:checked:after { transform:translateX(12px); }
@media(max-width:1100px) { .dataset-image-heading { gap:8px; } .dataset-image-heading h1 { font-size:16px; } .dataset-image-toolbar { gap:16px; } .dataset-image-tool-group + .dataset-image-tool-group { padding-left:16px; } }
</style>
