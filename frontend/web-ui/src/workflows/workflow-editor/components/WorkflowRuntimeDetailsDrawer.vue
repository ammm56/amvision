<template>
  <SideDrawer
    :open="open"
    :title="t('workflowEditor.appDetail.runtimeDetailsTitle')"
    :close-label="t('common.close')"
    @close="emit('close')"
  >
    <template v-if="runtime">
      <dl class="workflow-runtime-details">
        <div>
          <dt>{{ t('workflowEditor.appDetail.fields.displayName') }}</dt>
          <dd>{{ runtime.display_name || '-' }}</dd>
        </div>
        <div>
          <dt>{{ t('workflowEditor.appDetail.fields.runtimeId') }}</dt>
          <dd>{{ runtime.workflow_runtime_id }}</dd>
        </div>
        <div>
          <dt>{{ t('workflowEditor.appDetail.fields.version') }}</dt>
          <dd>{{ versionLabel }}</dd>
        </div>
        <div>
          <dt>{{ t('workflowEditor.appDetail.fields.generation') }}</dt>
          <dd>{{ runtime.revision_generation }}</dd>
        </div>
        <div>
          <dt>{{ t('workflowEditor.appDetail.fields.desiredState') }}</dt>
          <dd>{{ runtime.desired_state }}</dd>
        </div>
        <div>
          <dt>{{ t('workflowEditor.appDetail.fields.observedState') }}</dt>
          <dd>{{ runtime.observed_state }}</dd>
        </div>
        <div>
          <dt>{{ t('workflowEditor.appDetail.fields.boundTriggers') }}</dt>
          <dd>{{ triggerSourceCount }}</dd>
        </div>
        <div>
          <dt>{{ t('workflowEditor.appDetail.fields.heartbeat') }}</dt>
          <dd>{{ formatDateTime(runtime.heartbeat_at) }}</dd>
        </div>
        <div>
          <dt>{{ t('workflowEditor.appDetail.fields.updatedAt') }}</dt>
          <dd>{{ formatDateTime(runtime.updated_at) }}</dd>
        </div>
        <div>
          <dt>{{ t('workflowEditor.appDetail.fields.createdAt') }}</dt>
          <dd>{{ formatDateTime(runtime.created_at) }}</dd>
        </div>
      </dl>

      <section class="workflow-runtime-details__section">
        <h3>{{ t('workflowEditor.appDetail.fields.healthSummary') }}</h3>
        <pre class="json-view">{{ formatJson(runtime.health_summary) }}</pre>
      </section>
      <section class="workflow-runtime-details__section">
        <h3>{{ t('workflowEditor.appDetail.fields.lastError') }}</h3>
        <pre class="json-view">{{ runtime.last_error || '-' }}</pre>
      </section>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { formatSystemDateTime } from '@/shared/formatters/date-time'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import type { WorkflowAppRuntime, WorkflowJsonObject } from '../types'

defineProps<{
  open: boolean
  runtime: WorkflowAppRuntime | null
  versionLabel: string
  triggerSourceCount: number
}>()

const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()

function formatDateTime(value: string | null | undefined): string {
  return value ? formatSystemDateTime(value) : '-'
}

function formatJson(value: WorkflowJsonObject): string {
  return Object.keys(value).length > 0 ? JSON.stringify(value, null, 2) : '{}'
}
</script>

<style scoped>
.workflow-runtime-details {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--am-space-md);
  margin: 0;
}

.workflow-runtime-details > div,
.workflow-runtime-details__section {
  min-width: 0;
  padding: var(--am-space-md);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface-soft);
}

.workflow-runtime-details dt,
.workflow-runtime-details__section h3 {
  margin: 0 0 var(--am-space-sm);
  color: var(--am-text-muted);
  font-size: 13px;
  font-weight: 700;
}

.workflow-runtime-details dd {
  margin: 0;
  color: var(--am-text-strong);
  overflow-wrap: anywhere;
}

.workflow-runtime-details__section {
  margin-top: var(--am-space-md);
}

.workflow-runtime-details__section .json-view {
  max-height: 360px;
  margin: 0;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@media (max-width: 620px) {
  .workflow-runtime-details {
    grid-template-columns: 1fr;
  }
}
</style>
