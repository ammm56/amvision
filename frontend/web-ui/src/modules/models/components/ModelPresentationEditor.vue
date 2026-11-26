<template>
  <SideDrawer :open="open" :title="label('编辑模型信息', 'Edit model information')" :close-label="label('关闭', 'Close')"
    panel-class="model-editor-drawer" plain :busy="saving" @close="requestClose">
    <form class="model-editor" @submit.prevent="save">
      <label>
        <span>{{ label('模型名称', 'Model name') }} <span class="model-editor__required" aria-hidden="true">*</span></span>
        <input v-model="name" maxlength="128" :disabled="saving" required />
      </label>
      <label>
        <span>{{ label('模型说明', 'Description') }}</span>
        <textarea v-model="description" maxlength="2000" rows="5" :disabled="saving" />
      </label>
      <dl class="model-editor__identity">
        <div><dt>{{ label('任务类型', 'Task type') }}</dt><dd>{{ modelTaskLabel(model?.task_type, locale.startsWith('zh')) }}</dd></div>
        <div><dt>{{ label('模型系列', 'Architecture') }}</dt><dd>{{ architecture }}</dd></div>
      </dl>
      <p class="model-editor__hint"><CircleHelp :size="16" aria-hidden="true" />{{ label('修改展示信息不会改变模型版本和训练产物。', 'Display changes do not alter model versions or training outputs.') }}</p>
      <dl class="model-editor__time">
        <div><dt>{{ label('最近更新时间', 'Last updated') }}</dt><dd>{{ formatSystemDateTime(baseline.updatedAt, 'minutes') }}</dd></div>
      </dl>
      <InlineError :message="error" />
      <div v-if="conflict" class="model-editor__conflict">
        <Button v-if="!serverPresentation" size="sm" variant="secondary" :loading="readingLatest" @click="readLatest">
          <RefreshCw :size="15" />{{ label('读取最新信息', 'Load current information') }}
        </Button>
        <template v-else>
          <strong>{{ label('服务器上的最新信息', 'Current information on the server') }}</strong>
          <dl>
            <div><dt>{{ label('模型名称', 'Model name') }}</dt><dd>{{ serverPresentation.name }}</dd></div>
            <div><dt>{{ label('模型说明', 'Description') }}</dt><dd>{{ serverPresentation.description || '—' }}</dd></div>
          </dl>
          <div class="model-editor__conflict-actions">
            <Button size="sm" variant="secondary" @click="acceptLatest(false)">{{ label('使用最新信息', 'Use current information') }}</Button>
            <Button size="sm" variant="secondary" @click="acceptLatest(true)">{{ label('保留我的草稿', 'Keep my draft') }}</Button>
          </div>
        </template>
      </div>
    </form>
    <template #footer>
      <div class="model-editor__actions">
        <Button :disabled="saving" @click="requestClose">{{ label('取消', 'Cancel') }}</Button>
        <Button variant="primary" :loading="saving" :disabled="!canSave" @click="save">{{ label('保存', 'Save') }}</Button>
      </div>
    </template>
  </SideDrawer>
  <Teleport to="body">
    <ConfirmDialog v-if="confirmLeave" panel-class="model-editor-discard"
      :title="label('放弃未保存修改？', 'Discard unsaved changes?')"
      :message="label('离开后，本次名称和说明修改不会保存。', 'Leaving discards the changes to the name and description.')"
      :confirm-label="label('放弃修改', 'Discard changes')" :cancel-label="label('继续编辑', 'Keep editing')"
      @confirm="settleLeave(true)" @cancel="settleLeave(false)">
      <template #title-icon><CircleAlert :size="36" aria-hidden="true" /></template>
    </ConfirmDialog>
  </Teleport>
</template>

<script setup lang="ts">
import { CircleAlert, CircleHelp, RefreshCw } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError } from '@/shared/api/error'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { modelDisplayName } from '../model-display-name'
import { modelTaskLabel } from '../model-evaluation-types'
import { getProjectModelCatalogDetail, updateProjectModelPresentation, type PlatformBaseModelSummary } from '../services/model.service'

