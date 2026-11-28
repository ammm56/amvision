<template>
  <SideDrawer
    :open="open"
    title="复制应用"
    close-label="关闭"
    plain
    size="compact"
    :busy="busy"
    @close="emit('close')"
  >
    <div v-if="sourceApp" class="app-copy-form">
      <div class="app-copy-readonly">
        <span class="app-copy-label">来源应用</span>
        <div class="app-copy-box">{{ sourceApp.application.display_name || sourceApp.application.application_id }}</div>
      </div>

      <div class="app-copy-readonly">
        <span class="app-copy-label">来源版本</span>
        <div class="app-copy-box">
          {{ sourceApp.latestVersion ? sourceApp.latestVersion.display_version : '当前草稿' }}
        </div>
      </div>

      <label class="app-copy-field">
        <span><em>*</em> 新应用名称</span>
        <input
          v-model="displayName"
          type="text"
          maxlength="120"
          placeholder="请输入新应用名称"
          :disabled="busy"
        />
      </label>

      <label class="app-copy-field">
        <span><em>*</em> 新应用 ID</span>
        <input
          v-model="targetApplicationId"
          type="text"
          maxlength="120"
          placeholder="例如 workflow-app-copy"
          :disabled="busy"
        />
      </label>

      <label class="app-copy-field">
        <span>应用说明</span>
        <textarea
          v-model="description"
          rows="3"
          maxlength="500"
          placeholder="可选，复制后可单独编辑"
          :disabled="busy"
        />
      </label>

      <p class="app-copy-hint">复制流程与配置，不复制运行实例和触发入口。</p>
      <InlineError :message="errorMessage" />
    </div>

    <template #footer>
      <Button variant="secondary" :disabled="busy" @click="emit('close')">取消</Button>
      <Button
        variant="primary"
        :disabled="!displayName.trim() || !targetApplicationId.trim() || busy"
        :loading="busy"
        data-app-copy-submit
        @click="submitCopy"
      >
        创建副本
      </Button>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

import { getErrorMessage } from '@/shared/api/error'
import Button from '@/shared/ui/components/Button.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { copyWorkflowApplication } from '../services/workflow-application.service'
import type { WorkflowAppSummary } from '../services/workflow-app.service'
import type { WorkflowApplicationDocument } from '../types'

const props = defineProps<{
  open: boolean
  projectId: string
  sourceApp: WorkflowAppSummary | null
}>()

const emit = defineEmits<{
  close: []
  copied: [doc: WorkflowApplicationDocument]
}>()

const displayName = ref('')
const targetApplicationId = ref('')
const description = ref('')
const busy = ref(false)
const errorMessage = ref<string | null>(null)

watch(
  () => [props.open, props.sourceApp?.application.application_id] as const,
  ([isOpen]) => {
    if (!isOpen || !props.sourceApp) return
    const baseName = props.sourceApp.application.display_name || props.sourceApp.application.application_id
    displayName.value = `${baseName} · 副本`
    const suffix = Date.now().toString(36).slice(-4)
    targetApplicationId.value = `${props.sourceApp.application.application_id}-copy-${suffix}`
    description.value = props.sourceApp.application.description || ''
    errorMessage.value = null
  },
  { immediate: true },
)

async function submitCopy(): Promise<void> {
  if (!props.sourceApp || !displayName.value.trim() || !targetApplicationId.value.trim() || busy.value) {
    return
  }
  busy.value = true
  errorMessage.value = null
  try {
    const doc = await copyWorkflowApplication(
      props.projectId,
      props.sourceApp.application.application_id,
      {
        targetApplicationId: targetApplicationId.value.trim(),
        displayName: displayName.value.trim(),
        description: description.value.trim(),
      },
    )
    emit('copied', doc)
  } catch (err) {
    errorMessage.value = getErrorMessage(err)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.app-copy-form {
  display: grid;
  gap: 14px;
}

.app-copy-readonly,
.app-copy-field {
  display: grid;
  gap: 6px;
}

.app-copy-label,
.app-copy-field > span {
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.app-copy-field > span em {
  color: #dc2626;
  font-style: normal;
}

.app-copy-box {
  padding: 8px 10px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
  color: var(--am-text-strong);
  font-size: 13px;
}

.app-copy-field input,
.app-copy-field textarea {
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

.app-copy-hint {
  margin: 0;
  font-size: 12px;
  color: var(--am-text-muted);
}
</style>
