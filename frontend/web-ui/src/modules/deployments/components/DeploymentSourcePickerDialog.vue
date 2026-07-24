<template>
  <ModelPickerDialogShell :open="open" :loading="loading" :kicker="t('deploymentOps.sourcePicker.kicker')" :title="t('deploymentOps.sourcePicker.title')" :description="t('deploymentOps.sourcePicker.description')" :close-label="t('deploymentOps.sourcePicker.close')" :task-type-label="t('deploymentOps.sourcePicker.taskType')" :task-type-options="taskTypeOptions" :selected-task-type="taskType" :list-title="t('deploymentOps.sourcePicker.modelList')" :list-count="models.length" :detail-title="t('deploymentOps.sourcePicker.modelDetail')" @close="$emit('close')" @change-task-type="emitTaskType">
    <template #list>

          <EmptyState
            v-if="!loading && models.length === 0"
            :title="t('deploymentOps.sourcePicker.emptyModelsTitle')"
            :description="t('deploymentOps.sourcePicker.emptyModelsDescription')"
          />

          <div v-else class="deployment-source-picker__grid">
            <button
              v-for="model in models"
              :key="model.model_id"
              type="button"
              class="deployment-source-card"
              :class="{ 'is-selected': model.model_id === selectedModelId }"
              @click.stop="$emit('select-model', model.model_id)"
            >
              <div class="deployment-source-card__identity">
                <strong>{{ model.model_name }}</strong>
                <span>{{ model.model_id }}</span>
              </div>
              <div class="deployment-source-card__meta">
                <span class="deployment-source-pill">{{ model.model_type }}</span>
                <span class="deployment-source-pill">{{ model.task_type }}</span>
                <span class="deployment-source-pill">Scale · {{ model.model_scale }}</span>
              </div>
              <div class="deployment-source-card__footer">
                <span>{{ t('deploymentOps.sourcePicker.versionCount', { count: model.version_count }) }}</span>
                <span>{{ t('deploymentOps.sourcePicker.buildCount', { count: model.build_count }) }}</span>
              </div>
            </button>
          </div>
    </template>
    <template #detail>

          <div v-if="selectedModelDetail" class="deployment-source-detail">
            <div class="deployment-source-detail__summary">
              <div class="deployment-source-detail__identity">
                <strong>{{ selectedModelDetail.model_name }}</strong>
                <span>{{ selectedModelDetail.model_id }}</span>
              </div>
              <div class="deployment-source-card__meta">
                <span class="deployment-source-pill">{{ selectedModelDetail.model_type }}</span>
                <span class="deployment-source-pill">{{ selectedModelDetail.task_type }}</span>
                <span class="deployment-source-pill">Scale · {{ selectedModelDetail.model_scale }}</span>
              </div>
            </div>

            <section class="deployment-source-group">
              <header class="deployment-source-picker__section-heading">
                <strong>{{ t('deploymentOps.sourcePicker.completedBuilds') }}</strong>
                <span class="deployment-source-picker__section-count">{{ selectedModelDetail.builds.length }}</span>
              </header>
              <div
                v-if="selectedModelDetail.builds.length > 0"
                class="compact-list deployment-source-list deployment-source-list--builds"
              >
                <div
                  v-for="build in selectedModelDetail.builds"
                  :key="build.model_build_id"
                  class="compact-list__item"
                  :class="{
                    'is-active': build.model_build_id === selectedBuildId,
                    'is-disabled': !isBuildSelectable(build),
                  }"
                >
                  <div class="deployment-source-build-meta">
                    <strong>{{ build.model_build_id }}</strong>
                    <span>
                      {{ build.build_format }} · {{ build.runtime_backend }} ·
                      {{ build.runtime_precision.toUpperCase() }}
                    </span>
                    <span
                      v-if="buildRuntimeUnavailableReason(build)"
                      class="deployment-source-pill deployment-source-pill--warning"
                    >
                      {{ buildRuntimeUnavailableReason(build) }}
                    </span>
                  </div>
                  <div class="table-actions">
                    <Button
                      size="sm"
                      variant="secondary"
                      :disabled="!isBuildSelectable(build)"
                      :title="buildRuntimeUnavailableReason(build) || t('deploymentOps.sourcePicker.useBuild')"
                      @click.stop="applyBuildSelection(build)"
                    >
                      {{ isBuildSelectable(build) ? t('deploymentOps.sourcePicker.useBuild') : t('deploymentOps.sourcePicker.environmentUnavailable') }}
                    </Button>
                  </div>
                </div>
              </div>
              <div v-else class="deployment-source-detail__empty">
                <strong>{{ t('deploymentOps.sourcePicker.emptyBuildsTitle') }}</strong>
                <span>{{ t('deploymentOps.sourcePicker.emptyBuildsDescription') }}</span>
              </div>
            </section>

            <section class="deployment-source-group">
              <header class="deployment-source-picker__section-heading">
                <strong>{{ t('deploymentOps.sourcePicker.directVersions') }}</strong>
                <span class="deployment-source-picker__section-count">{{ selectedModelDetail.versions.length }}</span>
              </header>
              <div
                v-if="selectedModelDetail.versions.length > 0"
                class="compact-list deployment-source-list"
              >
                <div
                  v-for="version in selectedModelDetail.versions"
                  :key="version.model_version_id"
                  class="compact-list__item"
                  :class="{ 'is-active': version.model_version_id === selectedVersionId && !selectedBuildId }"
                >
                  <div>
                    <strong>{{ version.model_version_id }}</strong>
                    <span>{{ version.source_kind }}</span>
                  </div>
                  <div class="table-actions">
                    <Button size="sm" variant="secondary" @click.stop="$emit('apply-source', versionSelection(version))">
                      {{ t('deploymentOps.sourcePicker.useVersion') }}
                    </Button>
                  </div>
                </div>
              </div>
              <div v-else class="deployment-source-detail__empty">
                <strong>{{ t('deploymentOps.sourcePicker.emptyVersionsTitle') }}</strong>
                <span>{{ t('deploymentOps.sourcePicker.emptyVersionsDescription') }}</span>
              </div>
            </section>
          </div>

          <div v-else class="deployment-source-detail__empty deployment-source-detail__empty--large">
            <strong>{{ t('deploymentOps.sourcePicker.selectModelTitle') }}</strong>
            <span>{{ t('deploymentOps.sourcePicker.selectModelDescription') }}</span>
          </div>
    </template>
  </ModelPickerDialogShell>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type {
  DeploymentSourceModelBuild,
  DeploymentSourceModelDetail,
  DeploymentSourceModelSummary,
  DeploymentSourceModelVersionDetail,
} from '@/modules/models/services/model.service'
import Button from '@/shared/ui/components/Button.vue'
import ModelPickerDialogShell from '@/shared/ui/components/ModelPickerDialogShell.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import { hasCudaDevice } from '../deployment-device-support'
import type { ModelTaskType } from '../services/deployment.service'
import type { DeploymentSourceSelection } from './deployment-source.types'

