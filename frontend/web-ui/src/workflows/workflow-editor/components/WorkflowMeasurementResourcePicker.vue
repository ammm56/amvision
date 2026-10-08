<template>
  <button class="resource-picker" type="button" :disabled="disabled || !project.selectedProjectId" @click="show">
    <span>{{ currentLabel }}</span><span>{{ t('edit') }}</span>
  </button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" :title="kind === 'localization-template' ? t('template') : t('calibration')" :confirm-label="t('apply')" :cancel-label="t('cancel')"
      confirm-variant="primary" size="wide" scroll-body :busy="busy" :confirm-disabled="!selectedDocument || disabled" @cancel="close" @confirm="apply">
      <div class="resource-workspace">
        <p v-if="error" class="resource-error" role="alert">{{ error }}</p>
        <label>{{ t('version') }}<SelectField v-model="selected" :options="options" :disabled="busy" /></label>
        <Button v-if="current" variant="secondary" size="sm" :disabled="busy || disabled" @click="clear">{{ t('clear') }}</Button>
        <div v-if="selectedDocument" class="resource-version">
          <span>{{ selectedDocument.name }} · v{{ selectedDocument.reference.version }}</span>
          <Button v-if="selectedDocument.content.template" variant="secondary" size="sm" @click="viewStored">{{ t('view') }}</Button>
          <Button variant="secondary" size="sm" @click="exportSelected">{{ t('export') }}</Button>
        </div>
        <details>
          <summary>{{ t('newVersion') }}</summary>
          <div class="resource-create">
            <label>{{ t('name') }}<input v-model="name" maxlength="128"></label>
            <label>{{ t('import') }}<input type="file" accept=".zip,application/zip" @change="importArchive"></label>
            <template v-if="kind === 'localization-template'">
              <label>{{ t('referenceId') }}<input v-model="referenceId" maxlength="128"></label>
              <label>{{ t('image') }}<input type="file" accept=".png,image/png" @change="loadImage"></label>
              <button v-if="imageUrl" class="resource-image" type="button" @click="viewerOpen = true"><img :src="imageUrl" :alt="t('image')"><span>{{ t('draw') }}</span></button>
              <div class="resource-numbers">
                <label v-for="(label, index) in ['X', 'Y', 'Width', 'Height']" :key="label">{{ label }}<input v-model.number="roi[index]" type="number" step="1" :min="index < 2 ? 0 : 8"></label>
                <label v-for="(label, index) in ['Anchor X', 'Anchor Y']" :key="label">{{ label }}<input v-model.number="anchor[index]" type="number" step="0.1"></label>
              </div>
            </template>
            <template v-else>
              <p>{{ t('calibrationHelp') }}</p>
              <label>{{ t('calibrationJson') }}<textarea v-model="calibrationJson" rows="10" spellcheck="false" /></label>
            </template>
            <label class="resource-check"><input v-model="addVersion" type="checkbox" :disabled="!selectedDocument">{{ t('addVersion') }}</label>
            <Button variant="primary" :disabled="!canSave" @click="save">{{ t('saveResource') }}</Button>
          </div>
        </details>
      </div>
    </ConfirmDialog>
  </Teleport>
  <ImageViewer :open="viewerOpen" :image="viewerImage" :preview-disabled="true" dialog-layer @close="viewerOpen = false" @apply-interaction="applyRegion" />
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useProjectStore } from '@/app/stores/project.store'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import ImageViewer from '@/shared/ui/components/ImageViewer.vue'
import { apiRequest } from '@/shared/api/http-client'
import { importMeasurementResource, listMeasurementResources, readMeasurementResourceImage, resourceVersionPath, saveMeasurementResource, type MeasurementResourceDocument, type MeasurementResourceReference } from '../services/measurement-resource.service'

