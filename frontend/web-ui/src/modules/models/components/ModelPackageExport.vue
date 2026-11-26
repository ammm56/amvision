<template>
  <section class="package-export">
    <h2>{{ zh ? '导出模型包' : 'Export model package' }}</h2>
    <div class="package-export__source"><Package :size="22" /><div><strong>{{ name }}</strong><span>{{ modelTaskLabel(taskType, zh) }} · {{ modelVersionDisplayName(version) }}</span></div></div>
    <template v-if="!record">
      <h3>{{ zh ? '选择模型产物' : 'Select artifacts' }}</h3>
      <div class="resource-table">
        <table>
          <thead><tr><th scope="col">{{ zh ? '选择' : 'Select' }}</th><th scope="col">{{ zh ? '文件格式' : 'Format' }}</th><th scope="col">{{ zh ? '精度' : 'Precision' }}</th></tr></thead>
          <tbody>
            <tr v-if="hasCheckpoint"><td><input v-model="checkpoint" type="checkbox" aria-label="PyTorch" /></td><td>PyTorch</td><td>FP32</td></tr>
            <tr v-for="build in builds" :key="build.model_build_id">
              <td><input v-model="selected" type="checkbox" :value="build.model_build_id" :aria-label="`${conversionFormatName(build.build_format, zh)} ${build.runtime_precision.toUpperCase()}`" /></td><td>{{ conversionFormatName(build.build_format, zh) }}</td><td>{{ build.runtime_precision.toUpperCase() }}</td>
            </tr>
            <tr v-if="!hasCheckpoint && !builds.length"><td colspan="3">{{ zh ? '暂无可导出的模型文件' : 'No artifacts are available for export' }}</td></tr>
          </tbody>
        </table>
      </div>
      <section class="package-export__metadata" aria-labelledby="package-export-metadata">
        <h3 id="package-export-metadata">{{ zh ? '包含的元数据' : 'Included metadata' }}</h3>
        <dl>
          <div v-for="item in metadataItems" :key="item.label">
            <dt><component :is="item.icon" :size="16" aria-hidden="true" />{{ item.label }}</dt>
            <dd>{{ item.value }}</dd>
          </div>
        </dl>
      </section>
      <label class="field"><span>{{ zh ? '输出文件' : 'Output file' }}</span><input v-model.trim="fileName" /></label>
      <footer><Button @click="$emit('back')">{{ zh ? '返回' : 'Back' }}</Button><Button variant="primary" :loading="busy" :disabled="!fileName.toLowerCase().endsWith('.zip') || (!checkpoint && !selected.length)" @click="start">{{ zh ? '生成模型包' : 'Generate package' }}</Button></footer>
    </template>
    <ModelPackageExportResult v-else :record="record" :zh="zh" :busy="busy" :checking="checking" :actions-blocked="!!recordError" :close-label="zh ? '关闭' : 'Close'"
      @close="$emit('back')" @download="download" @regenerate="start" />
    <InlineError :message="error" />
    <div v-if="recordError" class="package-export__read-error">
      <InlineError :message="recordError" />
      <Button size="sm" :loading="checking" @click="retryStatus">{{ zh ? '重试读取状态' : 'Retry reading status' }}</Button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { conversionFormatName } from '../conversion-task-presentation'
import { modelVersionDisplayName } from '../model-display-name'
import { modelTaskLabel } from '../model-evaluation-types'
import { FileText, Package, Scan, ShieldCheck, SlidersHorizontal } from '@lucide/vue'
import { computed, onBeforeUnmount, ref } from 'vue'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { ApiError } from '@/shared/api/error'
import type { PlatformBaseModelBuild, PlatformBaseModelVersionDetail } from '../services/model.service'
import { canDownloadModelPackage, downloadModelPackage, exportModelPackage, getModelPackage, packagePending, type ModelPackageRecord } from '../services/model-package.service'
import ModelPackageExportResult from './ModelPackageExportResult.vue'

