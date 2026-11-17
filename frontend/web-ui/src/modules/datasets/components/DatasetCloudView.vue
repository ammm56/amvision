<template>
  <div class="cloud-sample">
    <div class="dataset-actions">
      <Button :disabled="!ready" @click="scene?.fit('iso')">{{
        l('适配', 'Fit')
      }}</Button>
      <Button :disabled="!ready" @click="scene?.fit('y')">{{
        l('正视', 'Front')
      }}</Button>
      <Button :disabled="!ready" @click="scene?.fit('z')">{{
        l('俯视', 'Top')
      }}</Button>
      <label
        ><input
          type="checkbox"
          v-model="ortho"
          :disabled="!ready"
          @change="scene?.projection(ortho)"
        />
        {{ l('正交', 'Orthographic') }}</label
      >
      <label
        >{{ l('点大小', 'Point size') }}
        <input
          type="range"
          min="1"
          max="8"
          v-model.number="size"
          :disabled="!ready"
          @input="scene?.pointSize(size)"
      /></label>
      <label
        >{{ l('着色', 'Color') }}
        <select v-model="color" @change="applyColor" :disabled="!ready">
          <option value="height">{{ l('高度', 'Height') }}</option>
          <option value="original">
            {{ media.has_color ? 'RGB' : l('单色', 'Single color') }}
          </option>
        </select></label
      >
    </div>
    <InlineError v-if="error" :message="error" /><Button
      v-if="error"
      @click="load"
      >{{ l('重新打开', 'Retry') }}</Button
    >
    <div
      ref="host"
      class="cloud-host"
      :aria-label="l('点云视图', 'Point cloud viewport')"
    >
      <span v-if="!media.preview_count">{{
        l('无有效点', 'No valid points')
      }}</span>
      <div v-if="ready && color === 'height' && media.z_range" class="cloud-legend" :aria-label="l('高度色标', 'Height legend')">
        <span>{{ l('高度', 'Height') }}<template v-if="media.unit"> ({{ media.unit }})</template></span>
        <div class="cloud-legend__scale"><span class="cloud-legend__bar" :class="{ 'cloud-legend__bar--flat': media.z_range[0] === media.z_range[1] }" /><div><span>{{ displayNumber(media.z_range[1]) }}</span><span>{{ displayNumber(media.z_range[0]) }}</span></div></div>
      </div>
      <svg v-if="ready && orientation.length" class="cloud-orientation" viewBox="0 0 88 88" role="img" :aria-label="l('坐标轴方向', 'Coordinate axes')">
        <defs><marker v-for="(color, axis) in axisColors" :id="`dataset-cloud-axis-${axis}`" :key="axis" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" :fill="color" /></marker></defs>
        <g v-for="axis in orientation" :key="axis.label" :stroke="axisColors[axis.label]" :fill="axisColors[axis.label]">
          <line v-if="Math.hypot(axis.x, axis.y) >= 0.15" x1="44" y1="44" :x2="44 + axis.x * 27" :y2="44 + axis.y * 27" stroke-width="2" :marker-end="`url(#dataset-cloud-axis-${axis.label})`" />
          <circle v-if="Math.hypot(axis.x, axis.y) < 0.15" cx="44" cy="44" r="3" />
          <text :x="44 + axis.x * 35 + (Math.hypot(axis.x, axis.y) < 0.25 ? 9 : 0)" :y="44 + axis.y * 35 + (Math.hypot(axis.x, axis.y) < 0.25 ? 9 : 0)" text-anchor="middle" dominant-baseline="central" stroke="none">{{ axis.label }}</text>
        </g>
      </svg>
    </div>
    <p class="cloud-caption">
      {{ media.frame }} · {{ media.unit }} · {{ media.point_count?.toLocaleString() }}
      {{ l('点', 'points') }} · {{ l('有效', 'Valid') }}
      {{ media.valid_count?.toLocaleString() }} · {{ l('无效', 'Invalid') }}
      {{ media.invalid_count?.toLocaleString() }} · {{ l('显示', 'Displayed') }}
      {{ media.preview_count?.toLocaleString() }}
    </p>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { createCloudRenderer } from '@/workflows/workflow-editor/point-cloud/renderer'
import { displayNumber, type projectOrientation } from '@/workflows/workflow-editor/point-cloud/view-presentation'
import { reserveCpu } from '@/workflows/workflow-editor/point-cloud/preview-data'
import { readSampleAsset, type SampleMedia } from '../sample-media'
import type { DatasetSample } from '../services/dataset-workspace.service'
const props = defineProps<{
  dataset: string
  sample: DatasetSample
  media: SampleMedia
}>()
const { locale } = useI18n()
const l = (zh: string, en: string) => (locale.value.startsWith('zh') ? zh : en)
const host = ref<HTMLElement>(),
  error = ref(''),
  ready = ref(false),
  size = ref(2),
  ortho = ref(false),
  color = ref('height'),
  orientation = ref<ReturnType<typeof projectOrientation>>([])
