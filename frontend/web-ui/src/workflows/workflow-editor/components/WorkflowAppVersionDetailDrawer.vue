<template>
  <SideDrawer
    :open="open"
    title="发布版本详情"
    close-label="关闭"
    plain
    size="compact"
    :busy="saving"
    @close="emit('close')"
  >
    <div v-if="version" class="ver-drawer">
      <div class="ver-drawer__head">
        <strong>{{ version.display_version }}</strong>
        <span class="ver-state-badge" :class="version.state === 'published' ? 'is-ok' : 'is-neutral'">
          {{ version.state === 'published' ? '已发布' : version.state === 'archived' ? '已归档' : version.state }}
        </span>
      </div>

      <dl class="ver-kv">
        <div>
          <dt>版本说明</dt>
          <dd>
            <template v-if="editingMeta">
              <div class="ver-edit-inline">
                <input v-model="draftDisplayVersion" type="text" placeholder="版本名称" :disabled="saving" />
                <textarea v-model="draftReleaseNotes" rows="2" placeholder="版本说明" :disabled="saving" />
                <div class="ver-edit-inline__btns">
                  <Button size="sm" variant="secondary" :disabled="saving" @click="editingMeta = false">取消</Button>
                  <Button size="sm" variant="primary" :loading="saving" @click="saveMeta">保存</Button>
                </div>
              </div>
            </template>
            <div v-else class="ver-note-row">
              <span>{{ version.release_notes || '—' }}</span>
              <button v-if="canWrite" type="button" class="ver-link-btn" @click="startEditMeta">编辑</button>
            </div>
          </dd>
        </div>
        <div>
          <dt>发布时间</dt>
          <dd>{{ formatDateTime(version.completed_at || version.created_at) }}</dd>
        </div>
        <div>
          <dt>输入</dt>
          <dd>{{ inputCount }}</dd>
        </div>
        <div>
          <dt>输出</dt>
          <dd>{{ outputCount }}</dd>
        </div>
      </dl>

      <InlineError :message="detailError" />

      <section class="ver-section">
        <h4>引用实例 {{ referencingRuntimes.length }}</h4>
        <div v-if="referencingRuntimes.length === 0" class="ver-empty-sub">暂无运行实例引用此版本</div>
        <ul v-else class="ver-list">
          <li v-for="rt in referencingRuntimes" :key="rt.workflow_runtime_id">
            <span>{{ rt.display_name || rt.workflow_runtime_id }}</span>
            <span class="ver-dot-label">
              <i class="ver-dot" :class="rt.observed_state === 'running' ? 'is-ok' : rt.observed_state === 'failed' ? 'is-bad' : 'is-neutral'" />
              {{ formatRuntimeState(rt.observed_state) }}
            </span>
          </li>
        </ul>
      </section>

      <details class="ver-tech-box">
        <summary>技术信息</summary>
        <dl class="ver-kv ver-kv--compact">
          <div>
            <dt>版本 ID</dt>
            <dd class="ver-mono">{{ version.workflow_app_version_id }}</dd>
          </div>
          <div>
            <dt>内容指纹</dt>
            <dd class="ver-mono">{{ version.content_fingerprint }}</dd>
          </div>
          <div>
            <dt>接口校验值</dt>
            <dd class="ver-mono">{{ version.contract_fingerprint }}</dd>
          </div>
        </dl>
      </details>
    </div>

    <template #footer>
      <Button variant="secondary" @click="emit('close')">关闭</Button>
      <Button
        v-if="version"
        variant="secondary"
        @click="emit('compare', version.workflow_app_version_id)"
      >
        与草稿比较
      </Button>
      <Button
        v-if="version"
        variant="primary"
        @click="emit('load-editor', version.workflow_app_version_id)"
      >
        载入图编辑
      </Button>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { getErrorMessage } from '@/shared/api/error'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { getWorkflowAppVersion, renameWorkflowAppVersion } from '../services/workflow-application.service'
import type { WorkflowAppRuntime, WorkflowAppVersion, WorkflowAppVersionDetail } from '../types'

const props = withDefaults(
  defineProps<{
    open: boolean
    projectId: string
    applicationId: string
    version: WorkflowAppVersion | null
    referencingRuntimes: WorkflowAppRuntime[]
    canWrite?: boolean
  }>(),
  {
    canWrite: false,
  },
)

