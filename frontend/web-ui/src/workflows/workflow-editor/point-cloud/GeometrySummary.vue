<template>
  <div class="geometry-summary">
    <table v-if="planes.length"><thead><tr><th>{{ zh?'特征':'Feature' }}</th><th>{{ zh?'几何状态':'Geometry state' }}</th><th>{{ zh?'支持点数':'Support count' }}</th><th>{{ zh?'质量指标':'Quality metrics' }}</th></tr></thead>
      <tbody><tr v-for="plane in planes" :key="String(plane.feature_id)" :class="{selected:plane.feature_id===selected}"><td><button :aria-pressed="plane.feature_id===selected" @click="$emit('select-plane',String(plane.feature_id))">{{ plane.feature_id }}</button></td><td>{{ plane.valid?(zh?'几何有效':'Geometry valid'):(zh?'几何无效':'Geometry invalid') }}<template v-if="!plane.valid"> · {{ plane.reason }}</template></td><td>{{ plane.support_point_count??'-' }}</td><td>{{ metrics(plane.quality) }}</td></tr></tbody></table>
    <p v-if="frame">{{ frame.pose_id }} · {{ frame.source_frame_id }} → {{ frame.target_frame_id }} · {{ frame.state }}<template v-if="frame.reason"> · {{ frame.reason }}</template> · {{ metrics(frame.quality) }}</p>
    <p v-if="registration">{{ registration.scope==='feature-se3'?(zh?'特征粗定位与精化':'Feature search and refinement'):registration.scope==='datum-se2'?(zh?'台面约束 · U/V/绕 Z':'Datum constraint · U/V/yaw'):(zh?'局部配准':'Local registration') }} · {{ record(registration.parameters).algorithm }} · {{ zh?'全局唯一性：未评估':'Global uniqueness: not evaluated' }}</p>
    <template v-if="registration?.scope==='datum-se2'"><p v-for="(datum,i) in datums" :key="i">{{ i===0?(zh?'移动基准':'Moving datum'):(zh?'参考基准':'Reference datum') }}: {{ datum.pose_id }} · {{ datum.source_frame_id }} → {{ datum.target_frame_id }} · {{ datum.state }}<template v-if="datum.reason"> · {{ datum.reason }}</template></p></template>
    <template v-if="registration?.scope==='feature-se3'">
      <p>{{ zh?'双向特征对应':'Mutual feature matches' }}: {{ record(registration.search).feature_correspondence_count }} · {{ frame?.state==='ambiguous'?(zh?'本次搜索发现多解':'Multiple poses found in this search'):frame?.state==='found'?(zh?'本次有限搜索未见多解':'No competing pose found in this finite search'):(zh?'本次搜索无可用姿态':'No usable pose found in this search') }}</p>
      <table class="candidate-table"><thead><tr><th>{{ zh?'候选批次':'Trial' }}</th><th>{{ zh?'结果':'Result' }}</th><th>{{ zh?'质量指标':'Quality metrics' }}</th></tr></thead><tbody><tr v-for="candidate in candidates" :key="String(candidate.trial)"><td>{{ Number(candidate.trial)+1 }}</td><td>{{ record(candidate.quality).usable?(zh?'通过':'Passed'):candidate.reason }}</td><td><details><summary>{{ zh?'逐项指标':'All metrics' }}</summary><p>{{ metrics(candidate.quality) }}</p></details></td></tr></tbody></table>
    </template>
    <ol v-if="steps.length"><li v-for="(step,i) in steps" :key="i">{{ record(step.pose).pose_id }} · {{ step.inverse?record(step.pose).target_frame_id:record(step.pose).source_frame_id }} → {{ step.inverse?record(step.pose).source_frame_id:record(step.pose).target_frame_id }}</li></ol>
  </div>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
const props=defineProps<{geometry:Record<string,unknown>;selected?:string}>(),{locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
defineEmits<{'select-plane':[id:string]}>()
const record=(v:unknown):Record<string,unknown>=>v&&typeof v==='object'&&!Array.isArray(v)?v as Record<string,unknown>:{}
const planes=computed(()=>(Array.isArray(props.geometry.planes)?props.geometry.planes:[]).map(record)),frame=computed(()=>props.geometry.frame?record(props.geometry.frame):null)
const steps=computed(()=>{const steps=record(frame.value?.method).steps;return Array.isArray(steps)?steps.map(record):[]})
const registration=computed(()=>{const m=record(frame.value?.method);return m.method_id==='register-cloud'?m:null})
const candidates=computed(()=>{const c=record(registration.value?.search).candidates;return Array.isArray(c)?c.map(record):[]})
const datums=computed(()=>{const c=record(registration.value?.datum).frames;return Array.isArray(c)?c.map(record):[]})
function metrics(value:unknown){const m=record(record(value).metrics);return (Array.isArray(m.items)?m.items:[]).map(record).map(i=>`${i.item_id}: ${i.valid?i.value:i.reason} ${i.unit??''}`).join(' · ')}
</script>
<style scoped>
.geometry-summary {overflow:auto;max-height:170px;font-size:12px;min-width:0;overflow-wrap:anywhere}
button{border:0;background:transparent;color:var(--am-brand-primary);padding:0;cursor:pointer;font:inherit;overflow-wrap:anywhere;text-align:left}.selected{background:var(--am-surface-soft);box-shadow:inset 3px 0 var(--am-brand-primary)}
table {border-collapse:collapse;width:100%;min-width:520px;table-layout:fixed}th,td {padding:6px;border-bottom:1px solid var(--am-border);text-align:left}th:nth-child(1){width:90px}th:nth-child(2){width:100px}th:nth-child(3){width:100px}p {margin:6px 0}
.candidate-table{min-width:0}.candidate-table th:nth-child(1){width:54px}.candidate-table th:nth-child(2){width:78px}.candidate-table th:nth-child(3){width:auto}.candidate-table td{vertical-align:top}.candidate-table summary{cursor:pointer}
</style>
