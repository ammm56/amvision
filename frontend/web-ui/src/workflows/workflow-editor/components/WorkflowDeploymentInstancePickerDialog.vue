<template>
  <ModelPickerDialogShell
    :open="open"
    :loading="loading"
    :title="t('workflowEditor.deploymentPicker.title')"
    :description="t('workflowEditor.deploymentPicker.description', { taskType: taskTypeLabel })"
    :close-label="t('workflowEditor.deploymentPicker.close')"
    :task-type-label="t('workflowEditor.deploymentPicker.nodeTaskType')"
    :task-type-options="[{ label: taskTypeLabel, value: taskType }]"
    :selected-task-type="taskType"
    :list-title="t('workflowEditor.deploymentPicker.deployedInstances')"
    :list-count="deployments.length"
    :detail-title="t('workflowEditor.deploymentPicker.instanceDetails')"
    @close="emit('close')"
  >
    <template #list>
      <div class="workflow-deployment-picker__list-pane">
        <InlineError :message="errorMessage" />
        <div class="workflow-deployment-picker__list-actions">
          <span>{{ t('workflowEditor.deploymentPicker.sortHint') }}</span>
          <Button size="sm" variant="secondary" :disabled="loading" @click="emit('refresh')">
            <RefreshCw :size="14" />
            {{ t('workflowEditor.deploymentPicker.refresh') }}
          </Button>
        </div>
        <EmptyState
          v-if="!loading && !errorMessage && deployments.length === 0"
          :title="t('workflowEditor.deploymentPicker.emptyTitle')"
          :description="t('workflowEditor.deploymentPicker.emptyDescription', { taskType: taskTypeLabel })"
        />
        <div v-else class="workflow-deployment-picker__list">
          <button
            v-for="deployment in deployments"
            :key="deployment.deployment_instance_id"
            type="button"
            class="workflow-deployment-picker__card"
            :class="{ 'is-selected': deployment.deployment_instance_id === selectedDeploymentId }"
            @click="emit('select', deployment.deployment_instance_id)"
          >
            <span class="workflow-deployment-picker__card-heading">
              <strong>{{ deployment.display_name || deployment.deployment_instance_id }}</strong>
              <StatusBadge :tone="statusTone(deployment.status)">{{ humanizeStatusText(deployment.status) }}</StatusBadge>
            </span>
            <span class="workflow-deployment-picker__id">{{ deployment.deployment_instance_id }}</span>
            <span class="workflow-deployment-picker__card-meta">
              <span>{{ deployment.model_name || deployment.model_build_id || deployment.model_version_id }}</span>
              <span>{{ runtimeLabel(deployment) }}</span>
            </span>
          </button>
        </div>
      </div>
    </template>

    <template #detail>
      <div class="workflow-deployment-picker__detail-pane">
        <div v-if="configuredDeploymentMissing" class="workflow-deployment-picker__warning" role="status">
          {{ t('workflowEditor.deploymentPicker.configuredMissing', { deploymentInstanceId: configuredDeploymentId }) }}
        </div>
        <div v-if="selectedDeployment" class="workflow-deployment-picker__detail">
          <header class="workflow-deployment-picker__detail-heading">
            <div>
              <strong>{{ selectedDeployment.display_name || selectedDeployment.deployment_instance_id }}</strong>
              <span>{{ selectedDeployment.deployment_instance_id }}</span>
            </div>
            <StatusBadge :tone="statusTone(selectedDeployment.status)">
              {{ humanizeStatusText(selectedDeployment.status) }}
            </StatusBadge>
          </header>

          <div class="workflow-deployment-picker__detail-grid">
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.taskType') }}</span><strong>{{ selectedDeployment.task_type || taskType }}</strong></div>
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.model') }}</span><strong>{{ selectedDeployment.model_name || '-' }}</strong></div>
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.modelScale') }}</span><strong>{{ selectedDeployment.model_scale || '-' }}</strong></div>
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.sourceKind') }}</span><strong>{{ selectedDeployment.source_kind || '-' }}</strong></div>
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.modelVersionId') }}</span><strong>{{ selectedDeployment.model_version_id || '-' }}</strong></div>
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.modelBuildId') }}</span><strong>{{ selectedDeployment.model_build_id || '-' }}</strong></div>
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.runtime') }}</span><strong>{{ runtimeLabel(selectedDeployment) }}</strong></div>
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.executionMode') }}</span><strong>{{ selectedDeployment.runtime_execution_mode || '-' }}</strong></div>
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.instanceCount') }}</span><strong>{{ selectedDeployment.runtime_configuration.execution.instance_count }}</strong></div>
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.inputSize') }}</span><strong>{{ inputSizeLabel(selectedDeployment.input_size) }}</strong></div>
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.labelCount') }}</span><strong>{{ selectedDeployment.labels?.length ?? 0 }}</strong></div>
            <div><span>{{ t('workflowEditor.deploymentPicker.fields.updatedAt') }}</span><strong>{{ formatSystemDateTime(selectedDeployment.updated_at) }}</strong></div>
          </div>

          <div class="workflow-deployment-picker__apply">
            <span v-if="selectedDeployment.deployment_instance_id === configuredDeploymentId">{{ t('workflowEditor.deploymentPicker.currentInstance') }}</span>
            <span v-else>{{ t('workflowEditor.deploymentPicker.applyHint') }}</span>
            <Button variant="primary" @click="emit('apply')">
              <Check :size="15" />
              {{ t('workflowEditor.deploymentPicker.useInstance') }}
            </Button>
          </div>
        </div>
        <EmptyState
          v-else
          :title="t('workflowEditor.deploymentPicker.detailEmptyTitle')"
          :description="t('workflowEditor.deploymentPicker.detailEmptyDescription')"
        />
      </div>
    </template>
  </ModelPickerDialogShell>
