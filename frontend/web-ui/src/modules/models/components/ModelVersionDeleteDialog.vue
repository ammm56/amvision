<template>
  <Teleport to="body">
    <ConfirmDialog v-if="open" scroll-body
      :panel-class="blocked ? 'model-version-delete model-version-delete--blocked' : 'model-version-delete'"
      :title="blocked ? label('无法删除模型版本', 'Cannot delete model version') : label('删除模型版本', 'Delete model version')"
      :confirm-label="blocked ? label('查看引用', 'View references') : label('删除版本', 'Delete version')"
      :cancel-label="blocked || uncertain ? label('关闭', 'Close') : label('取消', 'Cancel')"
      :show-confirm="blocked ? referenceCount > 0 : !!preview?.revision && !uncertain"
      :confirm-variant="blocked ? 'primary' : 'danger'"
      :confirm-disabled="!blocked && !readyToDelete" :busy="deleting"
      @cancel="close" @confirm="blocked ? $emit('references') : remove()">
      <template #title-icon><CircleAlert :size="23" aria-hidden="true" /></template>
      <template v-if="(error || blocked) && !uncertain" #leading-actions>
        <Button size="sm" variant="ghost" :disabled="loading || loadingReferences" @click="check">{{ label('重新检查', 'Check again') }}</Button>
      </template>

      <p v-if="loading" role="status">{{ label('正在检查依赖和删除范围…', 'Checking dependencies and deletion scope…') }}</p>
      <template v-else-if="blocked">
        <div class="model-delete__intro">
          <strong role="alert">
            {{ referenceCount
              ? label(`此版本仍被 ${referenceCount} 个部署实例引用，无法删除。`, `This version is referenced by ${referenceCount} deployment instances.`)
              : preview?.reason || label('此版本仍有依赖，无法删除。', 'This version still has dependencies.') }}
          </strong>
          <p class="model-delete__version">{{ confirmationLabel }}</p>
          <p v-if="referenceCount">{{ label('已停止的部署也会保留绑定。解除相关绑定后，可重新检查。', 'Stopped deployments retain their bindings. Remove the bindings and check again.') }}</p>
        </div>
        <p v-if="loadingReferences" role="status">{{ label('正在读取直接部署引用…', 'Loading direct deployment references…') }}</p>
        <InlineError :message="referenceError" />
        <div v-if="references.length" class="resource-table model-delete__references">
          <table>
            <thead><tr><th scope="col">{{ label('部署实例名称', 'Deployment instance') }}</th><th scope="col">{{ label('状态', 'Status') }}</th><th scope="col">{{ label('类型', 'Type') }}</th><th scope="col">{{ label('操作', 'Action') }}</th></tr></thead>
            <tbody>
              <tr v-for="item in references" :key="item.deployment_id">
                <td>{{ item.display_name }}</td>
                <td><div class="model-delete__runtimes">
                  <span v-for="state in runtimeStates(item.runtime_states)" :key="state.mode" class="model-delete__runtime" :class="{ 'is-running': state.status === 'running' }">
                    {{ state.label }}</span>
                </div></td>
                <td>{{ label('部署实例', 'Deployment') }}</td>
                <td><RouterLink :to="{ path: '/deployments', query: { deployment: item.deployment_id } }">{{ label('查看', 'View') }}</RouterLink></td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <template v-else-if="preview?.revision">
        <div class="model-delete__intro">
          <strong>{{ label('确认删除此模型版本？', 'Delete this model version?') }}</strong>
          <p>{{ label('删除后无法恢复该版本的登记记录。', 'Deleting permanently removes this version’s registry record.') }}</p>
        </div>
        <div class="model-delete__target">
          <dl>
            <div><dt>{{ label('模型名称', 'Model') }}</dt><dd>{{ modelName }}</dd></div>
            <div><dt>{{ label('版本', 'Version') }}</dt><dd>{{ confirmationLabel }}</dd></div>
            <div v-if="taskType"><dt>{{ label('任务类型', 'Task type') }}</dt><dd>{{ taskType }}</dd></div>
            <div><dt>{{ label('运行格式', 'Runtime formats') }}</dt><dd>{{ formats.join(' · ') || '—' }}</dd></div>
          </dl>
          <p>{{ label('未发现阻止删除的依赖。', 'No dependencies block deletion.') }}</p>
        </div>
        <section class="model-delete__impact">
          <h3>{{ label('删除范围', 'Deletion scope') }}</h3>
          <ul>
            <li><Trash2 :size="17" aria-hidden="true" /><span>{{ buildCount
              ? label(`删除此版本和 ${buildCount} 个转换产物的登记。`, `Removes this version and ${buildCount} conversion artifact records.`)
              : label('删除此模型版本的登记。', 'Removes this model version’s registry record.') }}</span></li>
            <li v-if="preview.has_file_cleanup"><Trash2 :size="17" aria-hidden="true" /><span>{{ label('专属文件由清理任务处理。', 'The cleanup task removes files owned by this version.') }}</span></li>
            <li v-if="otherVersionCount"><CircleCheck :size="17" aria-hidden="true" /><span>{{ label(`保留同一模型的其他 ${otherVersionCount} 个版本。`, `Keeps the other ${otherVersionCount} versions of this model.`) }}</span></li>
            <li><CircleCheck :size="17" aria-hidden="true" /><span>{{ label('保留来源数据集、任务历史及任务目录中的文件。', 'Keeps the source dataset, task history and task-owned files.') }}</span></li>
          </ul>
        </section>
        <label v-if="!uncertain" class="model-delete__confirm">
          <span>{{ label('输入版本号确认', 'Enter version number to confirm') }}</span>
          <input v-model="confirmation" :placeholder="confirmationLabel" :disabled="deleting" autocomplete="off" spellcheck="false" />
        </label>
      </template>
      <InlineError :message="error" />
      <p v-if="uncertain" role="alert">{{ label('未能确认删除结果。关闭后将刷新模型列表。', 'Could not confirm the deletion. The model list will refresh when this dialog closes.') }}</p>
    </ConfirmDialog>
  </Teleport>
