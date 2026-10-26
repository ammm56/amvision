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
    <details v-if="current"><summary>{{ zh?'评价面与等高来源':'Evaluation and contour source' }} · {{ current.feature_id }}</summary>
      <dl class="source-details">
        <dt>{{ zh?'评价面来源':'Evaluation source' }}</dt><dd>{{ object(object(current.method).parameters).evaluation && object(object(object(current.method).parameters).evaluation).kind==='feature'?(zh?'继承所选特征':'Selected feature'):(zh?'提取时解析':'Resolved at extraction') }}</dd>
        <dt>{{ zh?'评价原点':'Evaluation origin' }}</dt><dd>{{ evaluation.origin??'-' }}</dd>
        <dt>U / V / N</dt><dd>{{ evaluation.rotation??'-' }}</dd>
        <template v-if="resolution.pose">
          <dt>{{ zh?'位姿 / 基准':'Pose / datum' }}</dt><dd>{{ object(resolution.pose).pose_id }} / {{ object(resolution.datum).feature_id }}</dd>
          <dt>{{ zh?'等高值':'Contour height' }}</dt><dd>{{ resolution.height??'-' }} {{ evaluation.length_unit }}</dd>
          <dt>{{ zh?'原观测':'Source observation' }}</dt><dd>{{ resolution.observation_id }}</dd>
          <template v-if="resolution.measurement"><dt>{{ zh?'测量量 / 端点':'Measurement / endpoints' }}</dt><dd>{{ object(resolution.measurement).item_id }} / {{ object(object(resolution.measurement).geometry).endpoints??'-' }}</dd><dt>{{ zh?'比例 / 顺序':'Ratio / order' }}</dt><dd>{{ contourHeight.ratio }} / {{ contourHeight.order==='target-above'?(zh?'目标高于基体':'Target above reference'):(zh?'目标低于基体':'Target below reference') }}</dd></template>
        </template>
      </dl>
    </details>
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
const boundaryMethod=computed(()=>current.value?.kind==='boundary'?object(current.value.method):object(object(current.value?.method.boundary).method))
const resolution=computed(()=>object(boundaryMethod.value.resolution))
const evaluation=computed(()=>object(current.value?.kind==='boundary'?resolution.value.evaluation:current.value?.method.evaluation))
const contourHeight=computed(()=>object(object(object(boundaryMethod.value.parameters).method).height))
const metrics=computed(()=>{const rows=current.value?object(current.value.quality.metrics).items:[];return Array.isArray(rows)?rows.map(object):[]})
</script>
<style scoped>
.boundary-summary{overflow:auto;max-height:210px;font-size:12px;min-width:0}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:6px;border-bottom:1px solid var(--am-border);overflow-wrap:anywhere}button{font:inherit;border:0;background:transparent;color:var(--am-text);padding:4px;cursor:pointer}button[aria-pressed=true],.selected>td{background:var(--am-success-surface)}summary{cursor:pointer;padding:6px;font-weight:600}.source-details{display:grid;grid-template-columns:minmax(80px,auto) minmax(0,1fr);gap:6px;margin:6px}.source-details dd{margin:0;overflow-wrap:anywhere}
</style>
