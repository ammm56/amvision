<template>
  <div v-if="open" class="dataset-export-picker-backdrop" @click="$emit('close')">
    <div
      class="dataset-export-picker"
      role="dialog"
      aria-modal="true"
      :aria-label="title"
      @click.stop
      @keydown.esc.prevent="$emit('close')"
    >
      <header class="dataset-export-picker__header">
        <div>
          <h2>{{ title }}</h2>
          <p class="dataset-export-picker__description">{{ description }}</p>
        </div>
        <button
          type="button"
          class="dataset-export-picker__close"
          :title="closeLabel"
          :aria-label="closeLabel"
          @click="$emit('close')"
        >
          <X :size="16" />
        </button>
      </header>

      <label class="dataset-export-picker__search">
        <Search :size="16" />
        <input
          :value="searchValue"
          :placeholder="searchPlaceholder"
          @input="handleSearchInput"
        />
      </label>

      <div class="dataset-export-picker__body">
        <section class="dataset-export-picker__column">
          <header class="dataset-export-picker__section-heading">
            <strong>{{ listTitle }}</strong>
            <span class="dataset-export-picker__section-count">{{ filteredExports.length }}</span>
          </header>

          <EmptyState
            v-if="!loading && exports.length === 0"
            :title="emptyTitle"
            :description="emptyDescription"
          />

          <div v-else-if="filteredExports.length === 0" class="dataset-export-picker__empty">
            <strong>{{ noResultsTitle }}</strong>
            <span>{{ noResultsDescription }}</span>
          </div>

          <div v-else class="dataset-export-picker__list">
            <button
              v-for="item in filteredExports"
              :key="item.dataset_export_id"
              type="button"
              class="dataset-export-picker__item"
              :class="{ 'is-selected': item.dataset_export_id === selectedExportId }"
              @click="$emit('select-export', item.dataset_export_id)"
            >
              <div class="dataset-export-picker__item-main">
                <div class="dataset-export-picker__item-title">
                  <strong>{{ item.dataset_export_id }}</strong>
                  <div class="dataset-export-picker__item-chips">
                    <span class="dataset-export-pill">{{ item.task_type }}</span>
                    <span class="dataset-export-pill">{{ item.format_id }}</span>
                  </div>
                </div>
                <div class="dataset-export-picker__item-meta">
                  <span>{{ datasetVersionIdLabel }} {{ item.dataset_version_id }}</span>
                  <span>{{ sampleCountLabel }} {{ item.sample_count }}</span>
                </div>
                <div class="dataset-export-picker__item-meta">
                  <span>{{ datasetIdLabel }} {{ item.dataset_id }}</span>
                  <span>{{ createdAtLabel }} {{ formatSystemDateTime(item.created_at) }}</span>
                </div>
              </div>
              <Check v-if="item.dataset_export_id === selectedExportId" :size="18" />
            </button>
          </div>
        </section>

        <section class="dataset-export-picker__column dataset-export-picker__detail">
          <header class="dataset-export-picker__section-heading">
            <strong>{{ detailTitle }}</strong>
          </header>

          <div v-if="selectedExport" class="dataset-export-detail">
            <div class="dataset-export-detail__summary">
              <div class="dataset-export-detail__identity">
                <strong>{{ selectedExport.dataset_export_id }}</strong>
                <span>{{ datasetVersionIdLabel }} {{ selectedExport.dataset_version_id }}</span>
              </div>
              <div class="dataset-export-detail__chips">
                <span class="dataset-export-pill">{{ selectedExport.task_type }}</span>
                <span class="dataset-export-pill">{{ selectedExport.format_id }}</span>
              </div>
              <div class="dataset-export-detail__grid">
                <div class="dataset-export-detail__item">
                  <span>{{ datasetIdLabel }}</span>
                  <strong>{{ selectedExport.dataset_id }}</strong>
                </div>
                <div class="dataset-export-detail__item">
                  <span>{{ sampleCountLabel }}</span>
                  <strong>{{ selectedExport.sample_count }}</strong>
                </div>
                <div class="dataset-export-detail__item">
                  <span>{{ createdAtLabel }}</span>
                  <strong>{{ formatSystemDateTime(selectedExport.created_at) }}</strong>
                </div>
                <div class="dataset-export-detail__item">
                  <span>{{ categoryNamesLabel }}</span>
                  <strong>{{ selectedExport.category_names.join(', ') || noValueLabel }}</strong>
                </div>
              </div>
              <div class="dataset-export-detail__actions">
                <Button size="sm" variant="secondary" @click="$emit('apply-export', selectedExport)">
                  {{ applyLabel }}
                </Button>
              </div>
            </div>
          </div>

          <div v-else class="dataset-export-picker__empty">
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
import { Check, Search, X } from '@lucide/vue'

