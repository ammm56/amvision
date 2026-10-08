<template>
  <section ref="tableElement" class="result-table" @mousedown.stop @dblclick.stop @wheel.stop>
    <div class="result-table__tools">
      <input v-model="query" type="search" :placeholder="zh?'搜索检查项':'Search items'" :aria-label="zh?'搜索检查项':'Search items'">
      <label><input v-model="failedOnly" type="checkbox">{{ zh?'仅不通过':'Failed only' }}</label>
      <span>{{ visible.length }} / {{ table.rows.length }}</span>
    </div>
    <div class="result-table__scroll"><table><thead><tr><th v-for="column in table.columns" :key="column.key">{{ column.label }}</th></tr></thead><tbody>
      <tr v-for="row in pageRows" :key="String(row.item_id)" tabindex="0" role="button" :aria-label="String(row.item_id)" :aria-pressed="modelValue===row.item_id" :class="{selected:modelValue===row.item_id,failed:row.passed===false}" @click="select(row)" @keydown.enter.prevent="select(row)" @keydown.space.prevent="select(row)">
        <td v-for="column in table.columns" :key="column.key" :title="String(row[column.key]??'')">{{ formatResultCell(row[column.key],column.format??resultFormats[column.key],zh,reasonLabels) }}</td>
      </tr>
    </tbody></table></div>
    <PaginationControls v-if="visible.length>100" :offset="offset" :limit="100" :item-count="pageRows.length" :total-count="visible.length" @previous="offset-=100" @next="offset+=100" />
    <p v-if="selected && !shape">{{ zh?'此项没有可显示的几何位置。':'No geometry available for this item.' }}</p>
    <p v-if="shape?.kind==='expected-point'">{{ zh?'虚线标记为预期位置，未获得有效实测几何。':'Dashed marker is the expected position; no valid measured geometry is available.' }}</p>
    <details v-if="selected"><summary>{{ zh?'原始数据':'Raw data' }}</summary><pre>{{ JSON.stringify(selected,null,2) }}</pre></details>
  </section>
</template>
<script setup lang="ts">
import {computed,ref,watch,nextTick,inject} from 'vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import {useI18n} from 'vue-i18n'
import {selectedResultShape,type ResultTable} from '@/shared/ui/image-viewer/result-geometry'
import {formatResultCell,resultReasonLabelsKey,type ResultColumnFormat} from '@/shared/ui/image-viewer/result-format'
const props=defineProps<{table:ResultTable;modelValue?:string|null}>()
const emit=defineEmits<{'update:modelValue':[id:string|null]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const reasonLabels=inject(resultReasonLabelsKey,{})
const query=ref(''),failedOnly=ref(false)
const visible=computed(()=>props.table.rows.filter(row=>(!failedOnly.value||row.passed===false)&&String(row.item_id??'').toLowerCase().includes(query.value.toLowerCase())))
const offset=ref(0),pageRows=computed(()=>visible.value.slice(offset.value,offset.value+100))
watch([query,failedOnly,()=>props.table.observation_id],()=>{offset.value=0})
const tableElement=ref<HTMLElement>()
watch(()=>props.modelValue,async()=>{const index=visible.value.findIndex(row=>row.item_id===props.modelValue);if(index<0)return;offset.value=Math.floor(index/100)*100;await nextTick();tableElement.value?.querySelector('[aria-pressed="true"]')?.scrollIntoView?.({block:'nearest'})},{immediate:true})
const selected=computed(()=>props.table.rows.find(row=>row.item_id===props.modelValue))
const shape=computed(()=>selectedResultShape(props.table,props.modelValue))
watch(()=>props.table.observation_id,()=>{emit('update:modelValue',null)})
function select(row:Record<string,unknown>){emit('update:modelValue',typeof row.item_id==='string'?row.item_id:null)}
const resultFormats:Record<string,ResultColumnFormat>={unit:'unit',passed:'result',valid:'validity',reason:'reason'}
</script>
<style scoped>
.result-table { display:flex;flex-direction:column;gap:6px;min-height:0;max-height:100%;font-size:12px;color:var(--am-text);background:var(--am-surface);padding:8px;overflow:auto; }
.result-table__tools { display:flex;gap:12px;align-items:center;flex-wrap:wrap; }
.result-table__tools label { display:flex;gap:6px;align-items:center; }
input[type=search] { border:1px solid var(--am-border);color:var(--am-text);background:var(--am-input);border-radius:4px;padding:4px 8px;min-width:0; }
input[type=checkbox] { width:16px;height:16px;min-width:16px;padding:0; }
.result-table__scroll { min-height:60px;overflow:auto;flex:1; }
table { border-collapse:collapse;min-width:660px;width:100%; }
th,td { padding:5px 8px;border-bottom:1px solid var(--am-border);text-align:left;white-space:nowrap; }
th { position:sticky;top:0;background:var(--am-surface-soft); }
tr[role=button] { cursor:pointer; }
tr[role=button]:hover { background:var(--am-surface-soft); }
tr.selected { background:color-mix(in srgb,var(--am-brand-primary) 12%,var(--am-surface)); }
tr.failed td:first-child { color:var(--am-danger-text); }
p { margin:0;color:var(--am-text-muted); } pre { max-height:180px;overflow:auto; } summary { cursor:pointer; }
</style>
