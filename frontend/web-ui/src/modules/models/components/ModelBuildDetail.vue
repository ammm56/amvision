<template>
  <section class="model-build-detail">
    <Button v-if="!footerActions" variant="ghost" size="sm" @click="$emit('back')"><ArrowLeft :size="15" />{{ zh ? '返回版本' : 'Back to version' }}</Button>
    <h2>{{ build ? `${formatName(build.build_format)} (${build.runtime_precision.toUpperCase()})` : (zh ? '原始模型文件' : 'Original model files') }}</h2>
    <p class="model-build-detail__subtitle">{{ modelName }} · {{ modelVersionDisplayName(version) }}</p>
    <h3>{{ zh ? '基本信息' : 'Information' }}</h3>
    <dl class="model-build-detail__information">
      <div v-if="singleFile"><dt>{{ zh ? '文件名称' : 'File name' }}</dt><dd>{{ files[0].name }}</dd></div>
      <div><dt>{{ zh ? '文件格式' : 'Format' }}</dt><dd>{{ build ? formatName(build.build_format) : (version.files.map(file => file.file_type).join(' / ') || '—') }}</dd></div>
      <div><dt>{{ zh ? '精度' : 'Precision' }}</dt><dd>{{ build?.runtime_precision.toUpperCase() || '—' }}</dd></div>
      <div><dt>{{ zh ? '数值校验' : 'Numerical validation' }}</dt>
        <dd class="model-build-detail__line" :class="validation?.tone"><CircleCheck v-if="validation?.tone === 'success'" :size="16" aria-hidden="true" />{{ validation?.label ?? (zh ? '未记录' : 'Not recorded') }}</dd>
      </div>
      <div v-if="!files.length"><dt>{{ zh ? '文件状态' : 'File status' }}</dt><dd>{{ zh ? '暂无文件记录' : 'No file records' }}</dd></div>
      <template v-for="file in files" :key="file.key">
        <div class="model-build-detail__file"><dt>{{ zh ? '文件状态' : 'File status' }}</dt><dd>
          <span v-if="files.length > 1" class="model-build-detail__filename">{{ file.name }}</span>
          <span class="model-build-detail__line" :class="fileStates[file.key]?.state">
            <CircleCheck v-if="fileStates[file.key]?.state === 'present'" :size="16" aria-hidden="true" />
            <CircleAlert v-else-if="fileStates[file.key]" :size="16" aria-hidden="true" />
            {{ statusText(file.key) }}
            <Button v-if="fileStates[file.key] && fileStates[file.key].state !== 'present'" variant="ghost" size="sm" @click="checkFiles">{{ zh ? '重试' : 'Retry' }}</Button>
            <Button v-if="fileStates[file.key]?.state === 'present' && (!footerActions || files.length > 1)" variant="ghost" size="sm" :loading="downloading === file.key" :disabled="!!downloading" @click="downloadFile(file)"><Download :size="14" />{{ zh ? '下载' : 'Download' }}</Button>
          </span>
        </dd></div>
        <div><dt>{{ zh ? '相对路径' : 'Relative path' }}</dt><dd class="model-build-detail__line model-build-detail__path">
          <span>{{ file.path }}</span>
          <Button variant="ghost" size="sm" icon-only :aria-label="zh ? '复制文件路径' : 'Copy file path'" @click="copyPath(file.path)"><Copy :size="14" /></Button>
        </dd></div>
        <div><dt>SHA256</dt><dd>
          <details v-if="fileStates[file.key]?.state === 'present'" @toggle="($event.target as HTMLDetailsElement).open && loadChecksum(file)">
            <summary>{{ zh ? '查看 SHA256' : 'View SHA256' }}</summary>
            <code v-if="checksums[file.key] && checksums[file.key] !== 'failed'">{{ checksums[file.key] }}</code>
            <span v-else-if="checksums[file.key] === 'failed'" role="status">{{ zh ? '读取失败' : 'Could not read hash' }} <Button variant="ghost" size="sm" @click="loadChecksum(file)">{{ zh ? '重试' : 'Retry' }}</Button></span>
            <span v-else role="status">{{ zh ? '正在读取…' : 'Reading…' }}</span>
          </details>
          <span v-else>—</span>
        </dd></div>
      </template>
    </dl>
    <p v-if="!requiredFilesKnown" class="model-build-detail__error" role="status">{{ zh ? '缺少 OpenVINO XML 或 BIN 文件记录。' : 'The OpenVINO XML or BIN file record is missing.' }}</p>
    <p v-if="files.length" class="model-build-detail__note">{{ zh ? '部署时按目标环境检查兼容性。' : 'Deployment checks compatibility against the target environment.' }}</p>
    <p v-if="copyMessage" class="model-build-detail__note" role="status">{{ copyMessage }}</p>
    <p v-if="downloadError" role="alert" class="model-build-detail__error">{{ zh ? '下载失败，请检查文件后重试。' : 'Download failed. Check the file and retry.' }}</p>
    <h3>{{ zh ? '模型输入输出' : 'Model inputs and outputs' }}</h3>
    <div class="model-build-detail__io">
      <section><h4>{{ zh ? '输入' : 'Input' }}</h4><div class="resource-table"><table>
        <thead><tr><th scope="col">{{ zh ? '名称' : 'Name' }}</th><th scope="col">{{ zh ? '数据类型' : 'Type' }}</th><th scope="col">{{ zh ? '布局' : 'Layout' }}</th><th scope="col">{{ zh ? '形状' : 'Shape' }}</th></tr></thead>
        <tbody><tr><td>{{ inputNames }}</td><td>{{ inputDtype }}</td><td>{{ inputLayout }}</td><td>{{ inputShape }}</td></tr></tbody>
      </table></div></section>
      <section><h4>{{ zh ? '输出' : 'Output' }}</h4><div class="resource-table"><table>
        <thead><tr><th scope="col">{{ zh ? '名称' : 'Name' }}</th><th scope="col">{{ zh ? '说明' : 'Description' }}</th></tr></thead>
        <tbody><tr><td>{{ outputNames }}</td><td>{{ outputNames !== '—' && postprocess ? (zh ? '按后处理契约解析' : 'Apply the postprocessing contract') : '—' }}</td></tr></tbody>
      </table></div></section>
    </div>
    <div class="model-build-detail__contracts">
      <section><h3>{{ zh ? '类别信息' : 'Classes' }}</h3><p v-if="!categories.length">{{ zh ? '暂无类别信息' : 'No class information' }}</p><div v-else class="resource-table"><table><thead><tr><th scope="col">ID</th><th scope="col">{{ zh ? '类别名称' : 'Class name' }}</th></tr></thead><tbody><tr v-for="category in categories" :key="category.id"><td>{{ category.id }}</td><td>{{ category.name }}</td></tr></tbody></table></div></section>
      <section><h3>{{ zh ? '预处理与后处理' : 'Preprocessing and postprocessing' }}</h3><dl><div v-for="entry in contractEntries" :key="entry.label"><dt>{{ entry.label }}</dt><dd>{{ entry.value }}</dd></div></dl><p v-if="!contractEntries.length">{{ zh ? '暂无契约信息' : 'No contract information' }}</p></section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { modelBuildValidation, saveProjectModelDownload } from '../model-artifact-presentation'
