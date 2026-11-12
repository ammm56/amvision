<template>
  <SideDrawer
    :open="open"
    size="compact"
    plain
    :title="text(editing ? 'edit' : 'info')"
    :close-label="text('close')"
    :busy="busy"
    @close="close"
    @after-leave="finished"
  >
    <InlineError v-if="error" :message="error" /><Button
      v-if="conflict"
      @click="reload"
      >{{ text('reload') }}</Button
    >
    <form
      v-if="editing"
      id="dataset-info-form"
      class="dataset-form"
      @submit.prevent="save"
    >
      <label class="field"
        ><span>{{ text('name') }} *</span
        ><input v-model="name" maxlength="255" required :disabled="busy"
      /></label>
      <label class="field"
        ><span>{{ text('description') }}</span
        ><textarea
          v-model="description"
          rows="5"
          maxlength="2000"
          :disabled="busy"
        />
      </label>
    </form>
    <dl class="dataset-details dataset-info-basics">
      <template v-if="!editing"
        ><dt>{{ text('name') }}</dt>
        <dd><strong>{{ current.display_name }}</strong></dd>
        <dt>{{ text('description') }}</dt>
        <dd>{{ current.description || '—' }}</dd></template
      >
      <dt>{{ text('project') }}</dt>
      <dd>{{ project.projects.find(item => item.project_id === current.project_id)?.display_name || current.project_id }}</dd>
      <dt>{{ text('task') }}</dt>
      <dd>{{ current.task_type }}</dd>

    </dl>
    <template v-if="!editing">
      <InlineError v-if="summaryError" :message="summaryError" />
      <div class="dataset-info-metrics" :aria-busy="summaryLoading">
        <div v-for="item in metrics" :key="item.label"><component :is="item.icon" :size="21" /><span>{{ item.label }}<strong>{{ item.value }}</strong></span></div>
      </div>
      <div class="dataset-info-dates">
        <div v-for="item in [{ label: text('created'), value: current.created_at }, { label: text('updated'), value: current.updated_at }]" :key="item.label"><Clock3 :size="21" /><span>{{ item.label }}<strong>{{ datasetDate(item.value) }}</strong></span></div>
      </div>
      <div class="dataset-info-id"><span>{{ label('数据集 ID', 'Dataset ID') }}</span><span :title="current.dataset_id">{{ current.dataset_id }}</span><Button icon-only :aria-label="label('复制数据集 ID', 'Copy dataset ID')" @click="copyId"><Copy :size="16" /></Button></div>
    </template>
    <template #footer
      ><span />
      <div class="dataset-actions">
        <Button v-if="editing" :disabled="busy" @click="close">{{
          text(editing ? 'cancel' : 'close')
        }}</Button
        ><Button
          v-if="!editing && editable"
          @click="editing = true"
          >{{ text('edit') }}</Button
        ><Button v-if="!editing && latest" variant="primary" @click="viewDataset">{{ label('查看数据集', 'View dataset') }}</Button><Button
          v-if="editing"
          type="submit"
          form="dataset-info-form"
          variant="primary"
          :loading="busy"
          :disabled="!dirty || !name.trim() || conflict"
          >{{ text('save') }}</Button
        >
      </div></template
    >
  </SideDrawer>
  <ConfirmDialog
    v-if="discard"
    :title="text('discard')"
    :message="text('unsaved')"
    :confirm-label="text('discard')"
    :cancel-label="text('cancel')"
    @confirm="answer(true)"
    @cancel="answer(false)"
  />
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Copy, Layers, Images, Tags, FileInput, Database, Clock3 } from '@lucide/vue'
import { ApiError } from '@/shared/api/error'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { useFeedbackStore } from '@/app/stores/feedback.store'
import { useProjectStore } from '@/app/stores/project.store'
import { useDatasetText, datasetError, datasetDate } from '../dataset-workspace'
import {
  editDatasetInfo,
  listDatasetVersionPage,
  type DatasetVersion,
  getDatasetInfo,
  type DatasetInfo,
} from '../services/dataset-workspace.service'
const props = defineProps<{
    info: DatasetInfo
    mode: 'info' | 'edit'
    editable: boolean
  }>(),
  emit = defineEmits<{ close: []; saved: [info: DatasetInfo] }>()
const text = useDatasetText(),
  feedback = useFeedbackStore(),
  project = useProjectStore(),
  current = ref(props.info),
  editing = ref(props.mode === 'edit'),
  open = ref(true),
  busy = ref(false),
  error = ref(''),
  conflict = ref(false),
  discard = ref(false),
  name = ref(props.info.display_name),
  description = ref(props.info.description)
