<template>
  <div class="measurement-summary">
    <table><thead><tr><th>{{ zh?'测量项':'Measurement' }}</th><th>{{ zh?'数值':'Value' }}</th><th>{{ zh?'状态 / 原因':'State / reason' }}</th><th>{{ zh?'支持点数（基准 / 目标）':'Support (reference / target)' }}</th></tr></thead>
      <tbody><tr v-for="item in items" :key="item.item_id" :class="{selected:item.item_id===selected}"><td><button :aria-pressed="item.item_id===selected" @click="$emit('select',item.item_id)">{{ item.item_id }}</button></td><td>{{ item.valid?item.value:'-' }} {{ unit }}</td><td>{{ item.valid?(zh?'有效':'Valid'):item.reason }}</td><td>{{ item.support[0]?.point_count??'-' }} / {{ item.support[1]?.point_count??'-' }}</td></tr></tbody>
    </table>
    <details v-if="current"><summary>{{ zh?'质量证据':'Quality evidence' }} · {{ current.item_id }}</summary><table><tbody><tr v-for="metric in metrics" :key="String(metric.item_id)"><th>{{ metric.item_id }}</th><td>{{ metric.valid?metric.value:metric.reason }} {{ metric.unit??'' }}</td></tr></tbody></table></details>
  </div>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import {object} from './preview-data'
import type {MeasurementDisplay} from './measurement-display'
const props=defineProps<{items:MeasurementDisplay[];unit:string;selected:string}>()
defineEmits<{select:[id:string]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const current=computed(()=>props.items.find(i=>i.item_id===props.selected)),metrics=computed(()=>{const raw=current.value?object(current.value.quality.metrics).items:[];return Array.isArray(raw)?raw.map(object):[]})
</script>
<style scoped>
.measurement-summary{overflow:auto;max-height:200px;font-size:12px;min-width:0;overflow-wrap:anywhere}
table{border-collapse:collapse;width:100%;min-width:460px;table-layout:fixed}th,td{text-align:left;border-bottom:1px solid var(--am-border);padding:6px}
button{border:0;background:transparent;color:var(--am-brand-primary);padding:0;cursor:pointer;font:inherit;text-align:left;overflow-wrap:anywhere}
.selected{background:var(--am-success-surface)}summary{cursor:pointer;padding:6px 0}
</style>