import { modelVersionDisplayName } from '../model-display-name'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, CircleAlert, CircleCheck, Copy, Download } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import { ApiError } from '@/shared/api/error'
import { downloadProjectModelFile, getProjectModelFileStatus, type ModelFileStatus, type PlatformBaseModelBuild, type PlatformBaseModelVersionDetail } from '../services/model.service'

const props = defineProps<{ build?: PlatformBaseModelBuild | null; version: PlatformBaseModelVersionDetail; modelName: string; modelId: string; projectId: string; footerActions?: boolean }>()
defineEmits<{ back: [] }>()
const { locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
type ArtifactFile = { key: string; fileId: string; name: string; path: string; part?: 'weights' }
const files = computed<ArtifactFile[]>(() => {
  const listed = (props.build?.files ?? props.version.files).map(file => ({
    key: file.file_id, fileId: file.file_id, name: file.storage_uri.split(/[\\/]/).pop() || file.logical_name, path: file.storage_uri,
  }))
  const weights = props.build?.metadata.weights_object_uri
  if (props.build?.build_format !== 'openvino-ir' || typeof weights !== 'string' || listed.some(file => file.path === weights)) return listed
  const xml = listed.find(file => /\.xml$/i.test(file.path) && file.path.replace(/\.xml$/i, '.bin') === weights)
  return xml ? [...listed, { key: `${xml.key}:weights`, fileId: xml.fileId, part: 'weights', name: weights.split('/').pop() || weights, path: weights }] : listed
})
const fileStates = ref<Record<string, ModelFileStatus | { state: 'request-error' }>>({})
const checksums = ref<Record<string, string>>({})
let pendingChecksums = new Set<string>()
let checkRequest: AbortController | undefined
let downloadRequest: AbortController | undefined
const downloading = ref('')
const downloadError = ref(false)
const copyMessage = ref('')
const singleFile = computed(() => files.value.length === 1)
const requiredFilesKnown = computed(() => props.build?.build_format !== 'openvino-ir'
  || files.value.some(file => /\.xml$/i.test(file.path) && files.value.some(part => part.path === file.path.replace(/\.xml$/i, '.bin'))))
const filesPresent = computed(() => requiredFilesKnown.value && files.value.length > 0
  && files.value.every(file => fileStates.value[file.key]?.state === 'present'))
function fileRequest(file: ArtifactFile, signal?: AbortSignal) {
  return { projectId: props.projectId, modelId: props.modelId, versionId: props.version.model_version_id,
    fileId: file.fileId, ...(file.part && { part: file.part }), signal }
}
async function checkFiles(): Promise<void> {
  checkRequest?.abort()
  const request = new AbortController()
  checkRequest = request
  fileStates.value = {}
  pendingChecksums = new Set()
  checksums.value = {}
  await Promise.all(files.value.map(async file => {
    try {
      const result = await getProjectModelFileStatus(fileRequest(file, request.signal))
      if (!request.signal.aborted) fileStates.value[file.key] = file.part && result.part !== file.part ? { state: 'request-error' } : result
    } catch { if (!request.signal.aborted) fileStates.value[file.key] = { state: 'request-error' } }
  }))
}
function statusText(fileId: string): string {
  const state = fileStates.value[fileId]?.state
  if (!state) return zh.value ? '检查中…' : 'Checking…'
  const labels: Record<string, string> = zh.value
    ? { present: '文件存在', missing: '文件缺失', unavailable: '无法检查', 'request-error': '读取失败' }
    : { present: 'File present', missing: 'File missing', unavailable: 'Cannot check', 'request-error': 'Request failed' }
  return labels[state] ?? state
}
async function loadChecksum(file: ArtifactFile): Promise<void> {
  const request = checkRequest
  const pending = pendingChecksums
  if (!request || pending.has(file.key) || (checksums.value[file.key] && checksums.value[file.key] !== 'failed')) return
  pending.add(file.key)
  delete checksums.value[file.key]
  try {
    const result = await getProjectModelFileStatus({ ...fileRequest(file, request.signal), includeSha256: true })
    if (request.signal.aborted) return
    if (!file.part || result.part === file.part) fileStates.value[file.key] = result
    checksums.value[file.key] = (!file.part || result.part === file.part)
      && result.sha256 && /^[0-9a-f]{64}$/i.test(result.sha256) ? result.sha256 : 'failed'
  } catch {
    if (!request.signal.aborted) checksums.value[file.key] = 'failed'
  } finally { pending.delete(file.key) }
}
async function copyPath(path: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(path)
    copyMessage.value = zh.value ? '已复制文件路径。' : 'File path copied.'
  } catch { copyMessage.value = zh.value ? '无法复制文件路径。' : 'Could not copy the file path.' }
}
async function downloadFile(file: ArtifactFile): Promise<void> {
  if (downloading.value || fileStates.value[file.key]?.state !== 'present') return
  const request = new AbortController()
  downloadRequest = request
  downloading.value = file.key; downloadError.value = false
  try {
    const blob = await downloadProjectModelFile(fileRequest(file, request.signal))
    if (request.signal.aborted) return
    saveProjectModelDownload(blob, file.name)
  } catch (error) {
    if (request.signal.aborted) return
    downloadError.value = true
    if (error instanceof ApiError && error.status === 404) void checkFiles()
  } finally { if (!request.signal.aborted) downloading.value = '' }
}
function downloadSingle(): void { if (singleFile.value) void downloadFile(files.value[0]) }
defineExpose({ singleFile, filesPresent, downloading, downloadSingle })
watch(() => [props.projectId, props.modelId, props.version.model_version_id, props.build?.model_build_id], () => {
  downloadRequest?.abort()
  downloading.value = ''; downloadError.value = false; copyMessage.value = ''; void checkFiles()
}, { immediate: true })
onBeforeUnmount(() => { checkRequest?.abort(); downloadRequest?.abort() })
function object(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {} }
function stringValue(value: unknown): string { return typeof value === 'string' && value ? value : '—' }
function names(value: unknown): string { return Array.isArray(value) && value.every(item => typeof item === 'string') && value.length ? value.join(' / ') : '—' }
function formatName(value: string): string { return ({ onnx: 'ONNX', 'onnx-optimized': 'ONNX optimized', 'openvino-ir': 'OpenVINO', 'tensorrt-engine': 'TensorRT' } as Record<string, string>)[value] ?? value }
const inputTensor = computed(() => object(props.build?.metadata.input_tensor))
const inputSpec = computed(() => object(props.build?.metadata.model_input_spec ?? props.version.metadata.model_input_spec))
const inputNames = computed(() => {
  const inputName = props.build?.metadata.input_name ?? inputTensor.value.name
  return typeof inputName === 'string' && inputName ? inputName : names(props.build?.metadata.input_names)
})
const outputNames = computed(() => names(props.build?.metadata.output_names))
const inputDtype = computed(() => stringValue(inputTensor.value.dtype ?? inputSpec.value.dtype))
const inputLayout = computed(() => stringValue(inputTensor.value.layout ?? inputSpec.value.tensor_layout))
const inputShape = computed(() => {
  const shape = inputTensor.value.shape ?? inputSpec.value.tensor_shape
  return Array.isArray(shape) && shape.every(value => typeof value === 'number' || typeof value === 'string') ? shape.join(' × ') : '—'
})
const categories = computed(() => Array.isArray(props.version.metadata.category_names)
  ? props.version.metadata.category_names.flatMap((name, id) => typeof name === 'string' ? [{ id, name }] : []) : [])
