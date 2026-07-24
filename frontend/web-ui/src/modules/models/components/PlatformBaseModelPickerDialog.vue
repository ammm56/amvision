<template>
  <ModelPickerDialogShell
    :open="open"
    :loading="loading"
    compact
    :title="title"
    :close-label="closeLabel"
    :task-type-options="taskTypeOptions"
    :selected-task-type="selectedTaskType"
    :list-title="modelListTitle"
    :list-count="modelGroups.length"
    :detail-title="detailTitle"
    @close="$emit('close')"
    @change-task-type="$emit('change-task-type', $event)"
  >
    <template #list>
      <EmptyState
        v-if="!loading && models.length === 0"
        :title="emptyTitle"
        :description="emptyDescription"
      />

      <div v-else class="platform-model-selection">
        <section class="platform-model-selection__stage">
          <header class="platform-model-selection__heading">
            <span class="platform-model-selection__step">1</span>
            <strong>{{ modelNameLabel }}</strong>
          </header>
          <div
            class="platform-model-family-list"
            role="listbox"
            :aria-label="modelNameLabel"
          >
            <button
              v-for="group in modelGroups"
              :key="group.key"
              type="button"
              class="platform-model-family"
              :class="{ 'is-selected': group.key === selectedModelGroup?.key }"
              :aria-selected="group.key === selectedModelGroup?.key"
              @click.stop="selectModelGroup(group)"
            >
              <strong>{{ group.name }}</strong>
            </button>
          </div>
        </section>

        <section v-if="selectedModelGroup" class="platform-model-selection__stage">
          <header class="platform-model-selection__heading">
            <span class="platform-model-selection__step">2</span>
            <strong>{{ scaleLabel }}</strong>
          </header>
          <div
            class="platform-model-scale-list"
            role="listbox"
            :aria-label="scaleLabel"
          >
            <button
              v-for="model in selectedModelGroup.models"
              :key="model.model_id"
              type="button"
              class="platform-model-scale"
              :class="{ 'is-selected': model.model_id === selectedModelId }"
              :aria-selected="model.model_id === selectedModelId"
              @click.stop="selectScale(model)"
            >
              <strong>{{ displayScale(model.model_scale) }}</strong>
            </button>
          </div>
        </section>
      </div>
    </template>

    <template #detail>
      <div v-if="detailLoading" class="platform-model-detail__empty" aria-live="polite">
        <span class="platform-model-detail__spinner" />
        <strong>{{ detailLoadingLabel }}</strong>
      </div>

      <div v-else-if="selectedModelDetail" class="platform-model-detail">
        <div class="platform-model-detail__summary">
          <header class="platform-model-selection__heading">
            <span class="platform-model-selection__step">3</span>
            <strong>{{ currentSelectionLabel }}</strong>
          </header>
          <div class="platform-model-detail__identity">
            <strong>{{ selectedModelDetail.model_name }}</strong>
            <span>{{ selectedModelDetail.model_id }}</span>
          </div>
          <div class="platform-model-detail__chips">
            <span
              v-if="showModelType"
              class="platform-model-pill"
            >
              {{ selectedModelDetail.model_type }}
            </span>
            <span class="platform-model-pill">{{ selectedModelDetail.task_type }}</span>
            <span class="platform-model-pill">{{ scaleLabel }} · {{ displayScale(selectedModelDetail.model_scale) }}</span>
          </div>
          <div v-if="mode === 'training'" class="platform-model-detail__actions">
            <Button size="sm" variant="secondary" @click.stop="$emit('apply-model', selectedModelDetail)">
              {{ applyModelLabel }}
            </Button>
          </div>
        </div>

        <div class="platform-model-detail__versions">
          <header class="platform-model-selection__heading">
            <span class="platform-model-selection__step">4</span>
            <strong>{{ versionSelectionLabel }}</strong>
          </header>
          <div
            v-for="group in versionGroups"
            :key="group.id"
            class="platform-model-detail__version-group"
          >
            <div class="platform-model-detail__section-heading">
              <strong>{{ group.title }}</strong>
              <span class="platform-model-detail__section-count">{{ group.items.length }}</span>
            </div>
            <div class="compact-list">
              <div
                v-for="version in group.items"
                :key="version.model_version_id"
                class="compact-list__item"
                :class="{ 'is-active': version.model_version_id === selectedVersionId }"
              >
                <div>
                  <strong>{{ version.title }}</strong>
                  <span>{{ version.subtitle }}</span>
                </div>
                <div class="table-actions">
                  <Button
                    v-if="mode === 'training'"
                    class="platform-model-version-action"
                    size="sm"
                    variant="secondary"
                    @click.stop="$emit('apply-training-version', { model: selectedModelDetail, modelVersionId: version.model_version_id })"
                  >
                    {{ applyTrainingVersionLabel }}
                  </Button>
                  <Button
                    v-if="mode === 'conversion'"
                    class="platform-model-version-action"
                    size="sm"
                    variant="secondary"
                    @click.stop="$emit('apply-conversion-version', { model: selectedModelDetail, modelVersionId: version.model_version_id })"
                  >
                    {{ applyConversionVersionLabel }}
                  </Button>
                </div>
              </div>
            </div>
          </div>
          <div v-if="versionGroups.length === 0" class="platform-model-detail__empty">
            <strong>{{ emptyVersionsTitle }}</strong>
            <span>{{ emptyVersionsDescription }}</span>
          </div>
        </div>
      </div>

      <div v-else class="platform-model-detail__empty">
        <strong>{{ detailEmptyTitle }}</strong>
        <span>{{ detailEmptyDescription }}</span>
      </div>
    </template>
  </ModelPickerDialogShell>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { PlatformBaseModelDetail, PlatformBaseModelSummary } from '../services/model.service'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import ModelPickerDialogShell from '@/shared/ui/components/ModelPickerDialogShell.vue'

