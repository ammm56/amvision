<template>
  <Teleport to="body">
    <ConfirmDialog
      :title="blocked ? (zh ? '无法删除模型产物' : 'Cannot delete model artifact') : (zh ? '删除模型产物' : 'Delete model artifact')"
      :confirm-label="blocked ? (zh ? '查看引用' : 'View references') : (zh ? '删除产物' : 'Delete artifact')"
      :cancel-label="blocked ? (zh ? '关闭' : 'Close') : (zh ? '取消' : 'Cancel')"
      :show-confirm="blocked ? total > 0 : !!preview?.revision && !uncertain"
      :confirm-variant="blocked ? 'primary' : 'danger'"
      :confirm-disabled="!blocked && (!filename || confirmation !== filename)"
      :busy="deleting" scroll-body @cancel="$emit('close')" @confirm="blocked ? $emit('references') : remove()"
    >
      <template #title-icon><CircleAlert v-if="blocked" class="artifact-delete__warning-icon" :size="22" /><Trash2 v-else class="artifact-delete__danger-icon" :size="20" /></template>
      <template v-if="blocked" #leading-actions><Button type="button" variant="ghost" size="sm" @click="check">{{ zh ? '重新检查' : 'Check again' }}</Button></template>
      <div v-if="blocked" class="artifact-delete__blocked">
        <p role="alert"><strong>{{ total ? (zh ? '该模型产物仍被部署引用，无法删除。' : 'Deployments still reference this artifact.') : preview?.reason }}</strong></p>
        <p v-if="total" class="artifact-delete__hint">{{ zh ? '停止部署不会解除绑定。解除绑定后可重新检查。' : 'Stopping a deployment does not remove its binding. Check again after removing the binding.' }}</p>
      </div>
      <div class="artifact-delete__target" :class="{ 'artifact-delete__target--blocked': blocked }">
        <Box :size="27" aria-hidden="true" />
        <div><strong>{{ modelName }} · {{ versionLabel ?? '—' }}</strong><p>{{ format }} {{ build.runtime_precision.toUpperCase() }} / {{ filenames.join('、') || '—' }}</p></div>
      </div>
      <p v-if="loading" role="status">{{ zh ? '正在检查引用…' : 'Checking references…' }}</p>
      <template v-else-if="blocked">
        <template v-if="references.length">
          <h3>{{ zh ? `引用此产物的部署（${total}）` : `Referencing deployments (${total})` }}</h3>
          <table class="artifact-delete__references">
            <thead><tr><th scope="col">{{ zh ? '部署名称' : 'Deployment' }}</th><th scope="col">{{ zh ? '状态' : 'Status' }}</th><th scope="col">{{ zh ? '说明' : 'Binding' }}</th></tr></thead>
            <tbody><tr v-for="item in references" :key="item.deployment_id"><td>{{ item.display_name }}</td><td>{{ stateText(item.runtime_states) }}</td><td>{{ zh ? '仍绑定此产物' : 'Still bound' }}</td></tr></tbody>
          </table>
        </template>
      </template>
      <template v-else-if="preview?.revision">
        <section class="artifact-delete__impact">
          <h3><CircleAlert :size="18" />{{ zh ? '删除后影响' : 'Impact' }}</h3>
          <ul><li>{{ zh ? `删除 1 个 ${format} 产物及其文件。` : `Removes this ${format} artifact and its files.` }}</li>
            <li>{{ zh ? '保留此模型版本、其他产物及训练和转换任务历史。' : 'Keeps this model version, other artifacts, and training and conversion history.' }}</li></ul>
        </section>
        <section class="artifact-delete__check">
          <h3><Link2 :size="18" />{{ zh ? '引用检查' : 'Reference check' }}<span>{{ zh ? '0 项' : '0 references' }}</span></h3>
          <p>{{ zh ? '未发现直接引用。' : 'No direct references found.' }}</p>
        </section>
        <label v-if="!uncertain" class="artifact-delete__input">{{ zh ? '输入产物文件名确认' : 'Enter the artifact filename to confirm' }}
          <input v-model="confirmation" :placeholder="filename" :disabled="deleting || !filename" autocomplete="off" spellcheck="false" />
        </label>
        <p v-if="!filename" role="alert">{{ zh ? '产物没有可确认的文件名。' : 'No artifact filename is available for confirmation.' }}</p>
      </template>
      <p v-if="error" role="alert" class="artifact-delete__error">{{ error }} <Button v-if="!uncertain && !blocked" variant="ghost" size="sm" @click="check">{{ zh ? '重试检查' : 'Retry check' }}</Button></p>
    </ConfirmDialog>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Box, CircleAlert, Link2, Trash2 } from '@lucide/vue'
import { ApiError } from '@/shared/api/error'
import { previewModelBuildDeletion, submitResourceDeletion, type ModelVersionDeletionPreview } from '@/shared/api/resource-deletion'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import { listModelVersionReferences, type ModelDeploymentReference, type PlatformBaseModelBuild } from '../services/model.service'

