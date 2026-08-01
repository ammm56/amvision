<template>
  <ModelPickerDialogShell
    :open="open"
    :loading="loading"
    compact
    :title="t('deploymentOps.sourcePicker.title')"
    :close-label="t('deploymentOps.sourcePicker.close')"
    :task-type-options="taskTypeOptions"
    :selected-task-type="taskType"
    :list-title="t('deploymentOps.sourcePicker.modelSelection')"
    :list-count="modelTypeGroups.length"
    :detail-title="t('deploymentOps.sourcePicker.versionUsage')"
    @close="$emit('close')"
    @change-task-type="emitTaskType"
  >
    <template #list>
      <EmptyState
        v-if="!loading && projectModels.length === 0"
        :title="t('deploymentOps.sourcePicker.emptyModelsTitle')"
        :description="t('deploymentOps.sourcePicker.emptyModelsDescription')"
      />

      <div v-else class="deployment-model-selection">
        <section class="deployment-model-selection__stage">
          <header class="deployment-model-selection__heading">
            <span class="deployment-model-selection__step">1</span>
            <strong>{{ t('deploymentOps.sourcePicker.modelName') }}</strong>
          </header>
          <div
            class="deployment-model-family-list"
            role="listbox"
            :aria-label="t('deploymentOps.sourcePicker.modelName')"
          >
            <button
              v-for="group in modelTypeGroups"
              :key="group.key"
              type="button"
              class="deployment-model-family"
              :class="{ 'is-selected': group.key === selectedModelTypeGroup?.key }"
              :aria-selected="group.key === selectedModelTypeGroup?.key"
              @click.stop="selectModelTypeGroup(group)"
            >
              <strong>{{ group.name }}</strong>
            </button>
          </div>
        </section>

        <section v-if="selectedModelTypeGroup" class="deployment-model-selection__stage">
          <header class="deployment-model-selection__heading">
            <span class="deployment-model-selection__step">2</span>
            <strong>{{ t('deploymentOps.sourcePicker.modelScale') }}</strong>
          </header>
          <div
            class="deployment-model-scale-list"
            role="listbox"
            :aria-label="t('deploymentOps.sourcePicker.modelScale')"
          >
            <button
              v-for="group in modelScaleGroups"
              :key="group.key"
              type="button"
              class="deployment-model-scale"
              :class="{ 'is-selected': group.key === selectedModelScaleGroup?.key }"
              :aria-selected="group.key === selectedModelScaleGroup?.key"
              @click.stop="selectModelScaleGroup(group)"
            >
              <strong>{{ group.name }}</strong>
            </button>
          </div>
        </section>
      </div>
    </template>

    <template #detail>
      <div
        v-if="selectedModelTypeGroup && selectedModelScaleGroup"
        class="deployment-source-detail"
      >
        <section class="deployment-source-detail__models">
          <header class="deployment-model-selection__heading">
            <span class="deployment-model-selection__step">3</span>
            <strong>{{ t('deploymentOps.sourcePicker.currentSelection') }}</strong>
          </header>
          <div
            class="deployment-trained-model-list"
            role="listbox"
            :aria-label="t('deploymentOps.sourcePicker.currentSelection')"
          >
            <button
              v-for="model in selectedModelScaleGroup.models"
              :key="model.model_id"
              type="button"
              class="deployment-trained-model"
              :class="{ 'is-selected': model.model_id === selectedModelId }"
              :aria-selected="model.model_id === selectedModelId"
              @click.stop="selectTrainedModel(model)"
            >
              <span class="deployment-trained-model__identity">
                <strong>{{ model.model_name }}</strong>
                <span>{{ model.model_id }}</span>
              </span>
              <span class="deployment-source-detail__section-count">
                {{ t('deploymentOps.sourcePicker.buildCount', { count: model.build_count }) }}
              </span>
            </button>
          </div>
        </section>

        <section class="deployment-source-detail__sources">
          <header class="deployment-model-selection__heading">
            <span class="deployment-model-selection__step">4</span>
            <strong>{{ t('deploymentOps.sourcePicker.deploymentSource') }}</strong>
          </header>

          <div
            v-if="detailLoading"
            class="deployment-source-detail__empty deployment-source-detail__empty--loading"
            aria-live="polite"
          >
            <span class="deployment-source-detail__spinner" />
            <strong>{{ t('deploymentOps.sourcePicker.detailLoading') }}</strong>
          </div>

          <template v-else-if="selectedModelDetailMatchesSelection">
            <header class="deployment-source-detail__section-heading">
              <strong>{{ t('deploymentOps.sourcePicker.completedBuilds') }}</strong>
              <span class="deployment-source-detail__section-count">
                {{ selectedModelDetail?.builds.length ?? 0 }}
              </span>
            </header>
            <div
              v-if="selectedModelDetail && selectedModelDetail.builds.length > 0"
              class="compact-list deployment-source-list"
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
                    class="deployment-source-action"
                    size="sm"
                    variant="secondary"
                    :disabled="!isBuildSelectable(build)"
                    :title="buildRuntimeUnavailableReason(build) || t('deploymentOps.sourcePicker.useBuild')"
                    @click.stop="applyBuildSelection(build)"
                  >
                    {{
                      isBuildSelectable(build)
                        ? t('deploymentOps.sourcePicker.useBuild')
                        : t('deploymentOps.sourcePicker.environmentUnavailable')
                    }}
                  </Button>
                </div>
              </div>
            </div>
            <div v-else class="deployment-source-detail__empty">
              <strong>{{ t('deploymentOps.sourcePicker.emptyBuildsTitle') }}</strong>
              <span>{{ t('deploymentOps.sourcePicker.emptyBuildsDescription') }}</span>
            </div>
          </template>

          <div v-else class="deployment-source-detail__empty">
            <strong>{{ t('deploymentOps.sourcePicker.selectModelTitle') }}</strong>
            <span>{{ t('deploymentOps.sourcePicker.selectModelDescription') }}</span>
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
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  DeploymentSourceModelBuild,
  DeploymentSourceModelDetail,
  DeploymentSourceModelSummary,
} from '@/modules/models/services/model.service'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import ModelPickerDialogShell from '@/shared/ui/components/ModelPickerDialogShell.vue'
import { hasCudaDevice } from '../deployment-device-support'
import type { ModelTaskType } from '../services/deployment.service'
import type { DeploymentSourceSelection } from './deployment-source.types'

