<template>
  <dl v-if="item?.kind==='measure-deviation'" class="deviation-evidence">
    <dt>{{ zh?'目标点数 / 可计算点数':'Target / computable points' }}</dt><dd>{{ summary.target_count }} / {{ stats.count??0 }}</dd>
    <dt>{{ zh?'实测覆盖 / 有限延伸':'Measured support / bounded extension' }}</dt><dd>{{ counts.covered }} / {{ counts.extended }}</dd>
    <template v-for="key in failures" :key="key"><dt>{{ labels[key] }}</dt><dd>{{ counts[key] }}</dd></template>
    <template v-if="summary.diagnostic_only&&summary.diagnostic"><dt>{{ zh?'诊断统计（非有效测量值）':'Diagnostic statistics (not valid measurements)' }}</dt><dd>{{ stats.minimum }} / {{ stats.maximum }} / {{ stats.peak_to_valley }} / {{ stats.mean }} / {{ stats.rms }} {{ unit }}</dd></template>
    <template v-if="summary.diagnostic"><dt>{{ zh?'最小 / 最大值原始行号':'Min / max original row' }}</dt><dd>{{ object(stats.minimum_source).source_index }} / {{ object(stats.maximum_source).source_index }}</dd><dt>{{ zh?'极值并列点数':'Extreme tie counts' }}</dt><dd>{{ object(stats.minimum_source).tie_count }} / {{ object(stats.maximum_source).tie_count }}</dd></template>
    <dt>{{ zh?'基准正方向':'Datum positive direction' }}</dt><dd>{{ object(object(item.support[0]?.plane).geometry).normal }}</dd>
  </dl>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {object} from './preview-data'
import type {MeasurementDisplay} from './measurement-display'
const props=defineProps<{item?:MeasurementDisplay;unit:string;zh:boolean}>()
const summary=computed(()=>object(props.item?.diagnostic)),counts=computed(()=>object(summary.value.counts)),stats=computed(()=>object(summary.value.diagnostic))
const failures=['invalid_target','invalid_reference','outside_support','support_quality_failed','extension_limit_exceeded']
const labels=computed<Record<string,string>>(()=>props.zh?{invalid_target:'无效目标点',invalid_reference:'基准无效',outside_support:'无实测支持',support_quality_failed:'支持质量未通过',extension_limit_exceeded:'延伸超限'}:{invalid_target:'Invalid target',invalid_reference:'Invalid datum',outside_support:'Outside support',support_quality_failed:'Support quality failed',extension_limit_exceeded:'Extension limit exceeded'})
</script>
<style scoped>.deviation-evidence{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px;margin:8px 0;overflow-wrap:anywhere}.deviation-evidence dd{margin:0}</style>