const props = defineProps<{ zh: boolean; projectId: string; modelId: string; modelName: string; versionId: string; versionLabel?: string; build: PlatformBaseModelBuild; format: string }>()
const emit = defineEmits<{ close: []; references: []; deleted: []; uncertain: [] }>()
const preview = ref<ModelVersionDeletionPreview | null>(null)
const confirmation = ref('')
const references = ref<ModelDeploymentReference[]>([])
const total = ref(0)
const error = ref('')
const loading = ref(true)
const deleting = ref(false)
const uncertain = ref(false)
const filenames = computed(() => props.build.files.map(file => file.storage_uri.split(/[\\/]/).pop() || file.logical_name))
const filename = computed(() => filenames.value[0] || '')
const blocked = computed(() => !!preview.value?.blocked)
let serial = 0

function stateText(states: Record<string, string>): string {
  const labels: Record<string, string> = props.zh ? { active: '启用', running: '运行中', stopped: '已停止', starting: '启动中', failed: '失败', degraded: '异常' } : { active: 'Enabled', running: 'Running', stopped: 'Stopped', starting: 'Starting', failed: 'Failed', degraded: 'Degraded' }
  return [...new Set(Object.values(states))].map(state => labels[state] || state).join(' / ') || '—'
}

async function check(): Promise<void> {
  const request = ++serial
  preview.value = null; references.value = []; total.value = 0; confirmation.value = ''; error.value = ''; loading.value = true
  try {
    const result = await previewModelBuildDeletion(props.projectId, props.build.model_build_id)
    if (request !== serial) return
    if (result.blocked) {
      try {
        const list = await listModelVersionReferences({ projectId: props.projectId, modelId: props.modelId, versionId: props.versionId, buildId: props.build.model_build_id, offset: 0, limit: 4 })
        if (request !== serial) return
        references.value = list.items; total.value = list.total
      } catch {
        if (request !== serial) return
        error.value = props.zh ? '无法读取部署引用列表。' : 'Could not load the deployment references.'
      }
    }
    preview.value = result
  } catch { if (request === serial) error.value = props.zh ? '无法检查删除范围。' : 'Could not check the deletion scope.' }
  finally { if (request === serial) loading.value = false }
}

async function remove(): Promise<void> {
  if (!preview.value?.revision || blocked.value || !filename.value || confirmation.value !== filename.value || deleting.value || uncertain.value) return
  deleting.value = true
  try {
    await submitResourceDeletion('model-build', props.build.model_build_id, props.projectId, preview.value.revision)
    emit('deleted')
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 409) await check()
    else if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500 && cause.status !== 408 && cause.status !== 429) {
      preview.value = null
      error.value = cause.message
    } else {
      uncertain.value = true
      error.value = props.zh ? '未能确认删除结果。关闭后将刷新版本产物列表。' : 'Could not confirm deletion. Close to refresh the version artifacts.'
      emit('uncertain')
    }
  } finally { deleting.value = false }
}

onMounted(check)
onBeforeUnmount(() => { serial++ })
</script>

<style scoped>
.artifact-delete__target { display:flex; gap:14px; align-items:center; overflow-wrap:anywhere; }
.artifact-delete__target--blocked { padding:12px; border-radius:6px; background:var(--am-surface); border:1px solid var(--am-border); }
.artifact-delete__blocked p:first-child,.artifact-delete__references { margin:0; }
.artifact-delete__references { margin-top:-5px; }
.artifact-delete__target svg { flex:none; color:var(--am-text-muted); }
.artifact-delete__target p,.artifact-delete__hint,.artifact-delete__check p { margin:4px 0 0; color:var(--am-text-muted); }
.artifact-delete__impact { margin:16px 0; padding:12px 14px; background:var(--am-warning-surface); color:var(--am-warning-text); border-radius:6px; }
.artifact-delete__impact ul { margin:6px 0 0; padding-inline-start:23px; }
.artifact-delete__impact h3,.artifact-delete__check h3 { display:flex; align-items:center; gap:8px; margin:0; }
.artifact-delete__check { border-bottom:1px solid var(--am-border); padding-bottom:14px; }
.artifact-delete__check h3 span { margin-inline-start:auto; color:var(--am-text-muted); font-weight:400; }
.artifact-delete__input { display:grid; gap:7px; margin-top:14px; }
.artifact-delete__input input { min-width:0; padding:8px 10px; background:var(--am-surface-raised); color:var(--am-text); border:1px solid var(--am-border); border-radius:5px; font:inherit; }
.artifact-delete__references { width:100%; table-layout:fixed; border-collapse:collapse; margin-bottom:9px; }
.artifact-delete__references th,.artifact-delete__references td { padding:7px 8px; text-align:left; border:1px solid var(--am-border); overflow-wrap:anywhere; }
.artifact-delete__references th { background:var(--am-surface); }
.artifact-delete__warning-icon { color:var(--am-warning-icon); margin-inline-end:8px; vertical-align:middle; }
.artifact-delete__danger-icon { margin-inline-end:8px; vertical-align:middle; }
.artifact-delete__danger-icon,.artifact-delete__error { color:var(--am-danger-text); }
</style>
