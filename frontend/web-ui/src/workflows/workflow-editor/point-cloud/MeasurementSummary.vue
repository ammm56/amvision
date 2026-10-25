<template>
  <div class="measurement-summary">
    <table><thead><tr><th>{{ zh?'测量项':'Measurement' }}</th><th>{{ zh?'数值':'Value' }}</th><th>{{ zh?'状态 / 原因':'State / reason' }}</th><th>{{ zh?'支持点数':'Support points' }}</th></tr></thead>
      <tbody><tr v-for="item in items" :key="item.item_id" :class="{selected:item.item_id===selected}"><td><button :aria-pressed="item.item_id===selected" @click="$emit('select',item.item_id)">{{ item.item_id }}</button><div v-if="item.component">{{ componentLabel(item.component) }}</div></td><td>{{ item.valid?item.value:'-' }} {{ unit }}</td><td>{{ item.valid?(zh?'有效':'Valid'):item.reason }}<div v-if="ambiguous(item)">{{ zh?'尺寸一致，方向不唯一':'Consistent size, ambiguous orientation' }}</div></td><td>{{ item.support.map(s=>s.point_count??'-').join(' / ') }}</td></tr></tbody>
    </table>
    <dl v-if="extension" class="extension-evidence">
      <dt>{{ zh?'基准支持':'Datum support' }}</dt><dd>{{ extensionLabel(extension.state) }}</dd>
      <dt>{{ zh?'实际延伸 / 上限':'Extension / limit' }}</dt><dd>{{ extension.distance??'-' }} / {{ extension.max_distance }} {{ unit }}</dd>
      <template v-if="extension.source_index!==null"><dt>{{ zh?'最近实测点原始行号':'Nearest measured source index' }}</dt><dd>{{ extension.source_index }}</dd></template>
    </dl>
    <details v-if="current"><summary>{{ zh?'质量证据':'Quality evidence' }} · {{ current.item_id }}</summary><table><tbody><tr v-for="metric in metrics" :key="String(metric.item_id)"><th>{{ metric.item_id }}</th><td>{{ metric.valid?metric.value:metric.reason }} {{ metric.unit??'' }}</td></tr></tbody></table></details>
  </div>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import {object} from './preview-data'
import {referenceExtension,type MeasurementDisplay} from './measurement-display'
const props=defineProps<{items:MeasurementDisplay[];unit:string;selected:string}>()
defineEmits<{select:[id:string]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const current=computed(()=>props.items.find(i=>i.item_id===props.selected)),metrics=computed(()=>{const raw=current.value?object(current.value.quality.metrics).items:[];return Array.isArray(raw)?raw.map(object):[]})
const extension=computed(()=>current.value?referenceExtension(current.value.support):null)
function extensionLabel(state:string){return (zh.value?{covered:'有实测支持，未延伸',used:'已使用基准延伸','limit-exceeded':'基准延伸超限',unavailable:'基准不可用'}:{covered:'Measured support; not extended',used:'Datum extension used','limit-exceeded':'Datum extension limit exceeded',unavailable:'Datum unavailable'})[state]??state}
function componentLabel(key:string){return zh.value?({u:'U 投影跨度',v:'V 投影跨度',length:'包络长边',width:'包络短边',distance:'指定位置边间距',diameter:'拟合圆直径',center_x:'圆心 X',center_y:'圆心 Y',center_z:'圆心 Z'} as Record<string,string>)[key]??key:key}
function ambiguous(item:MeasurementDisplay){return item.valid&&item.geometry?.kind==='projected-extents'&&item.geometry.candidates&&object(item.geometry.candidates).orientation_unique===false}
</script>
<style scoped>
.measurement-summary{overflow:auto;max-height:200px;font-size:12px;min-width:0;overflow-wrap:anywhere}
table{border-collapse:collapse;width:100%;min-width:460px;table-layout:fixed}th,td{text-align:left;border-bottom:1px solid var(--am-border);padding:6px}
button{border:0;background:transparent;color:var(--am-brand-primary);padding:0;cursor:pointer;font:inherit;text-align:left;overflow-wrap:anywhere}
.selected{background:var(--am-success-surface)}summary{cursor:pointer;padding:6px 0}
.extension-evidence{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px;margin:8px 0}.extension-evidence dd{margin:0}
</style>
