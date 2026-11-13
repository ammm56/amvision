<template>
  <div class="measurement-summary">
    <div class="summary-tools"><span>{{ zh?'几何结果 · 未作产品公差判定':'Geometry results · no product tolerance decision' }}</span><label>{{ zh?'显示小数':'Display decimals' }}<select v-model="precision"><option value="raw">{{ zh?'原值':'Original' }}</option><option v-for="n in [2,3,4,6]" :key="n" :value="n">{{ n }}</option></select></label></div>
    <table><thead><tr><th>{{ zh?'测量项':'Measurement' }}</th><th>{{ zh?'数值':'Value' }}</th><th>{{ zh?'状态 / 原因':'State / reason' }}</th><th>{{ zh?'支持点数':'Support points' }}</th></tr></thead>
      <tbody><tr v-for="item in items" :key="item.item_id" :class="{selected:item.item_id===selected}"><td><button :aria-pressed="item.item_id===selected" @click="$emit('select',item.item_id)">{{ item.item_id }}</button><div v-if="item.component">{{ item.kind==='measure-relation'?(item.component==='angle'?(zh?'夹角':'Angle'):(zh?'距离':'Distance')):componentLabel(item.component) }}</div></td><td class="measurement-number"><span class="measurement-value" :title="item.valid?String(item.value):undefined">{{ displayValue(item) }}</span> <span class="measurement-unit">{{ measurementUnit(item,unit) }}</span></td><td>{{ item.valid?(zh?'几何有效':'Geometry valid'):(zh?'几何无效':'Geometry invalid') }}<div v-if="!item.valid">{{ measurementReason(item.reason,zh) }}</div><div v-if="ambiguous(item)">{{ zh?'尺寸一致，方向不唯一':'Consistent size, ambiguous orientation' }}</div></td><td>{{ item.support.map(s=>s.point_count??'-').join(' / ') }}</td></tr></tbody>
    </table>
    <dl v-if="current" class="extension-evidence"><dt>{{ zh?'测量方法':'Measurement method' }}</dt><dd>{{ measurementMethod(current,zh) }}</dd></dl>
    <ArcEvidenceSummary :item="current" :unit="unit" :zh="zh" :precision="precision" :selected-segment="selectedSegment" @select-segment="selectArcSegment" />
    <RelationEvidenceSummary :item="current" :zh="zh" />
    <DeviationEvidenceSummary :item="current" :zh="zh" :unit="unit" />
    <dl v-if="robust(current)" class="extension-evidence">
      <dt>{{ zh?'测量方法':'Measurement method' }}</dt><dd>{{ zh?'可见包络 · 稳健剖面跨度':'Visible envelope · robust profile spans' }}</dd>
      <dt>{{ zh?'低侧 / 高侧分位数':'Lower / upper quantiles' }}</dt><dd>{{ mode.lower_quantile }} / {{ mode.upper_quantile }} · linear</dd>
      <dt>{{ zh?'支持类型':'Support type' }}</dt><dd>{{ zh?'格中心插值 / 格边估计':'Cell-center interpolation / cell-edge estimates' }}</dd>
    </dl>
    <details v-if="contacts.length"><summary>{{ zh?'统计端点来源':'Statistical contacts' }}</summary><table><thead><tr><th>{{ zh?'侧 / 分位数':'Side / quantile' }}</th><th>{{ zh?'样本数 / 排名':'Count / ranks' }}</th><th>{{ zh?'顶点 / 权重':'Vertices / weight' }}</th></tr></thead><tbody><tr v-for="contact in contacts" :key="String(contact.side)"><td>{{ contact.side }} / {{ contact.quantile }}</td><td>{{ contact.sample_count }} / {{ contact.ranks }}</td><td>{{ contact.vertex_indices }} / {{ contact.weight }}</td></tr></tbody></table></details>
    <dl v-if="current?.query" class="extension-evidence">
      <dt>{{ zh?'查询来源':'Query source' }}</dt><dd>{{ current.query.kind==='pose-uv'?(zh?'本次基准坐标':'Current datum'):(zh?'配置位置和方向':'Configured position and direction') }}</dd>
      <template v-if="current.query.kind==='pose-uv'"><dt>{{ zh?'位姿 / 坐标系':'Pose / frame' }}</dt><dd>{{ current.query.poseId }} / {{ current.query.frameId }}</dd><dt>U / V</dt><dd>{{ current.query.uv?.join(', ') }} {{ unit }}</dd></template>
      <template v-if="current.query.position"><dt>{{ zh?'本次源坐标 XYZ':'Resolved source XYZ' }}</dt><dd>{{ current.query.position.join(', ') }} {{ unit }}</dd><dt>{{ zh?'本次测量方向':'Resolved direction' }}</dt><dd>{{ current.query.direction?.join(', ') }}</dd></template>
      <template v-else><dt>{{ zh?'来源无效':'Source unavailable' }}</dt><dd>{{ current.query.reason }}</dd></template>
    </dl>
    <dl v-if="extension" class="extension-evidence">
      <dt>{{ zh?'基准支持':'Datum support' }}</dt><dd>{{ extensionLabel(extension.state) }}</dd>
      <dt>{{ zh?'实际延伸 / 上限':'Extension / limit' }}</dt><dd>{{ extension.distance??'-' }} / {{ extension.max_distance }} {{ unit }}</dd>
      <template v-if="extension.source_index!==null"><dt>{{ zh?'最近实测点原始行号':'Nearest measured source index' }}</dt><dd>{{ extension.source_index }}</dd></template>
    </dl>
    <details v-if="current"><summary>{{ zh?'质量证据':'Quality evidence' }} · {{ current.item_id }}</summary><table><tbody><tr v-for="metric in metrics" :key="String(metric.item_id)"><th>{{ metric.item_id }}</th><td>{{ metric.valid?metric.value:metric.reason }} {{ metric.unit??'' }}</td></tr></tbody></table></details>
  </div>
