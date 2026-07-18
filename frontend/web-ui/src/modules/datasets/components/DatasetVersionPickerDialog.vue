<template>
  <div class="dataset-version-picker-backdrop" @click="$emit('close')">
    <div
      class="dataset-version-picker"
      role="dialog"
      aria-modal="true"
      :aria-label="t('datasetOps.versionPicker.title')"
      @click.stop
      @keydown.esc.prevent="$emit('close')"
    >
      <header class="dataset-version-picker__header">
        <div>
          <p class="page-kicker">{{ t('datasetOps.exportKicker') }}</p>
          <h2>{{ t('datasetOps.versionPicker.title') }}</h2>
          <p class="dataset-version-picker__description">{{ t('datasetOps.versionPicker.description') }}</p>
        </div>
        <button
          type="button"
          class="dataset-version-picker__close"
          :title="t('datasetOps.versionPicker.close')"
          :aria-label="t('datasetOps.versionPicker.close')"
          @click="$emit('close')"
        >
          <X :size="16" />
        </button>
      </header>

      <label class="dataset-version-picker__search">
        <Search :size="16" />
        <input
          ref="searchInput"
          :value="search"
          :placeholder="t('datasetOps.versionPicker.searchPlaceholder')"
          @input="$emit('update:search', ($event.target as HTMLInputElement).value)"
        />
      </label>

      <div v-if="filteredDatasetVersions.length === 0" class="dataset-version-picker__empty">
        <strong>{{ t('datasetOps.versionPicker.noResultsTitle') }}</strong>
        <span>{{ t('datasetOps.versionPicker.noResultsDescription') }}</span>
      </div>

      <div v-else class="dataset-version-picker__list">
        <button
          v-for="item in filteredDatasetVersions"
          :key="item.dataset_version_id"
          type="button"
          class="dataset-version-picker__item"
          :class="{ 'is-selected': item.dataset_version_id === resolvedDatasetVersionId }"
          @click="$emit('select', item.dataset_version_id)"
        >
          <div class="dataset-version-picker__item-main">
            <div class="dataset-version-picker__item-title">
              <strong>{{ item.dataset_version_id }}</strong>
              <div class="dataset-version-picker__item-chips">
                <span class="dataset-version-chip">{{ item.task_type }}</span>
                <span class="dataset-version-chip">{{ resolveImportFormatDisplayName(item.source_format_type) || t('common.noValue') }}</span>
              </div>
            </div>
            <div class="dataset-version-picker__item-meta">
              <span>{{ t('datasetOps.versionPicker.importIdLabel') }} {{ item.source_import_id || t('common.noValue') }}</span>
              <span v-if="item.source_created_at">{{ t('datasetOps.versionPicker.createdAtLabel') }} {{ formatSystemDateTime(item.source_created_at) }}</span>
            </div>
          </div>
          <div class="dataset-version-picker__item-side">
            <StatusBadge v-if="item.source_status" :tone="statusTone(item.source_status)">{{ item.source_status }}</StatusBadge>
            <Check v-if="item.dataset_version_id === resolvedDatasetVersionId" :size="18" />
          </div>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Check, Search, X } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import type { DatasetVersionSelectionItem } from '../composables/useDatasetVersionSelection'
import { resolveImportFormatDisplayName } from '../composables/useDatasetFormatCapabilities'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

defineProps<{
  search: string
  filteredDatasetVersions: DatasetVersionSelectionItem[]
  resolvedDatasetVersionId: string
  statusTone: (status: string | null | undefined) => 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}>()

defineEmits<{
  close: []
  select: [datasetVersionId: string]
  'update:search': [value: string]
}>()

const { t } = useI18n()
const searchInput = ref<HTMLInputElement | null>(null)

onMounted(() => {
  searchInput.value?.focus()
})
</script>

<style scoped>
.dataset-version-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgb(16 20 24 / 0.38);
}

.dataset-version-picker {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  width: min(860px, calc(100vw - 36px));
  max-height: min(640px, calc(100vh - 36px));
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 24px 48px rgb(0 0 0 / 0.18);
}

.dataset-version-picker__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.dataset-version-picker__header h2,
.dataset-version-picker__header p {
  margin: 0;
}

.dataset-version-picker__description {
  margin-top: 8px !important;
  color: var(--muted);
}

.dataset-version-picker__close {
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

.dataset-version-picker__search {
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

.dataset-version-picker__search:focus-within {
  border-color: var(--accent);
}

.dataset-version-picker__search input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  color: var(--input-text);
  background: transparent;
}

.dataset-version-picker__empty {
  display: grid;
  gap: 6px;
  place-items: center;
  min-height: 180px;
  padding: 24px;
  border: 1px dashed var(--line-strong);
  border-radius: 8px;
  color: var(--muted);
  text-align: center;
}

.dataset-version-picker__list {
  display: grid;
  align-content: start;
  gap: 10px;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.dataset-version-picker__item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  width: 100%;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  background: var(--summary-bg);
  text-align: left;
  cursor: pointer;
}

.dataset-version-picker__item:hover,
.dataset-version-picker__item.is-selected {
  border-color: var(--accent);
  background: var(--selected-row-bg);
}

.dataset-version-picker__item-main {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.dataset-version-picker__item-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.dataset-version-picker__item-title strong,
.dataset-version-picker__item-meta span {
  overflow-wrap: anywhere;
}

.dataset-version-picker__item-chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.dataset-version-chip {
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

.dataset-version-picker__item-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  color: var(--muted);
  font-size: 12px;
}

.dataset-version-picker__item-side {
  display: grid;
  justify-items: end;
  gap: 10px;
  flex-shrink: 0;
}

@media (max-width: 900px) {
  .dataset-version-picker {
    width: min(100%, calc(100vw - 24px));
    max-height: min(100%, calc(100vh - 24px));
  }

  .dataset-version-picker__item,
  .dataset-version-picker__item-title {
    flex-direction: column;
  }

  .dataset-version-picker__item-side {
    justify-items: start;
  }
}
</style>