const postprocess = computed(() => typeof inputSpec.value.postprocess_contract === 'string' ? inputSpec.value.postprocess_contract : '')
const validation = computed(() => {
  const passed = modelBuildValidation(props.build)
  if (passed === null) return null
  return passed
    ? { tone: 'success', label: zh.value ? '校验通过' : 'Passed' }
    : { tone: 'missing', label: zh.value ? '校验未通过' : 'Did not pass' }
})
const preprocessLabel = computed(() => {
  const value = inputSpec.value.preprocess
  if (value === 'letterbox') return 'Letterbox'
  if (value === 'yolox-top-left-letterbox') return zh.value ? 'YOLOX Letterbox（左上对齐）' : 'YOLOX Letterbox (top-left)'
  if (value === 'resize-center-crop') return zh.value ? '缩放并居中裁剪' : 'Resize and center crop'
  if (value === 'resize') return zh.value ? '缩放' : 'Resize'
  return value
})
const normalizationLabel = computed(() => {
  const value = inputSpec.value.normalization
  if (value === 'zero-to-one') return '0–1'
  if (value === 'imagenet') return 'ImageNet'
  if (value === 'none') return zh.value ? '无' : 'None'
  return value
})
const contractEntries = computed(() => [
  { label: zh.value ? '颜色空间' : 'Color space', value: inputSpec.value.color_space },
  { label: zh.value ? '预处理' : 'Preprocess', value: preprocessLabel.value },
  { label: zh.value ? '归一化' : 'Normalization', value: normalizationLabel.value },
  { label: zh.value ? '后处理契约' : 'Postprocessing contract', value: inputSpec.value.postprocess_contract },
].filter((entry): entry is { label: string; value: string } => typeof entry.value === 'string' && !!entry.value))
</script>

