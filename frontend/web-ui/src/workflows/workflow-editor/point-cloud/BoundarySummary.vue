<template>
  <section class="boundary-summary">
    <table><thead><tr><th>{{ zh?'特征':'Feature' }}</th><th>{{ zh?'类型':'Type' }}</th><th>{{ zh?'状态':'State' }}</th><th>{{ zh?'支持段':'Segments' }}</th></tr></thead>
      <tbody><tr v-for="item in items" :key="item.feature_id" :class="{selected:item.feature_id===selected}">
        <td><button @click="emit('select',item.feature_id,'')">{{ item.feature_id }}</button></td>
        <td>{{ names[item.kind] }} · {{ item.vertex_kind==='generated'?(zh?'生成顶点':'Generated'):(zh?'源点':'Source points') }}</td>
        <td>{{ item.valid?(zh?'几何可用':'Geometry usable'):item.reason }}<template v-if="item.failed_segment_id"> · {{ item.failed_segment_id }}</template></td>
        <td><button v-for="segment in item.topology?.segments??[]" :key="segment.segment_id" :aria-pressed="item.feature_id===selected&&segment.segment_id===selectedSegment" @click="emit('select',item.feature_id,segment.segment_id)">{{ segment.segment_id }} · {{ segment.closed?(zh?'闭合':'Closed'):(zh?'开放':'Open') }} · {{ segment.role }} · {{ segment.count }}</button></td>
      </tr></tbody>
    </table>
    <details v-if="current"><summary>{{ zh?'几何质量':'Geometry quality' }} · {{ current.feature_id }}</summary><table><thead><tr><th>{{ zh?'指标':'Metric' }}</th><th>{{ zh?'值':'Value' }}</th><th>{{ zh?'单位':'Unit' }}</th><th>{{ zh?'原因':'Reason' }}</th></tr></thead><tbody><tr v-for="metric in metrics" :key="String(metric.item_id)"><td>{{ metric.item_id }}</td><td>{{ metric.value??'-' }}</td><td>{{ metric.unit }}</td><td>{{ metric.reason??'-' }}</td></tr></tbody></table></details>
  </section>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import type {CurveDisplay} from './boundary-display'
import {object} from './preview-data'
const props=defineProps<{items:CurveDisplay[];selected:string;selectedSegment:string}>()
const emit=defineEmits<{select:[featureId:string,segmentId:string]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const names=computed(()=>zh.value?{boundary:'边界',line:'直线',circle:'圆'}:{boundary:'Boundary',line:'Line',circle:'Circle'})
const current=computed(()=>props.items.find(i=>i.feature_id===props.selected))
const metrics=computed(()=>{const rows=current.value?object(current.value.quality.metrics).items:[];return Array.isArray(rows)?rows.map(object):[]})
</script>
<style scoped>
.boundary-summary{overflow:auto;max-height:210px;font-size:12px;min-width:0}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:6px;border-bottom:1px solid var(--am-border);overflow-wrap:anywhere}button{font:inherit;border:0;background:transparent;color:var(--am-text);padding:4px;cursor:pointer}button[aria-pressed=true],.selected>td{background:var(--am-success-surface)}summary{cursor:pointer;padding:6px;font-weight:600}
</style>
