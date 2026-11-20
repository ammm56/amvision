<template>
  <div class="model-list-pagination">
    <PaginationControls numbered :offset="offset" :limit="pageSize" :item-count="itemCount" :total-count="total"
      :disabled="loading" @previous="$emit('page', page - 1)" @next="$emit('page', page + 1)" @go="$emit('page', $event / pageSize + 1)" />
    <Select :model-value="pageSize" :options="options" :disabled="loading" :aria-label="zh ? '每页条数' : 'Rows per page'"
      floating @update:model-value="$emit('page-size', Number($event))" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import Select from '@/shared/ui/components/Select.vue'

const props = defineProps<{ page: number; pageSize: number; itemCount: number; total: number; zh: boolean; loading?: boolean }>()
defineEmits<{ page: [number]; 'page-size': [number] }>()
const offset = computed(() => (props.page - 1) * props.pageSize)
const options = computed(() => [10, 20, 50].map(value => ({ value, label: props.zh ? `${value} 条/页` : `${value} / page` })))
</script>

<style scoped>
.model-list-pagination { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; padding-inline:12px; }
.model-list-pagination .pagination-controls { flex:1; min-width:0; border:0; padding-inline:0; background:transparent; }
.model-list-pagination > .ui-select { flex:none; }
</style>
