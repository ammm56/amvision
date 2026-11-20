<script setup lang="ts">
import { useIntersectionObserver } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { fetchDetectionEvaluationImage, type EvaluationBox } from '../services/model-evaluation.service'

const props = defineProps<{
  taskId: string
  index: number
  boxes: Array<{ box: EvaluationBox; kind: 'ground-truth' | 'prediction' }>
}>()
const target = ref<HTMLElement | null>(null)
const visible = ref(false)
const imageUrl = ref('')
const size = ref<{ width: number; height: number }>()
const frameWidth = computed(() => size.value ? `${Math.min(136, 76 * size.value.width / size.value.height)}px` : '88px')

const observer = useIntersectionObserver(target, ([entry]) => {
  if (entry?.isIntersecting) {
    visible.value = true
    observer.stop()
  }
}, { rootMargin: '96px' })
if (!observer.isSupported.value) visible.value = true

watch([() => props.taskId, () => props.index, visible], ([taskId, index, load], _, onCleanup) => {
  imageUrl.value = ''
  size.value = undefined
  if (!load) return
  const request = new AbortController()
  let url = ''
  onCleanup(() => {
    request.abort()
    if (url) URL.revokeObjectURL(url)
  })
  void fetchDetectionEvaluationImage(taskId, index, request.signal).then(blob => {
    if (request.signal.aborted) return
    url = URL.createObjectURL(blob)
    imageUrl.value = url
  }).catch(() => { /* The full preview offers a retry when the image is unavailable. */ })
}, { immediate: true })

function readSize(event: Event): void {
  const image = event.target as HTMLImageElement
  size.value = { width: image.naturalWidth, height: image.naturalHeight }
}
function boxStyle(box: EvaluationBox) {
  const [left, top, right, bottom] = box.bbox_xyxy
  const { width, height } = size.value!
  return { left: `${left / width * 100}%`, top: `${top / height * 100}%`, width: `${(right - left) / width * 100}%`, height: `${(bottom - top) / height * 100}%` }
}
</script>

<template>
  <div ref="target" class="sample-thumb" aria-hidden="true">
    <div v-if="imageUrl" class="sample-thumb__frame" :style="{ width: frameWidth }">
      <img :src="imageUrl" alt="" @load="readSize" @error="imageUrl = ''" />
      <template v-if="size">
        <span v-for="(item, index) in boxes" :key="index" :class="item.kind" :style="boxStyle(item.box)" />
      </template>
    </div>
    <span v-else>—</span>
  </div>
</template>

<style scoped>
.sample-thumb { display: flex; align-items: center; min-height: 76px; min-width: 0; color: var(--muted); }
.sample-thumb__frame { position: relative; max-width: 100%; overflow: hidden; border-radius: 4px; }
.sample-thumb__frame img { display: block; width: 100%; height: auto; }
.sample-thumb__frame span { position: absolute; box-sizing: border-box; border: 1px dashed #f79235; }
.sample-thumb__frame span.ground-truth { border: 1px solid var(--am-brand-primary); }
</style>
