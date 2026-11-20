<template>
  <div class="resource-table matrix-table" tabindex="0" :aria-label="zh ? '混淆矩阵' : 'Confusion matrix'">
    <table>
      <thead><tr>
        <th scope="col">{{ zh ? '标注 ＼ 预测' : 'Actual ＼ Predicted' }}</th>
        <th v-for="column in visibleColumns" :key="column" scope="col" :title="labels[column]">
          <template v-for="(part, partIndex) in labelParts(labels[column])" :key="partIndex">{{ part }}<wbr /></template>
        </th>
        <th scope="col">{{ zh ? '合计' : 'Total' }}</th>
      </tr></thead>
      <tbody><tr v-for="(row, index) in rows" :key="index">
        <th scope="row" :title="labels[index]">
          <template v-for="(part, partIndex) in labelParts(labels[index])" :key="partIndex">{{ part }}<wbr /></template>
        </th>
        <td v-for="column in visibleColumns" :key="column" :class="{ diagonal: index === column && row[column] > 0, 'has-count': row[column] > 0 }"
          :style="index === column && row[column] > 0 ? { '--diagonal-strength': `${20 + 24 * row[column] / totals[index]}%` } : undefined">
          {{ row[column] }}
        </td>
        <td>{{ totals[index] }}</td>
      </tr></tbody>
      <tfoot><tr>
        <th scope="row">{{ zh ? '合计' : 'Total' }}</th>
        <td v-for="column in visibleColumns" :key="column">{{ columns[column] }}</td>
        <td>{{ totals.reduce((sum, count) => sum + count, 0) }}</td>
      </tr></tfoot>
    </table>
  </div>
  <div v-if="pageCount > 1" class="matrix-pagination">
    <Button size="sm" :disabled="page === 0" @click="page--">{{ zh ? '上一组预测类别' : 'Previous prediction classes' }}</Button>
    <span>{{ page + 1 }} / {{ pageCount }}</span>
    <Button size="sm" :disabled="page + 1 >= pageCount" @click="page++">{{ zh ? '下一组预测类别' : 'Next prediction classes' }}</Button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Button from '@/shared/ui/components/Button.vue'

const props = defineProps<{ labels: string[]; rows: number[][]; zh: boolean }>()
const page = ref(0)
const pageSize = 6
const pageCount = computed(() => Math.ceil(props.labels.length / pageSize))
const visibleColumns = computed(() => Array.from(
  { length: Math.max(0, Math.min(pageSize, props.labels.length - page.value * pageSize)) },
  (_, index) => index + page.value * pageSize,
))
watch(pageCount, count => { page.value = Math.min(page.value, Math.max(0, count - 1)) })
const totals = computed(() => props.rows.map(row => row.reduce((sum, count) => sum + count, 0)))
const columns = computed(() => props.labels.map((_, index) => props.rows.reduce((sum, row) => sum + (row[index] ?? 0), 0)))
function labelParts(label: string): string[] { return label.split(/(?<=_)/) }
</script>

<style scoped>
.matrix-table { overflow:auto; max-height:420px; font-variant-numeric:tabular-nums; }
.matrix-table table { table-layout:fixed; }
.matrix-table :is(th,td) { text-align:center; }
.matrix-table th { overflow-wrap:anywhere; line-height:1.35; }
.matrix-table th:first-child { width:122px; }
.matrix-table td { overflow-wrap:anywhere; }
.matrix-pagination { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; margin-top:10px; }
.matrix-table thead { position:sticky; top:0; background:var(--am-surface-soft); }
.matrix-table tfoot { background:var(--am-surface-soft); font-weight:600; }
.matrix-table .has-count { background:var(--am-surface-soft); }
.matrix-table .diagonal { background:color-mix(in srgb,var(--am-brand-primary) var(--diagonal-strength,20%),var(--am-surface)); color:var(--am-text-strong); font-weight:600; }
</style>