interface TaskTypeOption {
  label: string
  value: string
}

interface VersionSelectionPayload {
  model: PlatformBaseModelDetail
  modelVersionId: string
}

interface VersionListItem {
  model_version_id: string
  source_kind: string
  title: string
  subtitle: string
}

interface VersionListGroup {
  id: string
  title: string
  items: VersionListItem[]
}

interface ModelNameGroup {
  key: string
  name: string
  models: PlatformBaseModelSummary[]
}

const props = defineProps<{
  open: boolean
  loading: boolean
  detailLoading: boolean
  mode: 'training' | 'conversion'
  title: string
  closeLabel: string
  taskTypeOptions: TaskTypeOption[]
  selectedTaskType: string
  modelListTitle: string
  modelNameLabel: string
  detailTitle: string
  detailLoadingLabel: string
  currentSelectionLabel: string
  versionSelectionLabel: string
  versionsTitle: string
  extraVersionsTitle: string
  scaleLabel: string
  applyModelLabel: string
  applyTrainingVersionLabel: string
  applyConversionVersionLabel: string
  emptyTitle: string
  emptyDescription: string
  detailEmptyTitle: string
  detailEmptyDescription: string
  emptyVersionsTitle: string
  emptyVersionsDescription: string
  models: PlatformBaseModelSummary[]
  selectedModelId: string | null
  selectedModelDetail: PlatformBaseModelDetail | null
  extraVersions?: VersionListItem[]
  selectedVersionId?: string
}>()

const emit = defineEmits<{
  close: []
  'change-task-type': [taskType: string]
  'select-model': [modelId: string]
  'apply-model': [model: PlatformBaseModelDetail]
  'apply-training-version': [payload: VersionSelectionPayload]
  'apply-conversion-version': [payload: VersionSelectionPayload]
}>()

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

function displayScale(value: string): string {
  const normalized = value.trim()
  return normalized || '-'
}

function compareScale(left: PlatformBaseModelSummary, right: PlatformBaseModelSummary): number {
  const leftScale = normalizeText(left.model_scale)
  const rightScale = normalizeText(right.model_scale)
  const leftOrder = scaleOrder.get(leftScale) ?? Number.MAX_SAFE_INTEGER
  const rightOrder = scaleOrder.get(rightScale) ?? Number.MAX_SAFE_INTEGER
  if (leftOrder !== rightOrder) {
    return leftOrder - rightOrder
  }
  return leftScale.localeCompare(rightScale)
}

const modelGroups = computed<ModelNameGroup[]>(() => {
  const groups = new Map<string, ModelNameGroup>()
  for (const model of props.models) {
    const name = model.model_name.trim() || model.model_type.trim() || model.model_id
    const key = normalizeText(name)
    const current = groups.get(key)
    if (current) {
      current.models.push(model)
      continue
    }
    groups.set(key, { key, name, models: [model] })
  }
  return Array.from(groups.values()).map((group) => ({
    ...group,
    models: [...group.models].sort(compareScale),
  }))
})

const selectedModelSummary = computed(
  () => props.models.find((model) => model.model_id === props.selectedModelId) ?? null,
)