const { t } = useI18n()

interface TaskTypeOption {
  label: string
  value: ModelTaskType
}

const props = defineProps<{
  open: boolean
  loading: boolean
  taskType: ModelTaskType
  taskTypeOptions: TaskTypeOption[]
  models: DeploymentSourceModelSummary[]
  selectedModelId: string
  selectedModelDetail: DeploymentSourceModelDetail | null
  selectedVersionId: string
  selectedBuildId: string
  devices: Record<string, unknown> | null
}>()

const emit = defineEmits<{
  close: []
  'change-task-type': [taskType: ModelTaskType]
  'select-model': [modelId: string]
  'apply-source': [selection: DeploymentSourceSelection]
}>()

function emitTaskType(taskType: string): void {
  if (props.taskTypeOptions.some((option) => option.value === taskType)) {
    emit('change-task-type', taskType as ModelTaskType)
  }
}

function buildSelection(build: DeploymentSourceModelBuild): DeploymentSourceSelection {
  const model = props.selectedModelDetail
  if (!model) {
    throw new Error('missing selected model detail')
  }
  return {
    sourceKind: 'model-build',
    modelId: model.model_id,
    modelName: model.model_name,
    modelType: model.model_type,
    modelScale: model.model_scale,
    taskType: props.taskType,
    modelVersionId: build.source_model_version_id,
    modelBuildId: build.model_build_id,
    buildFormat: build.build_format,
    runtimeProfileId: build.runtime_profile_id ?? '',
    runtimeBackend: build.runtime_backend,
    runtimePrecision: build.runtime_precision,
    buildMetadata: { ...build.metadata },
  }
}

