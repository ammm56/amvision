<template>
  <div v-if="open" class="platform-model-picker-backdrop" @click="$emit('close')">
    <div
      class="platform-model-picker"
      role="dialog"
      aria-modal="true"
      :aria-label="title"
      @click.stop
      @keydown.esc.prevent="$emit('close')"
    >
      <header class="platform-model-picker__header">
        <div>
          <p class="page-kicker">{{ kicker }}</p>
          <h2>{{ title }}</h2>
          <p class="platform-model-picker__description">{{ description }}</p>
        </div>
        <button
          type="button"
          class="platform-model-picker__close"
          :title="closeLabel"
          :aria-label="closeLabel"
          @click="$emit('close')"
        >
          <X :size="16" />
        </button>
      </header>

      <div class="platform-model-picker__toolbar">
        <span class="platform-model-picker__label">{{ taskTypeLabel }}</span>
        <div class="platform-model-picker__chips" role="tablist" :aria-label="taskTypeLabel">
          <button
            v-for="option in taskTypeOptions"
            :key="option.value"
            type="button"
            class="platform-model-picker__chip"
            :class="{ 'is-active': option.value === selectedTaskType }"
            @click="$emit('change-task-type', option.value)"
          >
            {{ option.label }}
          </button>
        </div>
      </div>

      <div class="platform-model-picker__body">
        <section class="platform-model-picker__column">
          <header class="platform-model-picker__section-heading">
            <strong>{{ modelListTitle }}</strong>
            <span class="platform-model-picker__section-count">{{ models.length }}</span>
          </header>

          <EmptyState
            v-if="!loading && models.length === 0"
            :title="emptyTitle"
            :description="emptyDescription"
          />

          <div v-else class="platform-model-picker__grid">
            <button
              v-for="model in models"
              :key="model.model_id"
              type="button"
              class="platform-model-card"
              :class="{ 'is-selected': model.model_id === selectedModelId }"
              @click="$emit('select-model', model.model_id)"
            >
              <div class="platform-model-card__identity">
                <strong>{{ model.model_name }}</strong>
                <span>{{ model.model_id }}</span>
              </div>
              <div class="platform-model-card__meta">
                <span class="platform-model-pill">{{ model.task_type }}</span>
                <span class="platform-model-pill">{{ scaleLabel }} · {{ model.model_scale }}</span>
              </div>
              <div class="platform-model-card__footer">
                <span>{{ versionsLabel }} {{ model.version_count }}</span>
                <span>{{ buildsLabel }} {{ model.build_count }}</span>
              </div>
            </button>
          </div>
        </section>

        <section class="platform-model-picker__column platform-model-picker__detail">
          <header class="platform-model-picker__section-heading">
            <strong>{{ detailTitle }}</strong>
          </header>

          <div v-if="selectedModelDetail" class="platform-model-detail">
            <div class="platform-model-detail__summary">
              <div class="platform-model-detail__identity">
                <strong>{{ selectedModelDetail.model_name }}</strong>
                <span>{{ selectedModelDetail.model_id }}</span>
              </div>
              <div class="platform-model-detail__chips">
                <span class="platform-model-pill">{{ selectedModelDetail.model_type }}</span>
                <span class="platform-model-pill">{{ selectedModelDetail.task_type }}</span>
                <span class="platform-model-pill">{{ scaleLabel }} · {{ selectedModelDetail.model_scale }}</span>
              </div>
              <div v-if="mode === 'training'" class="platform-model-detail__actions">
                <Button size="sm" variant="secondary" @click="$emit('apply-model', selectedModelDetail)">
                  {{ applyModelLabel }}
                </Button>
              </div>
            </div>

            <div class="platform-model-detail__versions">
              <div class="platform-model-picker__section-heading">
                <strong>{{ versionsTitle }}</strong>
                <span class="platform-model-picker__section-count">{{ availableVersions.length }}</span>
              </div>
              <div v-if="availableVersions.length === 0" class="platform-model-detail__empty">
                <strong>{{ emptyVersionsTitle }}</strong>
                <span>{{ emptyVersionsDescription }}</span>
              </div>
              <div v-else class="compact-list">
                <div
                  v-for="version in availableVersions"
                  :key="version.model_version_id"
                  class="compact-list__item"
                  :class="{ 'is-active': version.model_version_id === selectedVersionId }"
                >
                  <div>
                    <strong>{{ version.model_version_id }}</strong>
                    <span>{{ version.source_kind }}</span>
                  </div>
                  <div class="table-actions">
                    <Button
                      v-if="mode === 'training'"
                      size="sm"
                      variant="secondary"
                      @click="$emit('apply-training-version', { model: selectedModelDetail, version })"
                    >
                      {{ applyTrainingVersionLabel }}
                    </Button>
                    <Button
                      v-if="mode === 'conversion'"
                      size="sm"
                      variant="secondary"
                      @click="$emit('apply-conversion-version', { model: selectedModelDetail, version })"
                    >
                      {{ applyConversionVersionLabel }}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-else class="platform-model-detail__empty">
            <strong>{{ detailEmptyTitle }}</strong>
            <span>{{ detailEmptyDescription }}</span>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { X } from '@lucide/vue'