interface TaskTypeOption {
  label: string
  value: ModelTaskType
}

interface ModelTypeGroup {
  key: string
  name: string
  models: DeploymentSourceModelSummary[]
}

interface ModelScaleGroup {
  key: string
  name: string
  models: DeploymentSourceModelSummary[]
}

const props = defineProps<{
  open: boolean
  loading: boolean
  detailLoading: boolean
  taskType: ModelTaskType
  taskTypeOptions: TaskTypeOption[]
  models: DeploymentSourceModelSummary[]
  selectedModelId: string
  selectedModelDetail: DeploymentSourceModelDetail | null
  selectedBuildId: string
  devices: Record<string, unknown> | null
}>()

const emit = defineEmits<{
  close: []
  'change-task-type': [taskType: ModelTaskType]
  'select-model': [modelId: string]
  'apply-source': [selection: DeploymentSourceSelection]
}>()

const { t } = useI18n()

const scaleOrder = new Map([
  ['tiny', 0],
  ['t', 0],
  ['nano', 1],
  ['n', 1],
  ['small', 2],
  ['s', 2],
  ['medium', 3],
  ['m', 3],
  ['base', 4],
  ['b', 4],
  ['large', 5],
  ['l', 5],
  ['xlarge', 6],
  ['x', 6],
])

function normalizeText(value: string): string {
  return value.trim().toLowerCase()
}