function applyBuildSelection(build: DeploymentSourceModelBuild): void {
  if (!isBuildSelectable(build)) {
    return
  }
  emit('apply-source', buildSelection(build))
}

function isBuildSelectable(build: DeploymentSourceModelBuild): boolean {
  return buildRuntimeUnavailableReason(build) === ''
}

function buildRuntimeUnavailableReason(build: DeploymentSourceModelBuild): string {
  const runtimeBackend = String(build.runtime_backend ?? '').trim().toLowerCase()
  if (runtimeBackend !== 'tensorrt') {
    return ''
  }
  if (!hasCudaDevice(props.devices)) {
    return t('deploymentOps.sourcePicker.cudaUnavailable')
  }
  const tensorrt = readRecord(props.devices, 'tensorrt')
  if (tensorrt?.installed !== true) {
    return t('deploymentOps.sourcePicker.tensorrtUnavailable')
  }
  return ''
}

function readRecord(
  record: Record<string, unknown> | null | undefined,
  key: string,
): Record<string, unknown> | null {
  const value = record?.[key]
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function versionSelection(version: DeploymentSourceModelVersionDetail): DeploymentSourceSelection {
  const model = props.selectedModelDetail
  if (!model) {
    throw new Error('missing selected model detail')
  }
  return {
    sourceKind: 'model-version',
    modelId: model.model_id,
    modelName: model.model_name,
    modelType: model.model_type,
    modelScale: model.model_scale,
    taskType: props.taskType,
    modelVersionId: version.model_version_id,
    modelBuildId: '',
    buildFormat: '',
    runtimeProfileId: '',
    runtimeBackend: 'pytorch',
    runtimePrecision: 'fp32',
    buildMetadata: {},
  }
}
</script>

<style scoped>
.deployment-source-card__meta,
.deployment-source-card__footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.deployment-source-detail,
.deployment-source-group {
  display: grid;
  gap: 12px;
  min-height: 0;
  align-content: start;
}

.deployment-source-detail {
  overflow: auto;
  padding-right: 4px;
}

.deployment-source-picker__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  align-content: start;
  overflow: auto;
  padding-right: 4px;
}

.deployment-source-card,
.deployment-source-detail__summary,
.deployment-source-detail__empty {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--summary-bg);
}

.deployment-source-card {
  display: grid;
  gap: 12px;
  width: 100%;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.deployment-source-card:hover,
.deployment-source-card.is-selected,
.compact-list__item.is-active {
  border-color: var(--accent);
  background: var(--selected-row-bg);
}

.compact-list__item.is-disabled {
  opacity: 0.72;
}

.deployment-source-card__identity,
.deployment-source-detail__identity,
.deployment-source-build-meta,
.deployment-source-detail__empty {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.deployment-source-list {
  min-width: 0;
}

.deployment-source-list--builds {
  max-height: min(360px, 42vh);
  overflow: auto;
  padding-right: 4px;
}

.compact-list__item {
  align-items: flex-start;
  min-width: 0;
}

.table-actions {
  flex: 0 0 auto;
}

.deployment-source-card__identity strong,
.deployment-source-card__identity span,
.deployment-source-detail__identity strong,
.deployment-source-detail__identity span,
.deployment-source-build-meta strong,
.deployment-source-build-meta span,
.deployment-source-detail__empty strong,
.deployment-source-detail__empty span {
  overflow-wrap: anywhere;
}

.deployment-source-card__identity span,
.deployment-source-detail__identity span,
.deployment-source-build-meta span,
.deployment-source-detail__empty span,
.deployment-source-card__footer {
  color: var(--muted);
  font-size: 12px;
}

.deployment-source-pill {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  color: var(--badge-neutral-text);
  background: var(--badge-neutral-bg);
  font-size: 12px;
  font-weight: 700;
}

.deployment-source-pill--warning {
  color: #8a4b00;
  border-color: #f2c66d;
  background: #fff4d6;
}

.deployment-source-detail__summary {
  display: grid;
  gap: 12px;
  align-content: start;
}

.deployment-source-detail__empty--large {
  min-height: 200px;
  align-content: center;
}

</style>
