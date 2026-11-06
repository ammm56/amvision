<template>
  <div class="dataset-sample-image" :aria-busy="loading">
    <canvas
      v-show="!error"
      ref="canvas"
      role="img"
      :aria-label="sample.file_name"
    />
    <div v-if="error" class="dataset-image-error">
      <ImageOff :size="24" /><span>{{ text('failedImage') }}</span
      ><Button size="sm" @click.stop="load">{{ text('retry') }}</Button>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useResizeObserver } from '@vueuse/core'
import { ImageOff } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import {
  getDatasetImage,
  type DatasetSample,
} from '../services/dataset-workspace.service'
import { annotationBounds, paintAnnotations } from '../annotations'
import { useDatasetText } from '../dataset-workspace'
const props = defineProps<{
  datasetId: string
  sample: DatasetSample
  categories: { category_id: number; name: string }[]
  showAnnotations: boolean
  selectedObject?: string
  poseSchemas?: Record<string, unknown>
  cropObject?: string
}>()
const text = useDatasetText(),
  canvas = ref<HTMLCanvasElement | null>(null),
  loading = ref(false),
  error = ref(false),
  labels = computed(
    () => new Map(props.categories.map((c) => [c.category_id, c.name])),
  )
let bitmap: ImageBitmap | undefined,
  controller: AbortController | undefined,
  generation = 0
async function load() {
  controller?.abort()
  controller = new AbortController()
  const request = ++generation
  loading.value = true
  error.value = false
  try {
    const blob = await getDatasetImage(
      props.datasetId,
      props.sample.dataset_version_id,
      props.sample.sample_id,
      true,
      controller.signal,
    )
    const next = await createImageBitmap(blob, { imageOrientation: 'none' })
    if (request !== generation) {
      next.close()
      return
    }
    bitmap?.close()
    bitmap = next
    draw()
  } catch (e) {
    if (
      request === generation &&
      !(e instanceof DOMException && e.name === 'AbortError')
    )
      error.value = true
  } finally {
    if (request === generation) loading.value = false
  }
}
function draw() {
  const target = canvas.value
  if (!target || !bitmap) return
  const width = target.clientWidth || 320,
    height = target.clientHeight || 188
  const annotation = props.sample.annotations.find(item => item.annotation_id === props.cropObject)
  const box = annotation ? annotationBounds(annotation) : null
  const sourceWidth = props.sample.width, sourceHeight = props.sample.height
  const padding = box ? Math.max(box[2], box[3]) * .12 : 0
  const x = box ? Math.max(0, box[0] - padding) : 0, y = box ? Math.max(0, box[1] - padding) : 0
  const cropWidth = box ? Math.min(sourceWidth, box[0] + box[2] + padding) - x : sourceWidth
  const cropHeight = box ? Math.min(sourceHeight, box[1] + box[3] + padding) - y : sourceHeight
  if (cropWidth <= 0 || cropHeight <= 0) return
  const ratio = Math.min(width / cropWidth, height / cropHeight)
  target.width = Math.max(1, Math.round(cropWidth * ratio))
  target.height = Math.max(1, Math.round(cropHeight * ratio))
  const ctx = target.getContext('2d')
  if (!ctx) return
  ctx.drawImage(bitmap, x * bitmap.width / sourceWidth, y * bitmap.height / sourceHeight, cropWidth * bitmap.width / sourceWidth, cropHeight * bitmap.height / sourceHeight, 0, 0, target.width, target.height)
  ctx.save()
  ctx.translate(-x * ratio, -y * ratio)
  if (props.showAnnotations)
    paintAnnotations(
      ctx,
      annotation ? { ...props.sample, annotations: [annotation] } : props.sample,
      labels.value,
      sourceWidth * ratio,
      sourceHeight * ratio,
      props.selectedObject,
      1,
      props.poseSchemas,
    )
  ctx.restore()
}
useResizeObserver(canvas, draw)
watch(
  () => [
    props.datasetId,
    props.sample.dataset_version_id,
    props.sample.sample_id,
  ],
  load,
  { immediate: true },
)
watch(
  () => [
    props.showAnnotations,
    props.selectedObject,
    props.cropObject,
    props.categories,
    props.sample,
    canvas.value,
  ],
  draw,
  { flush: 'post' },
)
onBeforeUnmount(() => {
  generation++
  controller?.abort()
  bitmap?.close()
})
</script>
<style scoped>
.dataset-sample-image {
  height: 188px;
  background: var(--am-surface-muted);
  display: flex;
  justify-content: center;
  align-items: center;
  overflow: hidden;
}
.dataset-sample-image canvas {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.dataset-image-error {
  display: grid;
  justify-items: center;
  gap: 6px;
  color: var(--am-text-muted);
  font-size: 12px;
}
</style>