function compareScale(left: ModelScaleGroup, right: ModelScaleGroup): number {
  const leftOrder = scaleOrder.get(left.key) ?? Number.MAX_SAFE_INTEGER
  const rightOrder = scaleOrder.get(right.key) ?? Number.MAX_SAFE_INTEGER
  if (leftOrder !== rightOrder) {
    return leftOrder - rightOrder
  }
  return left.key.localeCompare(right.key)
}

const projectModels = computed(() =>
  props.models.filter((model) => model.scope_kind === 'project'),
)

const selectedModelSummary = computed(
  () => projectModels.value.find((model) => model.model_id === props.selectedModelId) ?? null,
)

const modelTypeGroups = computed<ModelTypeGroup[]>(() => {
  const groups = new Map<string, ModelTypeGroup>()
  for (const model of projectModels.value) {
    const name = model.model_type.trim() || model.model_name.trim() || model.model_id
    const key = normalizeText(name)
    const current = groups.get(key)
    if (current) {
      current.models.push(model)
      continue
    }
    groups.set(key, { key, name, models: [model] })
  }
  return Array.from(groups.values())
})

const selectedModelTypeGroup = computed(
  () =>
    modelTypeGroups.value.find((group) =>
      group.models.some((model) => model.model_id === props.selectedModelId),
    ) ??
    modelTypeGroups.value[0] ??
    null,
)

const modelScaleGroups = computed<ModelScaleGroup[]>(() => {
  const groups = new Map<string, ModelScaleGroup>()
  for (const model of selectedModelTypeGroup.value?.models ?? []) {
    const name = model.model_scale.trim() || '-'
    const key = normalizeText(name)
    const current = groups.get(key)
    if (current) {
      current.models.push(model)
      continue
    }
    groups.set(key, { key, name, models: [model] })
  }
  return Array.from(groups.values()).sort(compareScale)
})

const selectedModelScaleGroup = computed(
  () =>
    modelScaleGroups.value.find((group) =>
      group.models.some((model) => model.model_id === props.selectedModelId),
    ) ??
    modelScaleGroups.value[0] ??
    null,
)

const selectedModelDetailMatchesSelection = computed(
  () =>
    props.selectedModelDetail !== null &&
    props.selectedModelDetail.model_id === props.selectedModelId &&
    selectedModelSummary.value !== null,
)

function selectModelTypeGroup(group: ModelTypeGroup): void {
  const currentScale = normalizeText(selectedModelSummary.value?.model_scale ?? '')
  const target =
    group.models.find((model) => normalizeText(model.model_scale) === currentScale) ??
    group.models[0]
  selectTrainedModel(target)
}

function selectModelScaleGroup(group: ModelScaleGroup): void {
  const target =
    group.models.find((model) => model.model_id === props.selectedModelId) ?? group.models[0]
  selectTrainedModel(target)
}

function selectTrainedModel(model: DeploymentSourceModelSummary | undefined): void {
  if (model && model.model_id !== props.selectedModelId) {
    emit('select-model', model.model_id)
  }
}

function emitTaskType(taskType: string): void {
  if (props.taskTypeOptions.some((option) => option.value === taskType)) {
    emit('change-task-type', taskType as ModelTaskType)
  }
}

function buildSelection(build: DeploymentSourceModelBuild): DeploymentSourceSelection {
  const model = props.selectedModelDetail
  if (!model || model.model_id !== props.selectedModelId) {
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
  if (isBuildSelectable(build)) {
    emit('apply-source', buildSelection(build))
  }
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
    ? (value as Record<string, unknown>)
    : null
}
</script>

<style scoped>
.deployment-model-selection,
.deployment-source-detail,
.deployment-source-detail__sources {
  display: grid;
  gap: 12px;
  min-height: 0;
  align-content: start;
}

.deployment-model-selection {
  width: 100%;
  overflow: auto;
  padding-right: 4px;
}

.deployment-model-selection__stage,
.deployment-source-detail__models,
.deployment-source-detail__sources,
.deployment-source-detail__empty {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--summary-bg);
}

