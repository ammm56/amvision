<template>
  <section
    ref="shell"
    class="media-viewer"
    :class="{ 'media-viewer--info-open': infoOpen }"
    tabindex="-1"
    @keydown.esc.stop="$emit('close')"
  >
    <div class="dataset-heading">
      <div class="dataset-actions">
        <Button @click="$emit('close')"
          ><ArrowLeft :size="16" />{{ l('返回', 'Back') }}</Button
        >
        <h1 class="dataset-title" :title="sample.file_name">
          {{ name }} / {{ version }} / {{ sample.file_name }}
        </h1>
      </div>
    </div>
    <div class="media-toolbar">
      <div class="dataset-actions">
        <Button :disabled="busy || !previous" @click="$emit('previous')"
          ><ChevronLeft :size="15" />{{ l('上一张', 'Previous') }}</Button
        ><Button :disabled="busy || !next" @click="$emit('next')"
          >{{ l('下一张', 'Next') }}<ChevronRight :size="15"
        /></Button>
      </div>
      <div v-if="media.kind !== 'point-cloud'" class="dataset-actions">
        <Button :aria-label="l('缩小', 'Zoom out')" @click="zoom(0.8)"
          ><Minus :size="15" /></Button
        ><SelectField :model-value="String(Math.round(currentScale * 100))" :aria-label="l('缩放比例', 'Zoom')" :options="zoomOptions" @update:model-value="setZoom" />
        <Button :aria-label="l('放大', 'Zoom in')" @click="zoom(1.25)"
          ><Plus :size="15"
        /></Button><Button @click="scales = [1, 1]">{{ l('适配', 'Fit') }}</Button>
      </div>
      <div v-if="media.kind === 'rgbd'" class="dataset-actions">
        <SegmentedButtonGroup v-model="mode" :label="l('视图', 'View')" :options="modes" /><label
          ><input v-model="linked" type="checkbox" />
          {{ l('联动缩放', 'Linked zoom') }}</label
        >
      </div>
      <label v-if="media.kind === 'connector-reference'"
        ><input v-model="overlay" type="checkbox" />
        {{ l('针位编号', 'PIN labels') }}</label
      >
      <template v-if="media.kind === 'anomaly'">
        <label class="media-layer">{{ l('标注图层', 'Annotation layer') }}
          <SelectField :model-value="overlay" :aria-label="l('标注图层', 'Annotation layer')" :options="annotationLayers" @update:model-value="overlay = $event === true" />
        </label>
        <label class="media-layer">{{ l('预测图层', 'Prediction layer') }}
          <SelectField model-value="unloaded" disabled :aria-label="l('预测图层', 'Prediction layer')" :options="predictionLayers" />
        </label>
      </template>
      <Button @click="$emit('info')"
        ><Info :size="15" />{{
          media.kind === 'connector-reference'
            ? l('参考资料', 'Reference')
            : l('样本信息', 'Sample info')
        }}</Button
      >
    </div>
    <InlineError v-if="error" :message="error" /><Button
      v-if="error"
      @click="load"
      >{{ l('重试', 'Retry') }}</Button
    >
    <DatasetCloudView
      v-if="media.kind === 'point-cloud'"
      :media="media"
      :sample="sample"
      :dataset="dataset"
    />
    <div
      v-else
      class="media-planes"
      :class="{ pair: media.kind === 'rgbd' && mode === 'both' }"
    >
      <div
        v-if="mode !== 'depth'"
        class="media-plane"
        tabindex="0"
        @focusin="active = 0"
        @pointerdown="active = 0"
        @wheel.ctrl.prevent="wheelZoom(0, $event)"
      >
        <span v-if="media.kind === 'rgbd'" class="media-plane-label">RGB {{ sample.width }} × {{ sample.height }}</span>
        <div
          class="media-frame"
          :style="frameStyle(0, sample.width / sample.height)"
        >
          <img :src="image" :alt="sample.file_name" />
          <img
            v-if="overlay && mask"
            class="overlay"
            :src="mask"
            :alt="l('真值掩膜', 'Ground truth mask')"
          />
          <template v-if="overlay"
            ><span
              v-for="pin in media.pins"
              :key="pin.id"
              class="pin"
              :style="{
                left: (100 * pin.x) / sample.width + '%',
                top: (100 * pin.y) / sample.height + '%',
              }"
              >{{ pin.id }}</span
            ></template
          >
        </div>
      </div>
      <div
        v-if="media.kind === 'rgbd' && mode !== 'rgb'"
        class="media-plane"
        tabindex="0"
        @focusin="active = 1"
        @pointerdown="active = 1"
        @wheel.ctrl.prevent="wheelZoom(1, $event)"
      >
        <span class="media-plane-label">{{ l('深度', 'Depth') }} {{ media.depth_size?.join(' × ') }} <template v-if="media.unit">({{ media.unit }})</template></span>
        <div
          v-if="depth && media.depth_size"
          class="media-frame"
          :style="frameStyle(1, media.depth_size[0] / media.depth_size[1])"
        >
          <img
            :src="depth"
            :alt="l('深度伪彩', 'Depth map')"
            @pointermove="inspect"
            @pointerleave="reading = ''"
          />
        </div>
      </div>
    </div>
    <div v-if="media.kind === 'rgbd'" class="media-footer">
      <span>{{ media.id }}</span
      ><span>RGB {{ sample.width }} × {{ sample.height }}</span
      ><span>{{ l('深度', 'Depth') }} {{ media.depth_size?.join(' × ') }}</span
      ><span v-if="media.depth_range" class="depth-scale"
        >{{ media.depth_range.join(' – ') }} {{ media.unit }}</span
      ><span v-else>{{ l('无有效深度', 'No valid depth') }}</span
      ><span>{{ l('无效值', 'Invalid') }} {{ media.invalid }}</span
      ><output>{{ reading }}</output>
    </div>
    <p v-else-if="media.kind === 'connector-reference'" class="dataset-muted">
      {{
        media.synthetic
          ? l('合成设计值', 'Synthetic design')
          : l('设计参考', 'Design reference')
      }}<template v-if="media.pitch">
        · {{ l('节距', 'Pitch') }} {{ media.pitch }} {{ media.unit }}</template
      >
    </p>
    <p v-else-if="media.kind === 'anomaly'" class="dataset-muted">
      {{ media.label === 'normal' ? l('正常', 'Normal') : l('异常', 'Anomaly')
      }}<template v-if="media.defect"> · {{ media.defect }}</template> ·
      {{
        media.assets.includes('mask')
          ? l('已提供区域真值', 'Region annotated')
          : l('未提供区域标注', 'No region annotation')
      }}
    </p>
    <nav
      v-if="neighbors.length > 1"
      class="media-strip"
      :aria-label="l('附近样本', 'Nearby samples')"
    >
      <button
        v-for="item in neighbors"
        :key="item.sample_id"
        :title="item.file_name"
        :aria-label="item.file_name"
        :aria-current="item.sample_id === sample.sample_id || undefined"
        :disabled="busy"
        @click="item.sample_id !== sample.sample_id && $emit('pick', item)"
      >
        <DatasetSampleImage
          :dataset-id="dataset"
          :sample="item"
          :categories="[]"
          :show-annotations="false"
        />
      </button>
    </nav>
  </section>
