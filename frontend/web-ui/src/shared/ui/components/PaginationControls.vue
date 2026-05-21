<template>
  <nav class="pagination-controls" aria-label="Pagination">
    <p class="pagination-controls__summary" aria-live="polite">{{ summaryText }}</p>
    <div class="pagination-controls__actions">
      <span class="pagination-controls__page">{{ pageText }}</span>
      <div class="pagination-controls__buttons">
        <Button size="sm" variant="secondary" :disabled="disabled || !canGoPrevious" @click="emit('previous')">
          {{ t('common.pagination.previous') }}
        </Button>
        <Button size="sm" variant="secondary" :disabled="disabled || !canGoNext" @click="emit('next')">
          {{ t('common.pagination.next') }}
        </Button>
      </div>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Button from './Button.vue'

const props = withDefaults(
  defineProps<{
    offset: number
    limit: number
    itemCount: number
    totalCount?: number | null
    hasMore?: boolean
    disabled?: boolean
  }>(),
  {
    totalCount: null,
    hasMore: false,
    disabled: false,
  },
)

const emit = defineEmits<{
  previous: []
  next: []
}>()

const { t } = useI18n()

const rangeStart = computed(() => (props.itemCount > 0 ? props.offset + 1 : 0))
const rangeEnd = computed(() => props.offset + props.itemCount)
const currentPage = computed(() => (props.limit > 0 ? Math.floor(props.offset / props.limit) + 1 : 1))
const totalPages = computed(() => {
  if (props.totalCount === null || props.limit <= 0) return null
  return Math.max(Math.ceil(props.totalCount / props.limit), 1)
})
const canGoPrevious = computed(() => props.offset > 0)
const canGoNext = computed(() => {
  if (props.hasMore) return true
  if (props.totalCount === null) return false
  return props.offset + props.itemCount < props.totalCount
})
const summaryText = computed(() => {
  if (props.itemCount === 0 || props.totalCount === null) {
    return `${rangeStart.value}-${rangeEnd.value}`
  }
  return t('common.pagination.summary', {
    start: rangeStart.value,
    end: rangeEnd.value,
    total: props.totalCount,
  })
})
const pageText = computed(() => {
  if (totalPages.value === null) {
    return t('common.pagination.pageSingle', { current: currentPage.value })
  }
  return t('common.pagination.page', { current: currentPage.value, total: totalPages.value })
})
</script>

<style scoped>
.pagination-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
}

.pagination-controls__summary {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.pagination-controls__actions {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.pagination-controls__page {
  color: var(--text);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.pagination-controls__buttons {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 800px) {
  .pagination-controls {
    align-items: stretch;
    flex-direction: column;
  }

  .pagination-controls__actions {
    justify-content: space-between;
    width: 100%;
  }

  .pagination-controls__buttons {
    justify-content: flex-end;
  }
}
</style>