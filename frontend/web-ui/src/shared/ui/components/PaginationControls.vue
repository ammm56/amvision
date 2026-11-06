<template>
  <nav class="pagination-controls" aria-label="Pagination">
    <p class="pagination-controls__summary" aria-live="polite"><slot name="summary">{{ summaryText }}</slot></p>
    <div class="pagination-controls__actions">
      <span v-if="!numbered" class="pagination-controls__page">{{ pageText }}</span>
      <div class="pagination-controls__buttons">
        <Button size="sm" variant="secondary" :disabled="disabled || !canGoPrevious" @click="emit('previous')">
          {{ t('common.pagination.previous') }}
        </Button>
        <template v-if="numbered" v-for="(page, index) in pageNumbers" :key="index">
          <Button v-if="page" size="sm" :variant="page === currentPage ? 'primary' : 'secondary'" :aria-current="page === currentPage ? 'page' : undefined" :disabled="disabled" @click="emit('go', (page - 1) * limit)">{{ page }}</Button>
          <span v-else aria-hidden="true">…</span>
        </template>
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
    numbered?: boolean
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
  go: [offset: number]
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
const pageNumbers = computed(() => {
  const total = totalPages.value || currentPage.value
  const values = new Set([1, total, currentPage.value - 1, currentPage.value, currentPage.value + 1])
  if (currentPage.value <= 3) { values.add(2); values.add(3); values.add(4); values.add(5) }
  const pages = [...values].filter(page => page >= 1 && page <= total).sort((a, b) => a - b)
  const result: (number | null)[] = []
  pages.forEach((page, index) => { if (index && page - pages[index - 1] > 1) result.push(null); result.push(page) })
  return result
})
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
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface);
}

.pagination-controls__summary {
  margin: 0;
  color: var(--am-text-muted);
  font-size: 12px;
  font-weight: 600;
}

.pagination-controls__actions {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.pagination-controls__page {
  color: var(--am-text);
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