const props = defineProps<{ modelValue: unknown; schema: Record<string, unknown>; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: MeasurementResourceReference | undefined] }>()
const messages = {
  'zh-CN': { edit: '选择', template: '定位模板', calibration: '平面标定', apply: '应用', cancel: '取消', version: '资源版本', view: '查看图片', export: '导出', newVersion: '创建或导入资源', name: '资源名称', import: '导入资源包', referenceId: '参考坐标 ID', image: '参考原图（PNG）', draw: '标记模板区域和锚点', calibrationHelp: '使用 Planar Calibrate 节点生成并验证标定，再将 Calibration 输出保存在此。图片尺寸和单位必须与测量配置一致。', calibrationJson: 'Calibration 输出', addVersion: '保存为所选资源的新版本', saveResource: '保存资源', none: '未选择', invalidImage: '请选择不超过 64 MB 的 PNG 原图', invalid: '配置不完整或格式无效' },
  'en-US': { edit: 'Select', template: 'Localization Template', calibration: 'Planar Calibration', apply: 'Apply', cancel: 'Cancel', version: 'Resource version', view: 'View image', export: 'Export', newVersion: 'Create or import resource', name: 'Name', import: 'Import resource package', referenceId: 'Reference ID', image: 'Reference image (PNG)', draw: 'Set template region and anchor', calibrationHelp: 'Use Planar Calibrate to calculate and validate calibration, then save its Calibration output here. Image size and unit must match the measurement configuration.', calibrationJson: 'Calibration output', addVersion: 'Save a new version of the selected resource', saveResource: 'Save resource', none: 'Not selected', invalidImage: 'Select a PNG image up to 64 MB', invalid: 'Incomplete or invalid configuration' },
}
Object.assign(messages['zh-CN'], { clear: '清除资源引用' })
Object.assign(messages['en-US'], { clear: 'Clear resource reference' })
const { t } = useI18n({ useScope: 'local', messages, fallbackLocale: 'en-US' })
const project = useProjectStore()
const kind = computed(() => props.schema['x-resource-kind'] === 'localization-template' ? 'localization-template' : 'planar-calibration')
const current = computed(() => props.modelValue as MeasurementResourceReference | undefined)
const currentLabel = computed(() => current.value?.resource_id ? `${t(kind.value === 'localization-template' ? 'template' : 'calibration')} · v${current.value.version}` : t('none'))
const open = ref(false), busy = ref(false), error = ref(''), selected = ref<string | number | boolean | null>('')
const documents = ref<MeasurementResourceDocument[]>([])
const options = computed(() => documents.value.filter(d => d.reference.kind === kind.value).map(d => ({ value: key(d.reference), label: `${d.name} · v${d.reference.version}` })))
const selectedDocument = computed(() => documents.value.find(d => key(d.reference) === selected.value))
const name = ref(''), referenceId = ref('reference'), calibrationJson = ref(''), addVersion = ref(false)
const imageUrl = ref(''), imageFile = ref<File | null>(null), imageWidth = ref(0), imageHeight = ref(0)
const roi = ref<[number, number, number, number]>([0, 0, 100, 100]), anchor = ref<[number, number]>([50,50])
const viewerOpen = ref(false), storedView = ref(false)
let controller: AbortController | null = null
let generation = 0
const canSave = computed(() => !busy.value && name.value.trim().length > 0 && (kind.value === 'localization-template' ? !!imageFile.value : !!calibrationJson.value.trim()))
const viewerImage = computed(() => imageUrl.value ? { title: name.value || t('image'), nodeId: 'measurement-resource', src: imageUrl.value, width: imageWidth.value, height: imageHeight.value, mediaType: 'image/png',
  interaction: storedView.value ? null : { mode: 'edit', coordinateSpace: 'image', tools: [
    { tool: 'bbox', label: 'Template ROI', targetParameters: ['template_roi'], initialBboxesXyxy: [[roi.value[0], roi.value[1], roi.value[0] + roi.value[2], roi.value[1] + roi.value[3]]] as Array<[number,number,number,number]> },
    { tool: 'point', label: 'Anchor', targetParameters: ['anchor'], maxPoints: 1, initialPointsXy: [anchor.value] },
  ] } } : null)
