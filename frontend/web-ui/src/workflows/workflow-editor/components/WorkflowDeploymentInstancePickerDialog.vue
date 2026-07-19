<template>
  <ModelPickerDialogShell
    :open="open"
    :loading="loading"
    kicker="MODEL INFERENCE"
    title="选择发布实例"
    :description="`仅显示当前项目中适用于 ${taskTypeLabel} 节点的部署实例，确认后自动填写 Deployment Instance Id。`"
    close-label="关闭发布实例选择"
    task-type-label="节点推理类型"
    :task-type-options="[{ label: taskTypeLabel, value: taskType }]"
    :selected-task-type="taskType"
    list-title="已部署实例"
    :list-count="deployments.length"
    detail-title="实例详情"
    @close="emit('close')"
  >
    <template #list>
      <div class="workflow-deployment-picker__list-pane">
        <InlineError :message="errorMessage" />
        <div class="workflow-deployment-picker__list-actions">
          <span>按运行状态和更新时间排序</span>
          <Button size="sm" variant="secondary" :disabled="loading" @click="emit('refresh')">
            <RefreshCw :size="14" />
            刷新
          </Button>
        </div>
        <EmptyState
          v-if="!loading && !errorMessage && deployments.length === 0"
          title="暂无可选部署实例"
          :description="`当前项目没有 ${taskTypeLabel} 部署实例，请先在部署页面创建实例。`"
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
          当前节点配置的实例 {{ configuredDeploymentId }} 已不在可用列表中。请选择新的部署实例。
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
            <div><span>任务类型</span><strong>{{ selectedDeployment.task_type || taskType }}</strong></div>
            <div><span>模型</span><strong>{{ selectedDeployment.model_name || '-' }}</strong></div>
            <div><span>模型 Scale</span><strong>{{ selectedDeployment.model_scale || '-' }}</strong></div>
            <div><span>来源类型</span><strong>{{ selectedDeployment.source_kind || '-' }}</strong></div>
            <div><span>ModelVersion id</span><strong>{{ selectedDeployment.model_version_id || '-' }}</strong></div>
            <div><span>ModelBuild id</span><strong>{{ selectedDeployment.model_build_id || '-' }}</strong></div>
            <div><span>Runtime</span><strong>{{ runtimeLabel(selectedDeployment) }}</strong></div>
            <div><span>执行模式</span><strong>{{ selectedDeployment.runtime_execution_mode || '-' }}</strong></div>
            <div><span>实例数</span><strong>{{ selectedDeployment.instance_count }}</strong></div>
            <div><span>输入尺寸</span><strong>{{ inputSizeLabel(selectedDeployment.input_size) }}</strong></div>
            <div><span>标签数</span><strong>{{ selectedDeployment.labels?.length ?? 0 }}</strong></div>
            <div><span>更新时间</span><strong>{{ formatSystemDateTime(selectedDeployment.updated_at) }}</strong></div>
          </div>

          <div class="workflow-deployment-picker__apply">
            <span v-if="selectedDeployment.deployment_instance_id === configuredDeploymentId">当前节点正在使用此实例</span>
            <span v-else>选择后只更新当前节点参数，保存应用时持久化。</span>
            <Button variant="primary" @click="emit('apply')">
              <Check :size="15" />
              使用此部署实例
            </Button>
          </div>
        </div>
        <EmptyState
          v-else
          title="请选择部署实例"
          description="选择左侧实例后，这里会显示模型来源与 runtime 详细信息。"
        />
      </div>
    </template>
  </ModelPickerDialogShell>
</template>

<script setup lang="ts">
import { Check, RefreshCw } from '@lucide/vue'

import type { ModelTaskType, TaskDeploymentInstance } from '@/modules/deployments/services/deployment.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ModelPickerDialogShell from '@/shared/ui/components/ModelPickerDialogShell.vue'
import { humanizeStatusText } from '@/shared/ui/data-display/status-text'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

defineProps<{
  open: boolean
  loading: boolean
  errorMessage: string | null
  taskType: ModelTaskType
  taskTypeLabel: string
  deployments: TaskDeploymentInstance[]
  selectedDeploymentId: string
  selectedDeployment: TaskDeploymentInstance | null
  configuredDeploymentId: string
  configuredDeploymentMissing: boolean
}>()

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
  border-color: #f2c66d;
  color: #8a4b00;
  background: #fff4d6;
}

.workflow-deployment-picker__apply {
  padding-top: 4px;
}

@media (max-width: 720px) {
  .workflow-deployment-picker__detail-grid { grid-template-columns: 1fr; }
  .workflow-deployment-picker__apply { align-items: flex-start; flex-direction: column; }
}
</style>