</template>
<script setup lang="ts">
import {computed,ref} from 'vue'
import {useI18n} from 'vue-i18n'
import {object} from './preview-data'
import {referenceExtension,type MeasurementDisplay} from './measurement-display'
import {measurementMethod,measurementReason} from './measurement-labels'
import {measurementUnit} from './arc-display'
import ArcEvidenceSummary from './ArcEvidenceSummary.vue'
import RelationEvidenceSummary from './RelationEvidenceSummary.vue'
import DeviationEvidenceSummary from './DeviationEvidenceSummary.vue'
import {deviationComponentLabel} from './deviation-display'
import {formatDisplayField} from '../preview/value-display'
const props=defineProps<{items:MeasurementDisplay[];unit:string;selected:string;selectedSegment?:string}>()
const emit=defineEmits<{select:[id:string];'select-segment':[featureId:string,segmentId:string]}>()
function selectArcSegment(id:string){const feature=object(current.value?.support[0]?.feature);if(typeof feature.feature_id==='string')emit('select-segment',feature.feature_id,id)}
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const precision=ref<number|'raw'>(4)
function displayValue(item:MeasurementDisplay){
  if(!item.valid)return '-'
  if(precision.value==='raw')return String(item.value)
  const formatted=formatDisplayField({label:'',value:item.value,format:'number',precision:precision.value,states:{}})
  // 非零量值不能因显示小数位被伪装为零，计算及证据始终保留原值。
  return item.value!==0&&Number(formatted)===0?String(item.value):formatted
}
const current=computed(()=>props.items.find(i=>i.item_id===props.selected)),metrics=computed(()=>{const raw=current.value?object(current.value.quality.metrics).items:[];return Array.isArray(raw)?raw.map(object):[]})
const extension=computed(()=>current.value?referenceExtension(current.value.support):null)
const mode=computed(()=>robust(current.value)?object(object(current.value!.method.parameters).mode):{})
const contacts=computed(()=>{const rows=current.value?.geometry?.contacts;return robust(current.value)&&Array.isArray(rows)?rows.map(c=>object(object(c).statistic)):[]})
function robust(item:MeasurementDisplay|undefined){return item?.kind==='measure-extents'&&object(object(item.method.parameters).mode).kind==='robust-profile-spans'}
function extensionLabel(state:string){return (zh.value?{covered:'有实测支持，未延伸',used:'已使用基准延伸','limit-exceeded':'基准延伸超限',unavailable:'基准不可用'}:{covered:'Measured support; not extended',used:'Datum extension used','limit-exceeded':'Datum extension limit exceeded',unavailable:'Datum unavailable'})[state]??state}
function componentLabel(key:string){if(['min','max','peak-to-valley','mean','rms'].includes(key))return deviationComponentLabel(key,zh.value);return zh.value?({u:'U 投影跨度',v:'V 投影跨度',length:'包络长边',width:'包络短边',distance:'指定位置边间距',diameter:'拟合圆直径',center_x:'圆心 X',center_y:'圆心 Y',center_z:'圆心 Z',radius:'圆半径',signed_sweep:'有符号扫角',sweep:'扫角',arc_length:'圆模型弧长',chord_length:'圆模型弦长',coverage_angle:'支持角区并集',supported_length:'圆模型支持弧长',start_x:'投影起点 X',start_y:'投影起点 Y',start_z:'投影起点 Z',end_x:'投影终点 X',end_y:'投影终点 Y',end_z:'投影终点 Z'} as Record<string,string>)[key]??key:key}
function ambiguous(item:MeasurementDisplay){return item.valid&&item.geometry?.kind==='projected-extents'&&item.geometry.candidates&&object(item.geometry.candidates).orientation_unique===false}
</script>
<style scoped>
.measurement-summary{overflow:auto;max-height:200px;font-size:12px;min-width:0;overflow-wrap:anywhere}
table{border-collapse:collapse;width:100%;min-width:460px}th,td{text-align:left;border-bottom:1px solid var(--am-border);padding:6px;vertical-align:top}
.measurement-number{white-space:nowrap;font-variant-numeric:tabular-nums}.measurement-unit{color:var(--am-text-muted)}
button{border:0;background:transparent;color:var(--am-brand-primary);padding:0;cursor:pointer;font:inherit;text-align:left;overflow-wrap:anywhere}
.selected{background:var(--am-surface-soft);box-shadow:inset 3px 0 var(--am-brand-primary)}summary{cursor:pointer;padding:6px 0}
.summary-tools{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;padding:6px;position:sticky;top:0;z-index:1;background:var(--am-surface)}.summary-tools label{display:flex;gap:6px;align-items:center}
.extension-evidence{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px;margin:8px 0}.extension-evidence dd{margin:0}
</style>