function key(r: MeasurementResourceReference) { return `${r.resource_id}:${r.version}:${r.sha256}` }
function replaceImage(blob: Blob | null) { if (imageUrl.value) URL.revokeObjectURL(imageUrl.value); imageUrl.value = blob ? URL.createObjectURL(blob) : '' }
function close() { generation++; controller?.abort(); controller = null; open.value = false; viewerOpen.value = false; busy.value = false; replaceImage(null); imageFile.value = null }
async function show() {
  close(); open.value = true; error.value = ''; name.value = ''; calibrationJson.value = ''; addVersion.value = false
  selected.value = current.value ? key(current.value) : ''; controller = new AbortController()
  const token = generation
  await perform(async () => { const result = await listMeasurementResources(project.selectedProjectId, controller?.signal); if (token === generation) documents.value = result })
}
async function perform(work: () => Promise<void>) {
  const token = generation; busy.value = true; error.value = ''
  try { await work() } catch (e) { if (token === generation && !(e instanceof DOMException && e.name === 'AbortError')) error.value = e instanceof Error ? e.message : t('invalid') }
  finally { if (token === generation) busy.value = false }
}
function apply() { if (selectedDocument.value && !props.disabled) { emit('update:modelValue', selectedDocument.value.reference); close() } }
function clear() { if (!props.disabled && !busy.value) { emit('update:modelValue', undefined); close() } }
async function loadImage(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return
  const token = generation
  await perform(async () => {
    if (file.size > 64 * 1024 * 1024) throw new Error(t('invalidImage'))
    const bytes = new Uint8Array(await file.slice(0, 24).arrayBuffer())
    if (bytes.length < 24 || bytes[0] !== 137 || bytes[1] !== 80 || bytes[2] !== 78 || bytes[3] !== 71) throw new Error(t('invalidImage'))
    const view = new DataView(bytes.buffer), w = view.getUint32(16), h = view.getUint32(20)
    if (w < 8 || h < 8 || w * h > 16_000_000) throw new Error(t('invalidImage'))
    if (generation !== token) return
    imageFile.value = file; imageWidth.value = w; imageHeight.value = h; storedView.value = false; replaceImage(file)
    roi.value = [0, 0, Math.min(w, 100), Math.min(h, 100)]; anchor.value = [roi.value[2]/2, roi.value[3]/2]
  })
}
function applyRegion(event: { bboxXyxy?: [number,number,number,number]; pointsXy?: Array<[number,number]>; onApplied?: (ok: boolean) => void }) {
  if (storedView.value) { event.onApplied?.(false); return }
  if (event.bboxXyxy) { const [x,y,right,bottom] = event.bboxXyxy.map(Math.round); roi.value = [x,y,right-x,bottom-y]; anchor.value = [(x+right)/2,(y+bottom)/2] }
  if (event.pointsXy?.length) anchor.value = event.pointsXy[0]
  event.onApplied?.(true)
}
async function save() {
  const token = generation, projectId = project.selectedProjectId
  await perform(async () => {
    const body = new FormData(); body.set('name', name.value.trim())
    let content: Record<string, unknown>
    if (kind.value === 'localization-template') {
      const file = imageFile.value; if (!file) throw new Error(t('invalid'))
      const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
      const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('')
      content = { kind: kind.value, template: { reference_id: referenceId.value, image_width: imageWidth.value, image_height: imageHeight.value, template_roi: roi.value, anchor: anchor.value, image_sha256: hash } }; body.set('image', file)
    } else { content = { kind: kind.value, calibration: JSON.parse(calibrationJson.value) } }
    if (generation !== token) return
    body.set('content', JSON.stringify(content)); if (addVersion.value && selectedDocument.value) body.set('resource_id', selectedDocument.value.reference.resource_id)
    const result = await saveMeasurementResource(projectId, body, controller?.signal)
    if (generation !== token) return
    documents.value.push(result); selected.value = key(result.reference)
  })
}
async function importArchive(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return
  const token = generation
  await perform(async () => {
    if (file.size > 68 * 1024 * 1024) throw new Error(t('invalid'))
    const body = new FormData(); body.set('name', name.value.trim() || file.name); body.set('archive', file)
    const result = await importMeasurementResource(project.selectedProjectId, body, controller?.signal)
    if (generation !== token) return
    documents.value.push(result); if (result.reference.kind === kind.value) selected.value = key(result.reference)
  })
}
async function viewStored() {
  const item = selectedDocument.value, token = generation; if (!item?.content.template) return
  await perform(async () => { const image = await readMeasurementResourceImage(item.reference, controller?.signal); if (generation !== token) return; replaceImage(image); imageFile.value = null; imageWidth.value = item.content.template!.image_width; imageHeight.value = item.content.template!.image_height; storedView.value = true; viewerOpen.value = true })
}
async function exportSelected() {
  const item = selectedDocument.value, token = generation; if (!item) return
  await perform(async () => { const blob = await apiRequest<Blob>(`${resourceVersionPath(item.reference)}/export`, { responseType: 'blob', signal: controller?.signal }); if (generation !== token) return; const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `${item.reference.resource_id}-v${item.reference.version}.zip`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) })
}
watch(() => project.selectedProjectId, close)
onBeforeUnmount(close)
</script>
<style scoped>
.resource-picker { display:flex; justify-content:space-between; gap:8px; width:100%; padding:5px 8px; color:var(--am-text); background:var(--am-input); border:1px solid var(--am-border); border-radius:var(--am-radius-sm); font:inherit; cursor:pointer; }
.resource-picker span:first-child { overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.resource-workspace,.resource-create { display:grid; gap:16px; min-width:0; }
.resource-workspace label { display:grid; gap:6px; color:var(--am-text-muted); font-size:13px; }
.resource-workspace input,.resource-workspace textarea { min-width:0; padding:8px; color:var(--am-text); background:var(--am-input); border:1px solid var(--am-border); border-radius:var(--am-radius-sm); font:inherit; }
.resource-workspace :is(input,textarea):focus-visible { outline:2px solid var(--am-input-focus-ring); }
.resource-version,.resource-numbers { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.resource-numbers label { flex:1 1 80px; }
.resource-image { border:1px solid var(--am-border); background:var(--am-surface); color:var(--am-text); cursor:pointer; display:grid; gap:8px; padding:8px; }
.resource-image img { max-width:100%; max-height:240px; margin:auto; object-fit:contain; }
.resource-check { display:flex!important; align-items:center; }
.resource-error { color:var(--am-danger-text); overflow-wrap:anywhere; }
summary { cursor:pointer; padding:8px 0; color:var(--am-text); }
</style>
