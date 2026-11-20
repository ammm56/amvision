<template>
  <ConfirmDialog :title="zh ? '样本预览' : 'Sample preview'" :details="sample.name" :show-confirm="false" confirm-label="" :cancel-label="zh ? '关闭' : 'Close'" size="wide" scroll-body @cancel="emit('close')">
    <div class="failed-sample-notice" role="status">
      <TriangleAlert :size="18" aria-hidden="true" />
      <div><strong>{{ reason }}</strong><p>{{ advice }}</p></div>
    </div>
    <div class="failed-sample-media" :aria-busy="loading">
      <img v-if="imageUrl && !unavailable" :key="imageUrl" :src="imageUrl" :alt="sample.name" @load="loading = false" @error="imageFailed" />
      <p v-if="loading" role="status">{{ zh ? '正在读取原图…' : 'Loading original image…' }}</p>
      <div v-else-if="unavailable" class="failed-sample-placeholder">
        <ImageOff :size="30" aria-hidden="true" />
        <p>{{ zh ? '无法预览原图' : 'Original image unavailable' }}</p>
        <Button size="sm" @click="revision++"><RefreshCw :size="15" />{{ zh ? '重试读取' : 'Retry image' }}</Button>
      </div>
    </div>
    <p v-if="sample.classes.length" class="failed-sample-classes">{{ zh ? '报告记录的类别：' : 'Classes in report: ' }}{{ sample.classes.join(zh ? '、' : ', ') }}</p>
    <template #leading-actions>
      <div class="failed-sample-links">
        <Button size="sm" @click="emit('showError')">{{ sample.reason === 'invalid_annotation' ? (zh ? '查看标注问题' : 'View annotation issue') : (zh ? '查看错误' : 'View error') }}</Button>
        <RouterLink v-if="datasetLink" :to="datasetLink">{{ zh ? '在数据集中查看' : 'View in dataset' }}</RouterLink>
      </div>
    </template>
  </ConfirmDialog>
</template>

<script setup lang="ts">
import { ImageOff, RefreshCw, TriangleAlert } from '@lucide/vue'
import { ref, watch } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import { getDatasetExportDetail } from '@/modules/datasets/services/dataset.service'
import { fetchDetectionEvaluationImage, type FailedDetectionSample } from '../services/model-evaluation.service'

const props = defineProps<{ taskId: string; datasetExportId?: string; sample: FailedDetectionSample; reason: string; advice: string; zh: boolean }>()
const emit = defineEmits<{ close: []; showError: [] }>()
const revision = ref(0)
const imageUrl = ref('')
const loading = ref(true)
const unavailable = ref(false)
const datasetLink = ref<RouteLocationRaw>()

function imageFailed() {
  loading.value = false
  unavailable.value = true
}

watch([() => props.taskId, () => props.sample.image_index, revision], async ([id, index], _, onCleanup) => {
  const request = new AbortController()
  let url: string | undefined
  onCleanup(() => {
    request.abort()
    if (url) URL.revokeObjectURL(url)
  })
  imageUrl.value = ''
  loading.value = true
  unavailable.value = false
  try {
    const image = await fetchDetectionEvaluationImage(id, index, request.signal)
    if (request.signal.aborted) return
    url = URL.createObjectURL(image)
    imageUrl.value = url
  } catch {
    if (!request.signal.aborted) imageFailed()
  }
}, { immediate: true })

watch(() => props.datasetExportId, async (id, _, onCleanup) => {
  let active = true
  onCleanup(() => { active = false })
  datasetLink.value = undefined
  if (!id) return
  try {
    const source = await getDatasetExportDetail(id)
    if (active && source.dataset_id && source.dataset_version_id) {
      datasetLink.value = {
        path: `/datasets/${encodeURIComponent(source.dataset_id)}/versions/${encodeURIComponent(source.dataset_version_id)}`,
        query: props.sample.name ? { q: props.sample.name } : {},
      }
    }
  } catch {
    // 旧评估使用的导出可能已清理，仍可查看报告中的错误。
  }
}, { immediate: true })
</script>

<style scoped>
.failed-sample-notice { display:flex; align-items:flex-start; gap:10px; padding:12px; border-radius:6px; border:1px solid var(--am-warning-border); background:var(--am-warning-surface); color:var(--am-warning-text); }
.failed-sample-notice svg { flex:none; }
.failed-sample-notice p, .failed-sample-placeholder p { margin:4px 0 0; }
.failed-sample-media { position:relative; display:grid; place-items:center; min-height:min(216px,30dvh); margin-top:12px; border:1px solid var(--am-border); border-radius:6px; overflow:hidden; }
.failed-sample-media img { display:block; max-width:100%; max-height:min(380px,44dvh); object-fit:contain; }
.failed-sample-media[aria-busy='true'] img { position:absolute; visibility:hidden; }
.failed-sample-placeholder { display:grid; justify-items:center; gap:8px; padding:16px; color:var(--am-text-secondary); }
.failed-sample-classes { margin:12px 0 0; overflow-wrap:anywhere; }
.failed-sample-links { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; }
</style>