const axisColors = { X: '#ff5555', Y: '#37e873', Z: '#68a4ff' } as const
let scene: ReturnType<typeof createCloudRenderer> | undefined
let controller: AbortController | undefined,
  releaseCpu: (() => void) | undefined
const policy = {
  max_points: 50000,
  max_data_bytes: 1200000,
  max_cpu_bytes: 64 * 1024 ** 2,
  max_gpu_bytes: 128 * 1024 ** 2,
  max_canvas_pixels: 8_388_608,
  max_position_error: 0.001,
}
function release() {
  controller?.abort()
  scene?.dispose()
  scene = undefined
  releaseCpu?.()
  releaseCpu = undefined
  ready.value = false
  orientation.value = []
}
function applyColor() {
  const range = props.media.z_range,
    origin = props.media.origin,
    scale = props.media.scale
  if (color.value === 'height' && range && origin && scale) {
    scene?.colors(null, 'coordinate-z', {
      min: (range[0] - origin[2]) / scale,
      max: (range[1] - origin[2]) / scale,
    })
  } else scene?.colors(null, 'original')
}
async function load() {
  release()
  error.value = ''
  const count = props.media.preview_count
  if (!count || !host.value) return
  const signal = (controller = new AbortController()).signal
  try {
    if (count > policy.max_points) throw Error('cloud_preview_capacity')
    const blob = await readSampleAsset(
      props.dataset,
      props.sample,
      'points',
      signal,
    )
    if (blob.size !== count * 24) throw Error('cloud_preview_invalid')
    const buf = await blob.arrayBuffer()
    if (signal.aborted) return
    releaseCpu = reserveCpu(buf.byteLength * 2, policy)
    const source = new Float32Array(buf),
      positions = new Float32Array(count * 3),
      colors = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      positions.set(source.subarray(i * 6, i * 6 + 3), i * 3)
      colors.set(source.subarray(i * 6 + 3, i * 6 + 6), i * 3)
    }
    scene = createCloudRenderer(
      host.value,
      {
        count,
        positions,
        colors,
        origin: [0, 0, 0],
        point(i) {
          return {
            sourceIndex: null,
            xyz: Array.from(positions.slice(i * 3, i * 3 + 3)),
            scalar: null,
          }
        },
        dispose() {},
      },
      policy,
      () => {},
      () => {
        release()
        error.value = l(
          '三维视图已中断，请重新打开',
          '3D view interrupted. Try again.',
        )
      },
      () => {},
      true,
      { range: null, coordinateColor: false, scaleChanged: () => {}, orientationChanged: axes => { orientation.value = axes } },
    )
    scene.fit('iso')
    scene.projection(ortho.value)
    scene.pointSize(size.value)
    applyColor()
    ready.value = true
  } catch (e) {
    if (signal.aborted) return
    release()
    error.value =
      l('点云预览不可用', 'Point cloud preview unavailable') +
      ' · ' +
      String(e instanceof Error ? e.message : e)
  }
}
onMounted(load)
onBeforeUnmount(release)
</script>
<style scoped>
.cloud-sample {
  display: grid;
  gap: 12px;
  min-width: 0;
}
.cloud-host {
  height: clamp(300px, 58vh, 760px);
  position: relative;
  overflow: hidden;
  border-radius: var(--am-radius-md);
  background: #303337;
  color: #eee;
}
.cloud-host > span {
  position: absolute;
  inset: 45% 0;
  text-align: center;
}
.cloud-legend { position:absolute; z-index:1; top:14px; right:16px; display:grid; gap:8px; color:#fff; font-size:12px; text-shadow:0 1px 3px #000; pointer-events:none; }
.cloud-legend__scale { display:flex; align-items:stretch; gap:7px; }
.cloud-legend__bar { width:14px; height:110px; background:linear-gradient(to top, blue 0%, cyan 25%, lime 50%, yellow 75%, red 100%); }
.cloud-legend__bar--flat { background:lime; }
.cloud-legend__scale > div { display:flex; flex-direction:column; justify-content:space-between; }
.cloud-orientation { position:absolute; z-index:1; left:12px; bottom:12px; width:88px; height:88px; overflow:visible; pointer-events:none; font-size:12px; font-weight:600; filter:drop-shadow(0 1px 2px #000); }
.cloud-caption {
  color: var(--am-text-muted);
  margin: 0;
}
.dataset-actions {
  flex-wrap: wrap;
}
.dataset-actions label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.dataset-actions input[type='range'] {
  width: 70px;
}
</style>