</template>

<script setup lang="ts">
import { CircleAlert, CircleCheck, Trash2 } from '@lucide/vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError } from '@/shared/api/error'
import { previewModelVersionDeletion, submitResourceDeletion, type ModelVersionDeletionPreview } from '@/shared/api/resource-deletion'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { listModelVersionReferences, type ModelDeploymentReference } from '../services/model.service'

const props = defineProps<{
  open: boolean
  projectId: string
  modelId: string
  versionId: string
  versionLabel?: string
  modelName: string
  taskType?: string
  formats: string[]
  otherVersionCount: number
}>()
const emit = defineEmits<{ close: []; deleted: []; references: []; uncertain: [] }>()
const { locale } = useI18n()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en

const preview = ref<ModelVersionDeletionPreview | null>(null)
const references = ref<ModelDeploymentReference[]>([])
const referenceCount = ref(0)
const confirmation = ref('')
const loading = ref(false)
const loadingReferences = ref(false)
const deleting = ref(false)
const uncertain = ref(false)
const error = ref<string | null>(null)
const referenceError = ref<string | null>(null)
const blocked = computed(() => preview.value?.blocked === true)
const buildCount = computed(() => preview.value?.deleted_models?.filter(item => item.kind === 'model-build').length ?? 0)
const confirmationLabel = computed(() => props.versionLabel && props.versionLabel !== '—' ? props.versionLabel : props.versionId)
const readyToDelete = computed(() => props.open && !!preview.value?.revision && !blocked.value
  && !loading.value && !deleting.value && !uncertain.value && confirmation.value.trim() === confirmationLabel.value)

let generation = 0
let readRequest: AbortController | undefined

function runtimeStates(states: Record<string, string>): Array<{ mode: string; status: string; label: string }> {
  const labels: Record<string, string> = {
    active: label('启用', 'Enabled'), running: label('运行中', 'Running'),
    stopped: label('已停止', 'Stopped'), starting: label('启动中', 'Starting'),
    failed: label('失败', 'Failed'), degraded: label('异常', 'Degraded'),
  }
  const modes = [
    { mode: 'sync', status: states.sync, name: label('同步', 'Sync') },
    { mode: 'async', status: states.async, name: label('异步', 'Async') },
  ].filter(item => item.status)
  if (!modes.length) return [{ mode: 'instance', status: states.instance ?? '', label: labels[states.instance] || states.instance || '—' }]
  if (modes.every(item => item.status === modes[0].status)) {
    const status = modes[0].status
    return [{ mode: 'instance', status, label: labels[status] || status }]
  }
  return modes.map(({ mode, status, name }) => ({ mode, status, label: `${name} · ${labels[status] || status}` }))
}

async function check(): Promise<void> {
  if (!props.open || !props.modelId || !props.versionId || deleting.value || uncertain.value) return
  readRequest?.abort()
  const request = new AbortController()
  readRequest = request
  const active = ++generation
  const { projectId, modelId, versionId } = props
  const options = { projectId, modelId, versionId, offset: 0, limit: 4, signal: request.signal }

  preview.value = null
  loading.value = true
  loadingReferences.value = false
  references.value = []
  referenceCount.value = 0
  confirmation.value = ''
  error.value = null
  referenceError.value = null
  try {
    const result = await previewModelVersionDeletion(projectId, versionId, request.signal)
    if (generation !== active) return
    preview.value = result
    if (!result.blocked) return
    loading.value = false
    loadingReferences.value = true
    try {
      const list = await listModelVersionReferences(options)
      if (generation !== active) return
      references.value = list.items
      referenceCount.value = list.total
    } catch {
      if (generation === active) referenceError.value = label('直接部署引用读取失败。', 'Could not load direct deployment references.')
    } finally {
      if (generation === active) loadingReferences.value = false
    }
  } catch (cause) {
    if (generation === active) error.value = cause instanceof Error ? cause.message : label('无法检查删除范围。', 'Could not check the deletion scope.')
  } finally {
    if (generation === active) loading.value = false
  }
}