</template>
<script setup lang="ts">
import {
  ref,
  computed,
  onMounted,
  onBeforeUnmount,
  defineAsyncComponent,
} from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Info,
  Minus,
  Plus,
} from '@lucide/vue'
import DatasetSampleImage from './DatasetSampleImage.vue'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import SegmentedButtonGroup from '@/shared/ui/components/SegmentedButtonGroup.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { readSampleAsset, type SampleMedia } from '../sample-media'
import type { DatasetSample } from '../services/dataset-workspace.service'
const DatasetCloudView = defineAsyncComponent(
  () => import('./DatasetCloudView.vue'),
)
const props = defineProps<{
  dataset: string
  name: string
  version: string
  image: string
  sample: DatasetSample
  media: SampleMedia
  previous: boolean
  next: boolean
  busy: boolean
  neighbors: DatasetSample[]
  infoOpen?: boolean
}>()
defineEmits<{
  close: []
  info: []
  previous: []
  next: []
  pick: [sample: DatasetSample]
}>()
const { locale } = useI18n(),
  l = (zh: string, en: string) => (locale.value.startsWith('zh') ? zh : en)
const overlay = ref(true),
  linked = ref(true),
  mode = ref(props.media.kind === 'rgbd' ? 'both' : 'rgb'),
  active = ref(0),
  scales = ref<[number, number]>([1, 1])
const modes = computed(() => [
  { value: 'rgb', label: 'RGB' },
  { value: 'depth', label: l('深度', 'Depth') },
  { value: 'both', label: l('并排', 'Side by side') },
])
const currentScale = computed(() => scales.value[mode.value === 'depth' ? 1 : mode.value === 'rgb' ? 0 : active.value])
const zoomOptions = computed(() => [...new Set([25, 50, 75, 100, 150, 200, Math.round(currentScale.value * 100)])].sort((a, b) => a - b).map(value => ({ value: String(value), label: `${value}%` })))
function setZoom(value: string | number | boolean | null) {
  const next = Number(value) / 100
  if (!Number.isFinite(next)) return
  const which = mode.value === 'depth' ? 1 : mode.value === 'rgb' ? 0 : active.value
  scales.value = scales.value.map((v, i) => linked.value || i === which ? Math.min(8, Math.max(0.25, next)) : v) as [number, number]
}
const annotationLayers = computed(() => [
  { value: true, label: l('真值', 'Ground truth') },
  { value: false, label: l('原图', 'Image') },
])
const predictionLayers = computed(() => [{ value: 'unloaded', label: l('未载入', 'Not loaded') }])
const mask = ref(''),
  depth = ref(''),
  reading = ref(''),
  error = ref('')