const props = defineProps<{
  projectId: string
  name: string
  taskType: string
  version: PlatformBaseModelVersionDetail
  builds: PlatformBaseModelBuild[]
  zh: boolean
}>()
defineEmits<{ back: [] }>()
const hasCheckpoint = computed(() => props.version.files.some(file => /\.(pt|pth)$/i.test(file.storage_uri)))
const metadataItems = computed(() => {
  const categories = props.version.metadata.category_names
  const size = props.version.metadata.input_size
  const { width, height } = size && typeof size === 'object' ? size as Record<string, unknown> : {}
  const inputSize = typeof width === 'number' && typeof height === 'number' ? `${width} × ${height}` : ''
  return [
    { icon: FileText, label: props.zh ? '类别顺序' : 'Class order',
      value: Array.isArray(categories) ? (props.zh ? `共 ${categories.length} 类` : `${categories.length} classes`) : '—' },
    { icon: Scan, label: props.zh ? '输入输出' : 'Inputs and outputs',
      value: inputSize ? (props.zh ? `输入尺寸 ${inputSize}` : `Input size ${inputSize}`) : '—' },
    { icon: SlidersHorizontal, label: props.zh ? '前后处理配置' : 'Preprocessing and postprocessing',
      value: props.zh ? '图像预处理、后处理参数' : 'Image preprocessing and postprocessing parameters' },
    { icon: ShieldCheck, label: props.zh ? '文件校验' : 'File checksums', value: 'SHA-256' },
  ]
})
const checkpoint = ref(hasCheckpoint.value)
const selected = ref<string[]>([])
const versionLabel = modelVersionDisplayName(props.version)
const fileName = ref(`${props.name.replace(/[<>:"/\\|?*]/g, '_').slice(0, 84)}${versionLabel === '—' ? '' : `-${versionLabel}`}.zip`)
const record = ref<ModelPackageRecord | null>(null)
const error = ref('')
const recordError = ref('')
const checking = ref(false)
const busy = ref(false)
let disposed = false
let timer: ReturnType<typeof setTimeout>

async function refresh(id: string): Promise<void> {
  if (checking.value || disposed || record.value?.operation_id !== id) return
  checking.value = true
  let poll = true
  try {
    const data = await getModelPackage(props.projectId, id)
    if (disposed) return
    record.value = data
    recordError.value = ''
  } catch (cause) {
    if (!disposed) {
      recordError.value = cause instanceof Error ? cause.message : String(cause)
      poll = !(cause instanceof ApiError && [401, 403, 404].includes(cause.status))
    }
  } finally {
    checking.value = false
  }
  if (poll && !disposed && record.value && packagePending(record.value.state)) timer = setTimeout(() => void refresh(id), 1800)
}

function retryStatus(): void {
  if (!record.value) return
  clearTimeout(timer)
  void refresh(record.value.operation_id)
}

async function start(): Promise<void> {
  if (busy.value || checking.value || recordError.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await exportModelPackage(props.projectId, record.value?.export_options ?? {
      model_version_id: props.version.model_version_id, include_checkpoint: checkpoint.value,
      build_ids: selected.value, file_name: fileName.value,
    })
    if (!disposed) {
      record.value = result
      void refresh(result.operation_id)
    }
  } catch (cause) {
    if (!disposed) error.value = cause instanceof Error ? cause.message : String(cause)
  } finally { busy.value = false }
}

async function download(): Promise<void> {
  const row = record.value
  if (!row || !canDownloadModelPackage(row) || busy.value || checking.value || recordError.value) return
  busy.value = true
  error.value = ''
  try { await downloadModelPackage(props.projectId, row) }
  catch (cause) {
    if (disposed) return
    await refresh(row.operation_id)
    if (!disposed && record.value && canDownloadModelPackage(record.value)) error.value = cause instanceof Error ? cause.message : String(cause)
  }
  finally { busy.value = false }
}

onBeforeUnmount(() => { disposed = true; clearTimeout(timer) })
</script>

<style scoped>
.package-export { display:grid; gap:14px; }
.package-export :is(h2,h3,p) { margin:0; }
.package-export__source { display:flex; align-items:center; gap:12px; padding:12px; border:1px solid var(--am-border); border-radius:6px; background:var(--am-surface-soft); }
.package-export__source span { display:block; color:var(--am-text-muted); overflow-wrap:anywhere; }
.package-export__metadata { display:grid; gap:10px; min-width:0; }
.package-export__metadata dl { margin:0; border:1px solid var(--am-border); border-radius:6px; }
.package-export__metadata dl > div { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:4px 16px; padding:8px 12px; }
.package-export__metadata dl > div + div { border-block-start:1px solid var(--am-border); }
.package-export__metadata dt { display:flex; align-items:center; gap:10px; font-weight:600; }
.package-export__metadata dt svg { flex:none; color:var(--am-text-muted); }
.package-export__metadata dd { margin:0; margin-inline-start:auto; color:var(--am-text-muted); text-align:end; overflow-wrap:anywhere; }
.package-export footer { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:10px; }
.package-export__read-error { display:flex; align-items:center; flex-wrap:wrap; gap:8px; min-width:0; overflow-wrap:anywhere; }
</style>
