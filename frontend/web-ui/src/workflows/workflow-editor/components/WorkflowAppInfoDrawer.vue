<template>
  <SideDrawer
    :open="open"
    title="应用信息"
    close-label="关闭"
    plain
    size="compact"
    :busy="saving"
    @close="attemptClose"
  >
    <template v-if="appSummary">
      <template v-if="editing">
        <div class="app-drawer-form">
          <label class="app-field">
            <span>应用名称 <em>*</em></span>
            <input
              v-model="draftDisplayName"
              type="text"
              maxlength="120"
              placeholder="请输入应用名称"
              :disabled="saving"
            />
          </label>
          <label class="app-field">
            <span>应用说明</span>
            <textarea
              v-model="draftDescription"
              rows="4"
              maxlength="500"
              placeholder="可选，简要说明用途或产线工位"
              :disabled="saving"
            />
          </label>
          <dl class="app-kv-list app-kv-list--muted">
            <div>
              <dt>所属项目</dt>
              <dd>{{ projectName }}</dd>
            </div>
            <div>
              <dt>最新发布</dt>
              <dd>{{ latestVersionLabel || '未发布' }}</dd>
            </div>
          </dl>
          <InlineError :message="saveError" />
        </div>
      </template>

      <template v-else>
        <dl class="app-kv-list">
          <div>
            <dt>业务名称</dt>
            <dd><strong>{{ appSummary.application.display_name || appSummary.application.application_id }}</strong></dd>
          </div>
          <div>
            <dt>应用说明</dt>
            <dd>{{ appSummary.application.description || '—' }}</dd>
          </div>
          <div class="app-kv-sep" />
          <div>
            <dt>所属项目</dt>
            <dd>{{ projectName }}</dd>
          </div>
          <div>
            <dt>最新发布</dt>
            <dd>{{ latestVersionLabel || '未发布' }}</dd>
          </div>
          <div>
            <dt>运行实例</dt>
            <dd>{{ appSummary.runtimes.length }}</dd>
          </div>
          <div>
            <dt>触发入口</dt>
            <dd>{{ appSummary.triggerCount }}</dd>
          </div>
          <div class="app-kv-sep" />
          <div>
            <dt>创建时间</dt>
            <dd>{{ formatDateTime(appSummary.application.created_at) }}</dd>
          </div>
          <div>
            <dt>更新时间</dt>
            <dd>{{ formatDateTime(appSummary.application.updated_at) }}</dd>
          </div>
          <div class="app-kv-sep" />
          <div>
            <dt>应用 ID</dt>
            <dd class="app-mono-copy">
              <span>{{ appSummary.application.application_id }}</span>
              <button
                type="button"
                class="app-copy-mini"
                title="复制应用 ID"
                @click="copyValue(appSummary.application.application_id)"
              >
                <Copy :size="13" />
              </button>
            </dd>
          </div>
          <div>
            <dt>关联模板</dt>
            <dd class="app-mono-copy">
              <span>{{ appSummary.application.template_id }} / {{ appSummary.application.template_version }}</span>
            </dd>
          </div>
        </dl>
      </template>
    </template>

    <template #footer>
      <template v-if="editing">
        <Button variant="secondary" :disabled="saving" @click="cancelEdit">取消</Button>
        <Button
          variant="primary"
          :disabled="!draftDisplayName.trim() || saving"
          :loading="saving"
          data-app-info-save
          @click="submitEdit"
        >
          保存修改
        </Button>
      </template>
      <template v-else>
        <Button variant="secondary" @click="attemptClose">关闭</Button>
        <Button v-if="canWrite" variant="primary" data-app-info-edit @click="enterEdit">
          编辑信息
        </Button>
      </template>
    </template>
  </SideDrawer>

  <ConfirmDialog
    v-if="discardConfirmOpen"
    title="放弃未保存的修改?"
    message="当前应用信息有未保存的更改，关闭后这些修改将丢失。"
    confirm-label="放弃修改"
    cancel-label="继续编辑"
    confirm-variant="danger"
    @cancel="discardConfirmOpen = false"
    @confirm="confirmDiscard"
  />
</template>

<script setup lang="ts">
import { Copy } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import { getErrorMessage } from '@/shared/api/error'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { updateWorkflowApplicationMetadata } from '../services/workflow-application.service'
import type { WorkflowAppSummary } from '../services/workflow-app.service'
import type { WorkflowApplicationDocument } from '../types'