const selectedModelGroup = computed(
  () => modelGroups.value.find((group) => group.models.some((model) => model.model_id === props.selectedModelId))
    ?? modelGroups.value[0]
    ?? null,
)

const showModelType = computed(() => {
  const detail = props.selectedModelDetail
  return detail !== null && normalizeText(detail.model_type) !== normalizeText(detail.model_name)
})

function selectModelGroup(group: ModelNameGroup): void {
  const currentScale = normalizeText(selectedModelSummary.value?.model_scale ?? '')
  const target = group.models.find((model) => normalizeText(model.model_scale) === currentScale)
    ?? group.models[0]
  if (target && target.model_id !== props.selectedModelId) {
    emit('select-model', target.model_id)
  }
}

function selectScale(model: PlatformBaseModelSummary): void {
  if (model.model_id !== props.selectedModelId) {
    emit('select-model', model.model_id)
  }
}

const availableVersions = computed<VersionListItem[]>(() => {
  const versions = props.selectedModelDetail?.versions ?? props.selectedModelDetail?.available_versions ?? []
  return versions.map((version) => ({
    model_version_id: version.model_version_id,
    source_kind: version.source_kind,
    title: version.model_version_id,
    subtitle: version.source_kind,
  }))
})

const versionGroups = computed<VersionListGroup[]>(() => {
  const groups: VersionListGroup[] = []
  if (availableVersions.value.length > 0) {
    groups.push({
      id: 'base-versions',
      title: props.versionsTitle,
      items: availableVersions.value,
    })
  }
  if ((props.extraVersions ?? []).length > 0) {
    groups.push({
      id: 'extra-versions',
      title: props.extraVersionsTitle,
      items: props.extraVersions ?? [],
    })
  }
  return groups
})
</script>

<style scoped>
.platform-model-selection,
.platform-model-detail,
.platform-model-detail__versions {
  display: grid;
  gap: 12px;
  min-height: 0;
}

.platform-model-selection {
  align-content: start;
  overflow: auto;
  padding-right: 4px;
}

.platform-model-selection__stage,
.platform-model-detail__summary,
.platform-model-detail__versions,
.platform-model-detail__empty {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--summary-bg);
}

.platform-model-selection__stage {
  display: grid;
  gap: 12px;
}

.platform-model-selection__heading,
.platform-model-detail__section-heading,
.platform-model-detail__chips,
.platform-model-detail__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.platform-model-selection__step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  color: #fff;
  background: var(--accent);
  font-size: 12px;
  font-weight: 800;
}

.platform-model-family-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.platform-model-family,
.platform-model-scale {
  display: flex;
  align-items: center;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  text-align: left;
  background: var(--surface);
  cursor: pointer;
}

.platform-model-family:hover,
.platform-model-family.is-selected,
.platform-model-scale:hover,
.platform-model-scale.is-selected,
.compact-list__item.is-active {
  border-color: var(--accent);
  background: var(--selected-row-bg);
}

.platform-model-scale-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(116px, 1fr));
  gap: 8px;
}

.platform-model-scale {
  min-height: 52px;
}

.platform-model-detail {
  align-content: start;
}

.platform-model-detail__summary {
  display: grid;
  gap: 12px;
  align-content: start;
}

.platform-model-detail__identity,
.platform-model-detail__empty {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.platform-model-detail__identity strong,
.platform-model-detail__identity span,
.platform-model-detail__empty strong,
.platform-model-detail__empty span {
  overflow-wrap: anywhere;
}

.platform-model-detail__identity span,
.platform-model-detail__empty span {
  color: var(--muted);
  font-size: 12px;
}

.platform-model-detail__actions {
  justify-content: flex-start;
}

.platform-model-version-action {
  flex: none;
  white-space: nowrap;
}

.compact-list__item > div:first-child {
  min-width: 0;
}

.platform-model-detail__versions {
  align-content: start;
  overflow: auto;
}

.platform-model-detail__version-group {
  display: grid;
  gap: 10px;
}

.platform-model-detail__section-heading {
  justify-content: space-between;
}

.platform-model-detail__section-count {
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

.platform-model-pill {
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

.platform-model-detail__empty {
  min-height: 160px;
  align-content: center;
}

.platform-model-detail__spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--line-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: platform-model-detail-spin 0.8s linear infinite;
}

@keyframes platform-model-detail-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 680px) {
  .platform-model-family-list {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .platform-model-detail__spinner {
    animation: none;
  }
}
</style>