const props = defineProps<{ open: boolean; projectId: string; model: PlatformBaseModelSummary | null }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const { locale } = useI18n()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en

interface Presentation {
  name: string
  description: string
  revision: number
  updatedAt: string | null
}

function readPresentation(model: PlatformBaseModelSummary | null): Presentation {
  const metadata = model?.metadata
  return {
    name: model ? modelDisplayName(model) : '',
    description: typeof metadata?.description === 'string' ? metadata.description : '',
    revision: typeof metadata?.presentation_revision === 'number' ? metadata.presentation_revision : 0,
    updatedAt: typeof metadata?.presentation_updated_at === 'string' ? metadata.presentation_updated_at : null,
  }
}

const name = ref('')
const description = ref('')
const baseline = ref(readPresentation(null))
const serverPresentation = ref<Presentation | null>(null)
const saving = ref(false)
const readingLatest = ref(false)
const confirmLeave = ref(false)
const conflict = ref(false)
const error = ref<string | null>(null)
const dirty = computed(() => name.value.trim() !== baseline.value.name || description.value.trim() !== baseline.value.description)
const canSave = computed(() => props.open && !!props.model && !saving.value && !conflict.value && !confirmLeave.value && dirty.value && !!name.value.trim())
const architecture = computed(() => [props.model?.model_type, props.model?.model_scale].filter(Boolean).join('-') || '—')
let generation = 0
let latestRequest: AbortController | undefined
let leaveRequest: Promise<boolean> | undefined
let resolveLeave: ((allowed: boolean) => void) | undefined

function applyPresentation(presentation: Presentation): void {
  baseline.value = presentation
  name.value = presentation.name
  description.value = presentation.description
}

watch(() => [props.open, props.projectId, props.model?.model_id] as const, () => {
  generation++
  latestRequest?.abort()
  settleLeave(false)
  applyPresentation(readPresentation(props.model))
  serverPresentation.value = null
  saving.value = false
  readingLatest.value = false
  conflict.value = false
  error.value = null
}, { immediate: true })

function allowNavigation(): Promise<boolean> {
  if (!props.open) return Promise.resolve(true)
  if (saving.value) return Promise.resolve(false)
  if (!dirty.value) return Promise.resolve(true)
  if (leaveRequest) return leaveRequest
  confirmLeave.value = true
  leaveRequest = new Promise(resolve => { resolveLeave = resolve })
  return leaveRequest
}

function settleLeave(allowed: boolean): void {
  confirmLeave.value = false
  resolveLeave?.(allowed)
  resolveLeave = undefined
  leaveRequest = undefined
}

async function requestClose(): Promise<void> {
  if (await allowNavigation()) emit('close')
}

function preventUnintentionalReload(event: BeforeUnloadEvent): void {
  if (!props.open || (!dirty.value && !saving.value)) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => window.addEventListener('beforeunload', preventUnintentionalReload))
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', preventUnintentionalReload)
  generation++
  latestRequest?.abort()
  settleLeave(false)
})

defineExpose({ allowNavigation })

async function save(): Promise<void> {
  if (!canSave.value || !props.model) return
  const active = generation
  saving.value = true
  error.value = null
  try {
    await updateProjectModelPresentation({
      projectId: props.projectId,
      modelId: props.model.model_id,
      displayName: name.value.trim(),
      description: description.value.trim(),
      revision: baseline.value.revision,
    })
    if (generation === active) emit('saved')
  } catch (cause) {
    if (generation !== active) return
    conflict.value = cause instanceof ApiError && cause.status === 409
    error.value = cause instanceof Error ? cause.message : label('保存失败，请重试。', 'Save failed. Try again.')
  } finally {
    if (generation === active) saving.value = false
  }
}