</template>

<script setup lang="ts">
import { Check, RefreshCw } from '@lucide/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ModelTaskType, TaskDeploymentInstance } from '@/modules/deployments/services/deployment.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ModelPickerDialogShell from '@/shared/ui/components/ModelPickerDialogShell.vue'
import { humanizeStatusText } from '@/shared/ui/data-display/status-text'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

const props = defineProps<{
  open: boolean
  loading: boolean
  errorMessage: string | null
  taskType: ModelTaskType
  deployments: TaskDeploymentInstance[]
  selectedDeploymentId: string
  selectedDeployment: TaskDeploymentInstance | null
  configuredDeploymentId: string
  configuredDeploymentMissing: boolean
}>()

const { t } = useI18n()
const taskTypeLabel = computed(() => t(`workflowEditor.deploymentPicker.taskTypes.${props.taskType}`))

const emit = defineEmits<{
  close: []
  refresh: []
  select: [deploymentInstanceId: string]
  apply: []
}>()

function statusTone(status: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = status.trim().toLowerCase()
  if (normalized.includes('running') || normalized.includes('active') || normalized.includes('ready')) return 'success'
  if (normalized.includes('fail') || normalized.includes('error') || normalized.includes('crash')) return 'danger'
  if (normalized.includes('stop')) return 'warning'
  if (normalized.includes('start') || normalized.includes('process')) return 'info'
  return 'neutral'
}

function runtimeLabel(deployment: TaskDeploymentInstance): string {
  const backend = deployment.runtime_backend || '-'
  const precision = deployment.runtime_precision ? deployment.runtime_precision.toUpperCase() : '-'
  const device = deployment.device_name || '-'
  return `${backend} / ${precision} / ${device}`
}

function inputSizeLabel(inputSize: [number, number] | null | undefined): string {
  if (!Array.isArray(inputSize) || inputSize.length < 2) return '-'
  return `${inputSize[0]} × ${inputSize[1]}`
}
</script>

<style scoped>
.workflow-deployment-picker__list-pane,
.workflow-deployment-picker__detail-pane,
.workflow-deployment-picker__detail {
  display: grid;
  gap: 12px;
  min-height: 0;
  align-content: start;
}

.workflow-deployment-picker__list-pane,
.workflow-deployment-picker__detail-pane {
  overflow: auto;
  padding-right: 4px;
}

.workflow-deployment-picker__list-actions,
.workflow-deployment-picker__card-heading,
.workflow-deployment-picker__detail-heading,
.workflow-deployment-picker__apply {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.workflow-deployment-picker__list-actions,
.workflow-deployment-picker__apply {
  color: var(--muted);
  font-size: 12px;
}

.workflow-deployment-picker__list {
  display: grid;
  gap: 10px;
}

.workflow-deployment-picker__card {
  display: grid;
  gap: 8px;
  width: 100%;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  color: var(--text);
  background: var(--summary-bg);
  text-align: left;
  cursor: pointer;
}

.workflow-deployment-picker__card:hover,
.workflow-deployment-picker__card.is-selected {
  border-color: var(--accent);
  background: var(--selected-row-bg);
}

.workflow-deployment-picker__card-heading strong,
.workflow-deployment-picker__id,
.workflow-deployment-picker__card-meta span,
.workflow-deployment-picker__detail-heading strong,
.workflow-deployment-picker__detail-heading span,
.workflow-deployment-picker__detail-grid strong {
  overflow-wrap: anywhere;
}

.workflow-deployment-picker__id,
.workflow-deployment-picker__card-meta,
.workflow-deployment-picker__detail-heading span {
  color: var(--muted);
  font-size: 12px;
}

.workflow-deployment-picker__card-meta {
  display: grid;
  gap: 4px;
}

.workflow-deployment-picker__detail-heading > div {
  display: grid;
  gap: 4px;
}

.workflow-deployment-picker__detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.workflow-deployment-picker__detail-grid > div,
.workflow-deployment-picker__warning {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--summary-bg);
}

.workflow-deployment-picker__detail-grid span {
  color: var(--muted);
  font-size: 12px;
}

.workflow-deployment-picker__warning {
  border-color: color-mix(in srgb, var(--warning) 46%, var(--line));
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 12%, var(--summary-bg));
}

.workflow-deployment-picker__apply {
  padding-top: 4px;
}

@media (max-width: 720px) {
  .workflow-deployment-picker__detail-grid { grid-template-columns: 1fr; }
  .workflow-deployment-picker__apply { align-items: flex-start; flex-direction: column; }
}
</style>
