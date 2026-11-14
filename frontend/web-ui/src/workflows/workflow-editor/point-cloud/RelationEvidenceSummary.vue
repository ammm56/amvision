<template>
  <section v-if="item?.kind === 'measure-relation'" class="relation-evidence">
    <p v-if="nonunique">{{ zh ? '最近点对不唯一' : 'Closest pair is not unique' }}</p>
    <p v-if="item.diagnostic?.role">{{ zh ? '失败对象' : 'Failed operand' }}: {{ item.diagnostic.role === 'reference' ? 'A' : 'B' }} · {{ item.diagnostic.stage }}</p>
    <table><thead><tr><th>{{ zh ? '对象' : 'Operand' }}</th><th>{{ zh ? '来源 / 特征' : 'Source / feature' }}</th><th>{{ zh ? '坐标 / 原始行号' : 'Position / source row' }}</th></tr></thead>
      <tbody><tr v-for="side in item.support" :key="String(side.role)"><th>{{ side.role === 'reference' ? 'A' : 'B' }}</th><td>{{ origin(side) }}<div>{{ featureId(side) }}</div></td><td>{{ object(side.point).point ?? '-' }}<div v-if="object(side.point).source_index !== null && object(side.point).source_index !== undefined">{{ object(side.point).source_index }}</div></td></tr></tbody>
    </table>
  </section>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {object as requireObject} from './preview-data'
import type {MeasurementDisplay} from './measurement-display'
const props=defineProps<{item?:MeasurementDisplay;zh:boolean}>()
// 质量失败时不提供可绘制几何；唯一性仍来自同次计算的质量证据。
const nonunique=computed(()=>{
  if(props.item?.geometry?.contacts_unique===false)return true
  const raw=props.item?.quality?.metrics
  if(!raw)return false
  const metrics=object(raw)
  if(!Array.isArray(metrics.items))return false
  return metrics.items.some(value=>{
    const metric=object(value)
    return metric.item_id==='contacts_unique'&&metric.valid===true&&metric.unit==='1'&&metric.value===0
  })
})
function object(value:unknown){return value===null?{}:requireObject(value)}
function origin(side:Record<string,unknown>){const value=object(side.point).origin;return value?(props.zh?({measured:'实测原始点',estimated:'拟合圆心',specified:'指定坐标'} as Record<string,string>)[String(value)]:String(value)):(props.zh?'拟合模型':'Fitted model')}
function featureId(side:Record<string,unknown>){return side.feature!==null?object(side.feature).feature_id:side.plane!==null?object(object(object(side.plane).method).parameters).feature_id:''}
</script>
<style scoped>
.relation-evidence{min-width:0;font-size:12px;overflow-wrap:anywhere}.relation-evidence p{margin:6px 0}table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:6px;border-bottom:1px solid var(--am-border)}
</style>