async function readLatest(): Promise<void> {
  if (!props.model || !conflict.value || readingLatest.value) return
  const active = generation
  const request = new AbortController()
  latestRequest = request
  readingLatest.value = true
  try {
    const current = await getProjectModelCatalogDetail(props.projectId, props.model.model_id, request.signal)
    if (generation === active) serverPresentation.value = readPresentation(current)
  } catch (cause) {
    if (generation === active) error.value = cause instanceof Error ? cause.message : label('读取最新信息失败。', 'Could not load the current information.')
  } finally {
    if (generation === active) readingLatest.value = false
  }
}

function acceptLatest(keepDraft: boolean): void {
  const current = serverPresentation.value
  if (!current) return
  if (keepDraft) baseline.value = current
  else applyPresentation(current)
  serverPresentation.value = null
  conflict.value = false
  error.value = null
}
</script>

<style scoped>
:global(.model-editor-drawer.side-drawer) { width:min(600px, calc(100vw - 36px)); }
:global(.side-drawer__backdrop:has(> .model-editor-drawer)), :global(.confirm-dialog-backdrop:has(> .model-editor-discard)) {
  background:color-mix(in srgb, var(--am-overlay) 75%, #000 25%);
}
:global(.model-editor-discard.confirm-dialog) { width:min(440px, calc(100vw - 36px)); padding:22px; text-align:center; }
:global(.model-editor-discard .confirm-dialog__header) { position:relative; justify-content:center; }
:global(.model-editor-discard .confirm-dialog__header h2) { display:grid; gap:10px; justify-items:center; padding:8px 26px 0; }
:global(.model-editor-discard .confirm-dialog__header svg) { color:var(--am-warning-text); }
:global(.model-editor-discard .confirm-dialog__close) { position:absolute; inset:0 0 auto auto; background:transparent; border-color:transparent; }
:global(.model-editor-discard .confirm-dialog__close svg) { color:var(--am-text); }
:global(.model-editor-discard .confirm-dialog__actions) { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); }
:global(.model-editor-discard .confirm-dialog__leading-actions) { display:none; }
.model-editor { display:grid; gap:20px; min-width:0; }
.model-editor label { display:grid; gap:8px; font-weight:600; }
.model-editor input,.model-editor textarea { box-sizing:border-box; width:100%; padding:10px 12px; border:1px solid var(--am-border-strong); border-radius:var(--am-radius-sm); color:var(--am-text); background:var(--am-surface-raised); font:inherit; font-weight:400; }
.model-editor textarea { resize:vertical; min-height:90px; }
.model-editor__required { color:var(--am-danger-text); }
.model-editor dl { display:grid; gap:12px; margin:0; }
.model-editor dl > div { display:grid; grid-template-columns:minmax(90px, 112px) minmax(0, 1fr); align-items:center; gap:8px; }
.model-editor dt { color:var(--am-text); }
.model-editor dd { margin:0; overflow-wrap:anywhere; }
.model-editor__identity dd { padding:10px 12px; background:var(--am-surface); border:1px solid var(--am-border); border-radius:var(--am-radius-sm); color:var(--am-text-muted); }
.model-editor__hint { display:flex; gap:7px; align-items:flex-start; margin:-10px 0 0; padding-inline-start:120px; color:var(--am-text-muted); }
.model-editor__hint svg { flex:none; margin-top:2px; }
.model-editor__time { padding-top:18px; border-top:1px solid var(--am-border); }
.model-editor__time dd { color:var(--am-text-muted); }
.model-editor__actions,.model-editor__conflict-actions { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:10px; width:100%; }
.model-editor__actions :deep(.ui-button) { min-width:94px; }
.model-editor__conflict { display:grid; gap:12px; padding:14px; border:1px solid var(--am-border); border-radius:var(--am-radius-sm); }
.model-editor__conflict > .ui-button { justify-self:start; }
.model-editor__conflict dd { white-space:pre-wrap; }
@media (max-width: 560px) { .model-editor__hint { padding-inline-start:0; } }
</style>