const router = useRouter(), { locale } = useI18n()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const latest = ref<DatasetVersion | null>(null), versionCount = ref<number | null>(null), summaryLoading = ref(false), summaryError = ref('')
const summaryController = new AbortController()
const sourceLabel = computed(() => {
  const metadata = latest.value?.metadata
  if (!metadata) return '—'
  if (metadata.parent_version_id) return text('derived')
  const format = metadata.format_type
  if (typeof format === 'string' && format) return `${format.replaceAll('_', ' ').toUpperCase()} ZIP`
  return metadata.source_import_id ? text('imported') : '—'
})
const metrics = computed(() => [
  { icon: Database, label: label('最新可用版本', 'Latest available version'), value: latest.value ? `v${latest.value.version_number}` : '—' },
  { icon: Layers, label: label('版本数量', 'Versions'), value: versionCount.value == null ? '—' : `${versionCount.value} ${label('个版本', 'versions')}` },
  { icon: Images, label: text('samples'), value: latest.value ? `${latest.value.sample_count.toLocaleString()} ${label('张', 'images')}` : '—' },
  { icon: Tags, label: text('classes'), value: latest.value ? `${latest.value.category_count.toLocaleString()} ${label('类', 'classes')}` : '—' },
  { icon: FileInput, label: text('source'), value: sourceLabel.value },
])
watch(editing, async value => {
  if (value || latest.value || summaryLoading.value) return
  summaryLoading.value = true
  try {
    const query = { project_id: props.info.project_id, dataset_id: props.info.dataset_id, limit: 1 }
    const [all, available] = await Promise.all([
      listDatasetVersionPage(query, summaryController.signal),
      listDatasetVersionPage({ ...query, state: 'available' }, summaryController.signal),
    ])
    if (!summaryController.signal.aborted) { latest.value = available.items[0] || null; versionCount.value = all.total }
  } catch (e) { if (!summaryController.signal.aborted) summaryError.value = datasetError(e) }
  finally { summaryLoading.value = false }
}, { immediate: true })
async function copyId() {
  try { await navigator.clipboard.writeText(current.value.dataset_id); feedback.info(label('已复制', 'Copied')) }
  catch { feedback.error(label('复制失败', 'Copy failed')) }
}
function viewDataset() {
  if (!latest.value) return
  const path = `/datasets/${encodeURIComponent(current.value.dataset_id)}/versions/${encodeURIComponent(latest.value.dataset_version_id)}`
  open.value = false
  void router.push(path)
}
const dirty = computed(
  () =>
    editing.value &&
    (name.value !== current.value.display_name ||
      description.value !== current.value.description),
)
let saved: DatasetInfo | undefined,
  leaveAnswer: ((value: boolean) => void) | undefined,
  active = true
function close() {
  if (busy.value) return
  if (dirty.value) discard.value = true
  else open.value = false
}
function answer(value: boolean) {
  discard.value = false
  if (leaveAnswer) {
    leaveAnswer(value)
    leaveAnswer = undefined
  } else if (value) open.value = false
}
function finished() {
  if (saved) {
    feedback.success(text('saved'))
    emit('saved', saved)
  } else emit('close')
}
async function reload() {
  busy.value = true
  try {
    current.value = await getDatasetInfo(
      props.info.project_id,
      props.info.dataset_id,
    )
    conflict.value = false
    error.value = ''
  } catch (e) {
    error.value = datasetError(e)
  } finally {
    busy.value = false
  }
}
async function save() {
  if (!props.editable || busy.value || !dirty.value || !name.value.trim())
    return
  busy.value = true
  error.value = ''
  try {
    saved = await editDatasetInfo(current.value, {
      display_name: name.value.trim(),
      description: description.value,
    })
    if (active) open.value = false
  } catch (e) {
    error.value = datasetError(e)
    conflict.value = e instanceof ApiError && e.status === 409
  } finally {
    busy.value = false
  }
}
function confirmLeave() {
  if (busy.value) return false
  if (!dirty.value) return true
  discard.value = true
  return new Promise<boolean>((resolve) => {
    leaveAnswer = resolve
  })
}
onBeforeRouteLeave(confirmLeave)
onBeforeRouteUpdate(confirmLeave)
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault()
    event.returnValue = ''
  }
}
window.addEventListener('beforeunload', beforeUnload)
onBeforeUnmount(() => {
  summaryController.abort()
  active = false
  leaveAnswer?.(false)
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>

<style scoped>
.dataset-info-basics { margin:0; grid-template-columns:112px minmax(0,1fr); gap:0; align-items:stretch; }
.dataset-info-basics dt,.dataset-info-basics dd { margin:0; padding:18px 0; line-height:22px; }
.dataset-info-basics dt { display:flex; align-items:center; }
.dataset-info-basics dd { color:var(--am-text); overflow-wrap:anywhere; }
.dataset-info-basics strong { font-weight:600; }
.dataset-info-metrics,.dataset-info-dates { display:grid; grid-template-columns:1fr 1fr; gap:26px 20px; padding:24px 0; }
.dataset-info-metrics > div,.dataset-info-dates > div { display:flex; align-items:flex-start; gap:12px; min-width:0; }
.dataset-info-metrics svg,.dataset-info-dates svg { color:var(--am-text-secondary); margin-top:2px; flex-shrink:0; }
.dataset-info-metrics span,.dataset-info-dates span { display:grid; gap:9px; font-size:14px; color:var(--am-text-muted); min-width:0; }
.dataset-info-metrics strong,.dataset-info-dates strong { color:var(--am-text); font-size:15px; font-weight:400; overflow-wrap:anywhere; }
.dataset-info-id { display:grid; grid-template-columns:96px minmax(0,1fr) auto; align-items:center; gap:12px; padding-top:24px; font-size:13px; }
.dataset-info-id > span:first-child { color:var(--am-text-muted); }
.dataset-info-id > span:nth-child(2) { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
</style>