const emit = defineEmits<{
  close: []
  compare: [versionId: string]
  'load-editor': [versionId: string]
  updated: [version: WorkflowAppVersion]
}>()

const detail = ref<WorkflowAppVersionDetail | null>(null)
const detailError = ref<string | null>(null)
const editingMeta = ref(false)
const saving = ref(false)
const draftDisplayVersion = ref('')
const draftReleaseNotes = ref('')

const inputCount = computed(() => {
  const inputs = detail.value?.contract?.inputs
  return Array.isArray(inputs) ? inputs.length : '—'
})
const outputCount = computed(() => {
  const outputs = detail.value?.contract?.outputs
  return Array.isArray(outputs) ? outputs.length : '—'
})

watch(
  () => [props.open, props.version?.workflow_app_version_id] as const,
  async ([isOpen, versionId]) => {
    detail.value = null
    detailError.value = null
    editingMeta.value = false
    if (!isOpen || !versionId) return
    try {
      detail.value = await getWorkflowAppVersion(props.projectId, props.applicationId, versionId)
    } catch (err) {
      detailError.value = getErrorMessage(err)
    }
  },
  { immediate: true },
)

function startEditMeta(): void {
  if (!props.version) return
  draftDisplayVersion.value = props.version.display_version
  draftReleaseNotes.value = props.version.release_notes || ''
  editingMeta.value = true
}

async function saveMeta(): Promise<void> {
  if (!props.version || !draftDisplayVersion.value.trim() || saving.value) return
  saving.value = true
  detailError.value = null
  try {
    const updated = await renameWorkflowAppVersion(
      props.projectId,
      props.applicationId,
      props.version.workflow_app_version_id,
      draftDisplayVersion.value.trim(),
      draftReleaseNotes.value.trim(),
    )
    editingMeta.value = false
    emit('updated', updated)
  } catch (err) {
    detailError.value = getErrorMessage(err)
  } finally {
    saving.value = false
  }
}

function formatDateTime(value: string | null | undefined): string {
  return value ? formatSystemDateTime(value) : '—'
}

function formatRuntimeState(state: string): string {
  if (state === 'running') return '运行中'
  if (state === 'stopped') return '已停止'
  if (state === 'failed') return '启动失败'
  if (state === 'starting') return '启动中'
  if (state === 'stopping') return '停止中'
  return state
}
</script>

<style scoped>
.ver-drawer {
  display: grid;
  gap: 14px;
}

.ver-drawer__head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ver-drawer__head strong {
  font-size: 20px;
  color: var(--am-text-strong);
}

.ver-state-badge {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
}

.ver-state-badge.is-ok {
  background: var(--am-action-soft);
  color: var(--am-action-primary);
}

.ver-state-badge.is-neutral {
  background: var(--am-surface-soft);
  color: var(--am-text-muted);
}

.ver-kv {
  margin: 0;
  display: grid;
  gap: 2px;
}

.ver-kv > div {
  display: grid;
  grid-template-columns: 80px minmax(0, 1fr);
  gap: 10px;
  padding: 7px 0;
  font-size: 13px;
}

.ver-kv dt {
  color: var(--am-text-muted);
}

.ver-kv dd {
  margin: 0;
  color: var(--am-text-strong);
  overflow-wrap: anywhere;
}

.ver-note-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.ver-link-btn {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--am-action-primary);
  font-size: 12px;
  cursor: pointer;
}

.ver-edit-inline {
  display: grid;
  gap: 6px;
}

.ver-edit-inline input,
.ver-edit-inline textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 8px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-input);
  color: var(--am-text-strong);
  font: inherit;
  font-size: 13px;
}

.ver-edit-inline__btns {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.ver-section {
  display: grid;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--am-border);
}

.ver-section h4 {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: var(--am-text-strong);
}

.ver-empty-sub {
  font-size: 12px;
  color: var(--am-text-muted);
}

.ver-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
}

.ver-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 0;
  font-size: 13px;
  color: var(--am-text-strong);
}

.ver-dot-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--am-text-muted);
}

.ver-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.ver-dot.is-ok {
  background: var(--am-action-primary);
}

.ver-dot.is-bad {
  background: #dc2626;
}

.ver-dot.is-neutral {
  background: var(--am-text-muted);
}

.ver-tech-box {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  padding: 8px 12px;
  background: var(--am-surface-soft);
}

.ver-tech-box summary {
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.ver-mono {
  font-family: var(--am-font-mono);
  font-size: 12px;
}
</style>