let values: Uint16Array | undefined, controller: AbortController | undefined
function wheelZoom(plane: number, event: WheelEvent) {
  active.value = plane
  zoom(event.deltaY < 0 ? 1.25 : 0.8)
}
function zoom(factor: number) {
  const which =
    mode.value === 'depth' ? 1 : mode.value === 'rgb' ? 0 : active.value
  scales.value = scales.value.map((v, i) =>
    linked.value || i === which ? Math.min(8, Math.max(0.25, v * factor)) : v,
  ) as [number, number]
}
function frameStyle(i: number, ratio: number) {
  return { width: `calc(min(100%, ${54 * ratio}vh) * ${scales.value[i]})` }
}
function inspect(e: PointerEvent) {
  const dims = props.media.depth_size
  if (!dims || !values) return
  const rect = (e.target as HTMLImageElement).getBoundingClientRect()
  const x = Math.min(
      dims[0] - 1,
      Math.max(0, Math.floor(((e.clientX - rect.left) * dims[0]) / rect.width)),
    ),
    y = Math.min(
      dims[1] - 1,
      Math.max(0, Math.floor(((e.clientY - rect.top) * dims[1]) / rect.height)),
    )
  const raw = values[y * dims[0] + x]
  reading.value =
    `(${x}, ${y}) · ` +
    (raw === props.media.invalid
      ? l('无效', 'Invalid')
      : `${Number((raw! * props.media.scale!).toPrecision(7))} ${props.media.unit}`)
}
function reset() {
  controller?.abort()
  for (const v of [mask, depth]) {
    if (v.value) URL.revokeObjectURL(v.value)
    v.value = ''
  }
  values = undefined
}
async function load() {
  reset()
  error.value = ''
  const signal = (controller = new AbortController()).signal
  try {
    if (props.media.kind === 'rgbd') {
      const [img, raw] = await Promise.all(
        ['depth-preview', 'depth-values'].map((k) =>
          readSampleAsset(props.dataset, props.sample, k, signal),
        ),
      )
      const bytes = await raw!.arrayBuffer()
      if (signal.aborted) return
      const dims = props.media.depth_size!
      if (bytes.byteLength !== 2 * dims[0] * dims[1])
        throw Error(l('深度尺寸不匹配', 'Depth dimensions mismatch'))
      values = new Uint16Array(bytes)
      depth.value = URL.createObjectURL(img!)
    } else if (props.media.assets.includes('mask')) {
      const b = await readSampleAsset(
        props.dataset,
        props.sample,
        'mask-preview',
        signal,
      )
      if (!signal.aborted) mask.value = URL.createObjectURL(b)
    }
  } catch (e) {
    if (!signal.aborted) error.value = String(e)
  }
}
const shell = ref<HTMLElement>()
onMounted(() => {
  shell.value?.focus({ preventScroll: true })
  void load()
})
onBeforeUnmount(reset)
</script>
<style scoped>
.media-viewer {
  display: grid;
  min-width: 0;
  gap: 14px;
}
.media-viewer--info-open :deep(.cloud-sample),
.media-viewer--info-open .media-planes,
.media-viewer--info-open .media-footer { width: max(80px, calc(100% - min(520px, 50vw))); }
.media-toolbar,
.media-footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px 20px;
}
.media-toolbar {
  padding: 12px;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
}
.media-toolbar label {
  white-space: nowrap;
}
.media-layer { display: flex; align-items: center; gap: 8px; }
.media-toolbar .ui-select {
  width: 100px;
}
.media-planes {
  display: grid;
  gap: 12px;
  min-width: 0;
}
.media-planes.pair {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.media-plane {
  position: relative;
  min-width: 0;
  height: 57vh;
  overflow: auto;
  align-content: safe center;
  background: var(--am-surface-soft);
  border-radius: var(--am-radius-md);
}
.media-plane-label { position: absolute; z-index: 1; top: 8px; left: 8px; padding: 4px 8px; border-radius: var(--am-radius-sm); background: rgba(0, 0, 0, .7); color: white; font-size: 12px; }
.media-frame {
  position: relative;
  margin-inline: auto;
}
.media-frame img {
  width: 100%;
  display: block;
}
.media-frame .overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.pin {
  position: absolute;
  transform: translate(-50%, -50%);
  background: #252931;
  color: white;
  padding: 1px 3px;
  border-radius: 3px;
  font-size: 11px;
}
.media-footer {
  color: var(--am-text-muted);
}
.depth-scale:before {
  content: '';
  display: inline-block;
  width: 60px;
  height: 6px;
  margin-right: 6px;
  background: linear-gradient(90deg, blue, yellow, red);
}
.media-strip {
  display: flex;
  align-items: center;
  gap: 8px;
}
.media-strip button {
  border: 2px solid transparent;
  border-radius: var(--am-radius-md);
  overflow: hidden;
  padding: 0;
  width: min(12%, 88px);
  cursor: pointer;
}
.media-strip button[aria-current='true'] {
  border-color: var(--am-brand-primary);
}
.media-strip :deep(.dataset-sample-image) {
  height: 54px;
}
.media-viewer:focus {
  outline: none;
}
</style>