import type {
  PlatformBaseModelDetail,
  PlatformBaseModelSummary,
  PlatformBaseModelVersionDetail,
  PlatformBaseModelVersionSummary,
} from '../services/model.service'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'

interface TaskTypeOption {
  label: string
  value: string
}

interface VersionSelectionPayload {
  model: PlatformBaseModelDetail
  version: PlatformBaseModelVersionDetail | PlatformBaseModelVersionSummary
}

const props = defineProps<{
  open: boolean
  loading: boolean
  mode: 'training' | 'conversion'
  kicker: string
  title: string
  description: string
  closeLabel: string
  taskTypeLabel: string
  taskTypeOptions: TaskTypeOption[]
  selectedTaskType: string
  modelListTitle: string
  detailTitle: string
  versionsTitle: string
  versionsLabel: string
  buildsLabel: string
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
  selectedVersionId?: string
}>()

defineEmits<{
  close: []
  'change-task-type': [taskType: string]
  'select-model': [modelId: string]
  'apply-model': [model: PlatformBaseModelDetail]
  'apply-training-version': [payload: VersionSelectionPayload]
  'apply-conversion-version': [payload: VersionSelectionPayload]
}>()

const availableVersions = computed(() => props.selectedModelDetail?.versions ?? props.selectedModelDetail?.available_versions ?? [])
</script>

<style scoped>
.platform-model-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgb(16 20 24 / 0.38);
}

.platform-model-picker {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  width: min(1120px, calc(100vw - 36px));
  max-height: min(760px, calc(100vh - 36px));
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 24px 48px rgb(0 0 0 / 0.18);
}

.platform-model-picker__header,
.platform-model-picker__toolbar,
.platform-model-picker__section-heading,
.platform-model-card__meta,
.platform-model-card__footer,
.platform-model-detail__chips,
.platform-model-detail__actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.platform-model-picker__header h2,
.platform-model-picker__header p {
  margin: 0;
}

.platform-model-picker__description {
  margin-top: 8px !important;
  color: var(--muted);
}

.platform-model-picker__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  color: var(--text);
  background: var(--button-secondary-bg);
  cursor: pointer;
}

.platform-model-picker__label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.platform-model-picker__chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.platform-model-picker__chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  color: var(--muted);
  background: var(--button-secondary-bg);
  cursor: pointer;
  font-weight: 700;
}

.platform-model-picker__chip.is-active {
  border-color: var(--accent);
  color: #ffffff;
  background: var(--accent);
}

.platform-model-picker__body {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.9fr);
  gap: 14px;
  min-height: 0;
}

.platform-model-picker__column {
  display: grid;
  gap: 12px;
  min-height: 0;
  align-content: start;
}

.platform-model-picker__grid,
.platform-model-detail__versions,
.platform-model-detail {
  display: grid;
  gap: 12px;
  min-height: 0;
}

.platform-model-picker__grid {
  align-content: start;
  overflow: auto;
  padding-right: 4px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.platform-model-picker__detail {
  align-content: start;
}

.platform-model-card,
.platform-model-detail__summary,
.platform-model-detail__versions,
.platform-model-detail__empty {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--summary-bg);
}

.platform-model-card {
  display: grid;
  gap: 12px;
  width: 100%;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.platform-model-card:hover,
.platform-model-card.is-selected,
.compact-list__item.is-active {
  border-color: var(--accent);
  background: var(--selected-row-bg);
}

.platform-model-card__identity,
.platform-model-detail__identity,
.platform-model-detail__empty {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.platform-model-card__identity strong,
.platform-model-card__identity span,
.platform-model-detail__identity strong,
.platform-model-detail__identity span,
.platform-model-detail__empty strong,
.platform-model-detail__empty span {
  overflow-wrap: anywhere;
}

.platform-model-card__identity span,
.platform-model-detail__identity span,
.platform-model-detail__empty span,
.platform-model-card__footer {
  color: var(--muted);
  font-size: 12px;
}

.platform-model-picker__section-count {
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

.platform-model-card__footer {
  align-items: center;
  gap: 12px;
  font-weight: 700;
}

.platform-model-detail {
  align-content: start;
}

.platform-model-detail__summary {
  display: grid;
  gap: 12px;
  align-content: start;
}

.platform-model-detail__versions {
  align-content: start;
}

.platform-model-detail__actions {
  justify-content: flex-start;
}

.platform-model-detail__empty {
  min-height: 160px;
  align-content: center;
}

@media (max-width: 960px) {
  .platform-model-picker {
    width: min(100%, calc(100vw - 24px));
    max-height: min(100%, calc(100vh - 24px));
  }

  .platform-model-picker__body {
    grid-template-columns: 1fr;
  }
}
</style>