<style scoped>
.model-build-detail h2 { margin:0 0 6px; font-size:20px; overflow-wrap:anywhere; }
.model-build-detail h3 { margin:18px 0 10px; font-size:15px; }
.model-build-detail h4 { margin:0 0 10px; }
.model-build-detail__subtitle { margin:4px 0 14px; color:var(--am-text-muted); overflow-wrap:anywhere; }
.model-build-detail__note { color:var(--am-text-muted); font-size:12px; }
.model-build-detail__line { display:flex; align-items:center; flex-wrap:wrap; gap:6px; }
.model-build-detail__line :is(svg,button) { flex:none; }
.model-build-detail__line:is(.present,.success) { color:var(--am-success-text); }
.model-build-detail__line:is(.missing,.unavailable,.request-error) { color:var(--am-danger-text); }
.model-build-detail__filename { display:block; margin-bottom:4px; }
.model-build-detail__path span { flex:1; min-width:0; }
.model-build-detail__path { flex-wrap:nowrap; }
.model-build-detail details summary { cursor:pointer; }
.model-build-detail code { display:block; margin-top:6px; overflow-wrap:anywhere; }
.model-build-detail__error { color:var(--am-danger-text); }
.model-build-detail dl { margin:0; }
.model-build-detail dl div { display:grid; grid-template-columns:minmax(96px, 30%) minmax(0, 1fr); border:1px solid var(--am-border); border-bottom:0; }
.model-build-detail dl div:last-child { border-bottom:1px solid var(--am-border); }
dl.model-build-detail__information > div { grid-template-columns:minmax(90px,20%) minmax(0,1fr); }
.model-build-detail dt,.model-build-detail dd { margin:0; padding:9px 12px; overflow-wrap:anywhere; }
.model-build-detail dt { color:var(--am-text-muted); background:var(--am-surface); }
.model-build-detail__io,.model-build-detail__contracts { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(0,1fr); gap:12px; }
.model-build-detail__io section { padding:12px; border:1px solid var(--am-border); border-radius:5px; }
.model-build-detail table { table-layout:fixed; width:100%; }
.model-build-detail table :is(th,td) { padding:8px; overflow-wrap:anywhere; white-space:normal; }
.model-build-detail__io section:first-child th:last-child { width:38%; }
.model-build-detail__contracts th:first-child { width:25%; }
@media (max-width: 600px) { .model-build-detail__io,.model-build-detail__contracts { grid-template-columns:1fr; } }
</style>