async function remove(): Promise<void> {
  const revision = preview.value?.revision
  if (!readyToDelete.value || !revision) return
  const active = generation
  deleting.value = true
  error.value = null
  try {
    const result = await submitResourceDeletion('model-version', props.versionId, props.projectId, revision)
    if (generation !== active) return
    if (result.state === 'committed' || result.state === 'completed') emit('deleted')
    else uncertain.value = true
  } catch (cause) {
    if (generation !== active) return
    if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) {
      error.value = cause.message
      preview.value = null
    } else uncertain.value = true
  } finally {
    if (generation === active) deleting.value = false
  }
}

function close(): void {
  if (uncertain.value) emit('uncertain')
  emit('close')
}

watch(() => [props.open, props.projectId, props.modelId, props.versionId] as const, ([open]) => {
  generation++
  readRequest?.abort()
  deleting.value = false
  uncertain.value = false
  if (open) void check()
}, { immediate: true })
onBeforeUnmount(() => {
  generation++
  readRequest?.abort()
})
</script>

<style scoped>
:global(.model-version-delete .confirm-dialog__header h2) { display:flex; align-items:center; gap:10px; color:var(--am-danger-text); }
:global(.model-version-delete--blocked.confirm-dialog .confirm-dialog__header h2) { color:var(--am-warning-text); }
:global(.confirm-dialog-backdrop:has(> .model-version-delete)) { background:color-mix(in srgb, var(--am-overlay) 75%, #000 25%); }
.model-delete__intro { display:grid; gap:6px; min-width:0; }
.model-delete__intro strong { font-size:15px; }
.model-delete__intro p,.model-delete__target p { margin:0; color:var(--am-text-muted); }
.model-delete__version { overflow-wrap:anywhere; }
.model-delete__target { display:grid; gap:9px; padding:13px 14px; border:1px solid var(--am-border); border-radius:var(--am-radius-sm); background:var(--am-surface-muted); }
.model-delete__target dl { display:grid; gap:7px; margin:0; }
.model-delete__target dl > div { display:grid; grid-template-columns:minmax(82px,104px) minmax(0,1fr); gap:8px; }
.model-delete__target dd { margin:0; overflow-wrap:anywhere; }
.model-delete__target dt { color:var(--am-text-muted); }
.model-delete__impact h3,.model-delete__impact ul { margin:0; }
.model-delete__impact ul { display:grid; gap:8px; padding:9px 0 0; list-style:none; }
.model-delete__impact li { display:flex; align-items:flex-start; gap:8px; }
.model-delete__impact li svg { flex:none; margin-top:2px; color:var(--am-success-text); }
.model-delete__impact li svg.lucide-trash-2 { color:var(--am-danger-text); }
.model-delete__confirm { display:grid; grid-template-columns:auto minmax(0,1fr); align-items:center; gap:10px; padding-top:12px; border-top:1px solid var(--am-border); }
.model-delete__confirm input { width:100%; min-width:0; padding:9px 10px; border:1px solid var(--am-border-strong); border-radius:var(--am-radius-sm); background:var(--am-surface-raised); color:var(--am-text); }
.model-delete__references :deep(table) { width:100%; min-width:0; table-layout:fixed; }
.model-delete__references :deep(:is(th,td)) { padding:8px; white-space:normal; overflow-wrap:anywhere; }
.model-delete__references th:nth-child(1) { width:42%; }
.model-delete__references th:nth-child(2) { width:29%; }
.model-delete__references th:nth-child(3) { width:16%; }
.model-delete__references th:last-child { width:13%; }
.model-delete__references a { color:var(--am-action-primary-strong); }
.model-delete__runtimes { display:grid; gap:4px; }
.model-delete__runtime { color:var(--am-text-muted); }
.model-delete__runtime::before { display:inline-block; width:7px; height:7px; margin-inline-end:6px; border-radius:50%; background:currentColor; content:''; }
.model-delete__runtime.is-running { color:var(--am-success-text); }
@media (max-width: 460px) { .model-delete__confirm { grid-template-columns:minmax(0,1fr); } }
</style>