const props = withDefaults(
  defineProps<{
    open: boolean
    projectId: string
    projectName: string
    appSummary: WorkflowAppSummary | null
    initialEditing?: boolean
    canWrite?: boolean
  }>(),
  {
    initialEditing: false,
    canWrite: false,
  },
)

const emit = defineEmits<{
  close: []
  updated: [doc: WorkflowApplicationDocument]
}>()

const editing = ref(false)
const saving = ref(false)
const saveError = ref<string | null>(null)
const draftDisplayName = ref('')
const draftDescription = ref('')
const discardConfirmOpen = ref(false)

const latestVersionLabel = computed(() => {
  const latest = props.appSummary?.latestVersion
  if (!latest) return ''
  return latest.display_version || `v${latest.version_number}`
})

const isDirty = computed(() => {
  if (!editing.value || !props.appSummary) return false
  const origName = props.appSummary.application.display_name || ''
  const origDesc = props.appSummary.application.description || ''
  return draftDisplayName.value !== origName || draftDescription.value !== origDesc
})

watch(
  () => [props.open, props.appSummary?.application.application_id, props.initialEditing] as const,
  ([isOpen]) => {
    if (!isOpen || !props.appSummary) return
    syncDraft()
    editing.value = props.initialEditing && props.canWrite
    saveError.value = null
    discardConfirmOpen.value = false
  },
  { immediate: true },
)

function syncDraft(): void {
  if (!props.appSummary) return
  draftDisplayName.value = props.appSummary.application.display_name || ''
  draftDescription.value = props.appSummary.application.description || ''
}

function enterEdit(): void {
  syncDraft()
  saveError.value = null
  editing.value = true
}

function cancelEdit(): void {
  if (isDirty.value) {
    discardConfirmOpen.value = true
    return
  }
  editing.value = false
  saveError.value = null
}

function attemptClose(): void {
  if (isDirty.value) {
    discardConfirmOpen.value = true
    return
  }
  editing.value = false
  emit('close')
}

function confirmDiscard(): void {
  discardConfirmOpen.value = false
  editing.value = false
  syncDraft()
  emit('close')
}

async function submitEdit(): Promise<void> {
  if (!props.appSummary || !draftDisplayName.value.trim() || saving.value) return
  saving.value = true
  saveError.value = null
  try {
    const updated = await updateWorkflowApplicationMetadata(
      props.projectId,
      props.appSummary.application.application_id,
      {
        displayName: draftDisplayName.value.trim(),
        description: draftDescription.value.trim(),
      },
    )
    editing.value = false
    emit('updated', updated)
  } catch (err) {
    saveError.value = getErrorMessage(err)
  } finally {
    saving.value = false
  }
}

function formatDateTime(value: string | null | undefined): string {
  return value ? formatSystemDateTime(value) : '—'
}

async function copyValue(text: string): Promise<void> {
  if (!text || typeof navigator === 'undefined' || !navigator.clipboard) return
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // ignore
  }
}
</script>

<style scoped>
.app-kv-list {
  margin: 0;
  display: grid;
  gap: 2px;
}

.app-kv-list > div:not(.app-kv-sep) {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  align-items: start;
  gap: 12px;
  padding: 8px 0;
  font-size: 13px;
}

.app-kv-sep {
  height: 1px;
  margin: 6px 0;
  background: var(--am-border);
}

.app-kv-list dt {
  color: var(--am-text-muted);
}

.app-kv-list dd {
  margin: 0;
  color: var(--am-text-strong);
  overflow-wrap: anywhere;
}

.app-kv-list--muted {
  margin-top: 6px;
}

.app-mono-copy {
  display: flex !important;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-family: var(--am-font-mono);
  font-size: 12px;
}

.app-copy-mini {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
  flex: none;
}

.app-copy-mini:hover {
  background: var(--am-hover-surface);
  color: var(--am-text-strong);
}

.app-drawer-form {
  display: grid;
  gap: 14px;
}

.app-field {
  display: grid;
  gap: 6px;
}

.app-field > span {
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.app-field > span em {
  color: #dc2626;
  font-style: normal;
}

.app-field input,
.app-field textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-input);
  color: var(--am-text-strong);
  font: inherit;
  font-size: 13px;
}
</style>
