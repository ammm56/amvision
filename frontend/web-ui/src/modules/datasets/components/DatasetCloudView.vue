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
    </div>
    <p class="cloud-caption">
      {{ media.frame }} · {{ media.unit }} · {{ media.point_count?.toLocaleString() }}
      {{ l('点', 'points') }} · {{ l('有效', 'Valid') }}
      {{ media.valid_count?.toLocaleString() }} · {{ l('无效', 'Invalid') }}
      {{ media.invalid_count?.toLocaleString() }} · {{ l('显示', 'Displayed') }}
      {{ media.preview_count?.toLocaleString() }}
      <span class="height-scale" v-if="color === 'height' && media.z_range">
        Z {{ media.z_range.join(' – ') }} {{ media.unit }}</span
      >
    </p>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { createCloudRenderer } from '@/workflows/workflow-editor/point-cloud/renderer'
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
  color = ref('height')
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
    )
    scene.fit('iso')
    scene.axesVisible(true)
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
.cloud-caption {
  color: var(--am-text-muted);
  margin: 0;
}
.cloud-caption span {
  margin-inline-start: 12px;
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
.height-scale::before {content:"";display:inline-block;width:64px;height:6px;margin-right:6px;background:linear-gradient(90deg,blue,cyan,lime,yellow,red)}
</style>