import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'

const props = defineProps<{
  open: boolean
  loading: boolean
  title: string
  description: string
  closeLabel: string
  searchValue: string
  searchPlaceholder: string
  listTitle: string
  detailTitle: string
  applyLabel: string
  emptyTitle: string
  emptyDescription: string
  noResultsTitle: string
  noResultsDescription: string
  detailEmptyTitle: string
  detailEmptyDescription: string
  datasetIdLabel: string
  datasetVersionIdLabel: string
  sampleCountLabel: string
  createdAtLabel: string
  categoryNamesLabel: string
  noValueLabel: string
  exports: DatasetExportSummary[]
  selectedExportId: string | null
}>()

const emit = defineEmits<{
  close: []
  'update:searchValue': [value: string]
  'select-export': [datasetExportId: string]
  'apply-export': [datasetExport: DatasetExportSummary]
}>()

const filteredExports = computed(() => {
  const query = props.searchValue.trim().toLowerCase()
  if (!query) {
    return props.exports
  }
  return props.exports.filter((item) =>
    [
      item.dataset_export_id,
      item.dataset_id,
      item.dataset_version_id,
      item.format_id,
      item.task_type,
      item.status,
      ...item.category_names,
    ]
      .join(' ')
      .toLowerCase()
      .includes(query),
  )
})

const selectedExport = computed(
  () => props.exports.find((item) => item.dataset_export_id === props.selectedExportId) ?? null,
)

function handleSearchInput(event: Event): void {
  const input = event.target
  if (!(input instanceof HTMLInputElement)) {
    return
  }
  emit('update:searchValue', input.value)
}
</script>

<style scoped>
.dataset-export-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgb(16 20 24 / 0.38);
}

.dataset-export-picker {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  width: min(1080px, calc(100vw - 36px));
  max-height: min(720px, calc(100vh - 36px));
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 24px 48px rgb(0 0 0 / 0.18);
}

.dataset-export-picker__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.dataset-export-picker__header h2,
.dataset-export-picker__header p {
  margin: 0;
}

.dataset-export-picker__description {
  margin-top: 8px !important;
  color: var(--muted);
}

.dataset-export-picker__close {
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

.dataset-export-picker__search {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  color: var(--muted);
  background: var(--input-bg);
}

.dataset-export-picker__search:focus-within {
  border-color: var(--accent);
}

.dataset-export-picker__search input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  color: var(--input-text);
  background: transparent;
}

.dataset-export-picker__body {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.95fr);
  gap: 14px;
  min-height: 0;
}

.dataset-export-picker__column {
  display: grid;
  gap: 12px;
  min-height: 0;
  align-content: start;
}

.dataset-export-picker__section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.dataset-export-picker__section-count {
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

.dataset-export-picker__list {
  display: grid;
  align-content: start;
  gap: 10px;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.dataset-export-picker__item,
.dataset-export-detail__summary,
.dataset-export-picker__empty {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--summary-bg);
}

.dataset-export-picker__item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  width: 100%;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.dataset-export-picker__item:hover,
.dataset-export-picker__item.is-selected {
  border-color: var(--accent);
  background: var(--selected-row-bg);
}

.dataset-export-picker__item-main,
.dataset-export-detail__summary,
.dataset-export-detail__identity,
.dataset-export-picker__empty {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.dataset-export-picker__item-title,
.dataset-export-picker__item-chips,
.dataset-export-detail__chips,
.dataset-export-detail__actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.dataset-export-picker__item-title strong,
.dataset-export-picker__item-meta span,
.dataset-export-detail__identity strong,
.dataset-export-detail__identity span,
.dataset-export-picker__empty strong,
.dataset-export-picker__empty span,
.dataset-export-detail__item strong {
  overflow-wrap: anywhere;
}

.dataset-export-picker__item-meta,
.dataset-export-detail__identity span,
.dataset-export-picker__empty span,
.dataset-export-detail__item span {
  color: var(--muted);
  font-size: 12px;
}

.dataset-export-picker__item-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.dataset-export-pill {
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

.dataset-export-detail__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.dataset-export-detail__item {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.dataset-export-detail__actions {
  justify-content: flex-start;
}

.dataset-export-picker__empty {
  min-height: 180px;
  align-content: center;
  text-align: center;
}

@media (max-width: 960px) {
  .dataset-export-picker {
    width: min(100%, calc(100vw - 24px));
    max-height: min(100%, calc(100vh - 24px));
  }

  .dataset-export-picker__body,
  .dataset-export-detail__grid {
    grid-template-columns: 1fr;
  }

  .dataset-export-picker__item {
    flex-direction: column;
  }
}
</style>
