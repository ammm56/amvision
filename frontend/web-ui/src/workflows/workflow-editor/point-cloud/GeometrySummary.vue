<template>
  <div class="geometry-summary">
    <table v-if="planes.length"><thead><tr><th>{{ zh?'特征':'Feature' }}</th><th>{{ zh?'几何状态':'Geometry state' }}</th><th>{{ zh?'支持点数':'Support count' }}</th><th>{{ zh?'质量指标':'Quality metrics' }}</th></tr></thead>
      <tbody><tr v-for="plane in planes" :key="String(plane.feature_id)" :class="{selected:plane.feature_id===selected}"><td><button :aria-pressed="plane.feature_id===selected" @click="$emit('select-plane',String(plane.feature_id))">{{ plane.feature_id }}</button></td><td>{{ plane.valid?(zh?'有效':'Valid'):plane.reason }}</td><td>{{ plane.support_point_count??'-' }}</td><td>{{ metrics(plane.quality) }}</td></tr></tbody></table>
    <p v-if="frame">{{ frame.pose_id }} · {{ frame.source_frame_id }} → {{ frame.target_frame_id }} · {{ frame.state }}<template v-if="frame.reason"> · {{ frame.reason }}</template> · {{ metrics(frame.quality) }}</p>
  </div>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
const props=defineProps<{geometry:Record<string,unknown>;selected?:string}>(),{locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
defineEmits<{'select-plane':[id:string]}>()
const record=(v:unknown):Record<string,unknown>=>v&&typeof v==='object'&&!Array.isArray(v)?v as Record<string,unknown>:{}
const planes=computed(()=>(Array.isArray(props.geometry.planes)?props.geometry.planes:[]).map(record)),frame=computed(()=>props.geometry.frame?record(props.geometry.frame):null)
function metrics(value:unknown){const m=record(record(value).metrics);return (Array.isArray(m.items)?m.items:[]).map(record).map(i=>`${i.item_id}: ${i.valid?i.value:i.reason} ${i.unit??''}`).join(' · ')}
</script>
<style scoped>
.geometry-summary {overflow:auto;max-height:170px;font-size:12px;min-width:0;overflow-wrap:anywhere}
button{border:0;background:transparent;color:var(--am-brand-primary);padding:0;cursor:pointer;font:inherit;overflow-wrap:anywhere;text-align:left}.selected{background:var(--am-success-surface)}
table {border-collapse:collapse;width:100%;min-width:520px;table-layout:fixed}th,td {padding:6px;border-bottom:1px solid var(--am-border);text-align:left}th:nth-child(1){width:90px}th:nth-child(2){width:100px}th:nth-child(3){width:100px}p {margin:6px 0}
</style>