.deployment-model-selection__stage,
.deployment-source-detail__models {
  display: grid;
  gap: 12px;
}

.deployment-model-selection__heading,
.deployment-source-detail__section-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.deployment-source-detail__section-heading {
  justify-content: space-between;
}

.deployment-model-selection__step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  color: var(--accent-on);
  background: var(--accent);
  font-size: 12px;
  font-weight: 800;
}

.deployment-model-family-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.deployment-model-family,
.deployment-model-scale,
.deployment-trained-model {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  text-align: left;
  background: var(--surface);
  cursor: pointer;
}

.deployment-model-family,
.deployment-model-scale {
  display: flex;
  align-items: center;
}

.deployment-model-family:hover,
.deployment-model-scale:hover,
.deployment-trained-model:hover {
  border-color: var(--line-strong);
  background: var(--surface-muted);
}

.deployment-model-family.is-selected,
.deployment-model-scale.is-selected,
.deployment-trained-model.is-selected,
.compact-list__item.is-active {
  border-color: transparent;
  background: var(--selected-row-bg);
}

.deployment-model-scale-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(116px, 1fr));
  gap: 8px;
}

.deployment-model-scale {
  min-height: 52px;
}

.deployment-source-detail {
  grid-template-rows: auto minmax(0, 1fr);
}

.deployment-trained-model-list {
  display: grid;
  gap: 8px;
  max-height: 210px;
  overflow: auto;
  padding-right: 4px;
}

.deployment-trained-model {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-height: 66px;
}

.deployment-trained-model__identity,
.deployment-source-build-meta,
.deployment-source-detail__empty {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.deployment-trained-model__identity strong,
.deployment-trained-model__identity span,
.deployment-source-build-meta strong,
.deployment-source-build-meta span,
.deployment-source-detail__empty strong,
.deployment-source-detail__empty span {
  overflow-wrap: anywhere;
}

.deployment-trained-model__identity span,
.deployment-source-build-meta span,
.deployment-source-detail__empty span {
  color: var(--muted);
  font-size: 12px;
}

.deployment-source-detail__sources {
  grid-template-rows: auto auto minmax(0, 1fr);
  overflow: hidden;
}

.deployment-source-detail__section-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  min-height: 24px;
  padding: 0 8px;
  border-radius: 999px;
  color: var(--muted);
  background: var(--button-secondary-bg);
  font-size: 12px;
  font-weight: 700;
}

.deployment-source-list {
  min-width: 0;
  overflow: auto;
  padding-right: 4px;
}

.deployment-source-list .compact-list__item > div:first-child {
  min-width: 0;
}

.compact-list__item {
  align-items: flex-start;
}

.compact-list__item.is-disabled {
  opacity: 0.72;
}

.table-actions {
  flex: 0 0 auto;
}

.deployment-source-action {
  flex: none;
  white-space: nowrap;
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

.deployment-source-detail__empty {
  align-content: center;
}

.deployment-source-detail__empty--large {
  min-height: 160px;
}

.deployment-source-detail__empty--loading {
  min-height: 120px;
}

.deployment-source-detail__spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--line-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: deployment-source-detail-spin 0.8s linear infinite;
}

@keyframes deployment-source-detail-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 680px) {
  .deployment-model-family-list {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .deployment-model-selection,
  .deployment-trained-model-list,
  .deployment-source-list {
    max-height: none;
    overflow: visible;
  }

  .deployment-source-detail {
    grid-template-rows: auto auto;
  }

  .deployment-source-detail__sources {
    grid-template-rows: auto auto auto;
    overflow: visible;
  }
}

@media (prefers-reduced-motion: reduce) {
  .deployment-source-detail__spinner {
    animation: none;
  }
}
</style>
