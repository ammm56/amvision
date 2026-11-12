<template>
  <section class="edge-panel">
    <p v-if="error" role="alert">{{ label('完整边诊断不可显示或校验失败','Complete edge diagnostic unavailable or invalid') }} · {{ error }}</p>
    <p v-else-if="loading" role="status">{{ label('正在读取边诊断','Loading edge diagnostic') }}</p>
    <template v-if="data">
      <strong>{{ label('实测配对与采样诊断','Measured pairs and sampling diagnostics') }}</strong>
      <details v-for="report in reports" :key="String(report.target_id)">
        <summary>{{ report.target_id }} · {{ report.reason??label('几何可用','Geometry usable') }}</summary>
        <dl><template v-for="(value,key) in object(report.record_counts)" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></template></dl>
        <template v-for="group in qualityGroups(report)" :key="group.id">
          <strong>{{ group.id }}</strong>
          <dl><template v-for="check in group.checks" :key="String(check.item_id)"><dt>{{ check.item_id }}</dt><dd>{{ check.value??'—' }} {{ check.unit }} · {{ check.reason??label('通过','Passed') }} · {{ check.lower??'—' }} / {{ check.upper??'—' }}</dd></template></dl>
        </template>
      </details>
      <div class="controls"><label>{{ label('记录','Record') }} <input v-model.number="index" type="number" min="0" :max="data.count-1" step="1" /></label><span>/ {{ data.count }}</span><button :disabled="!selected" :title="label('聚焦记录','Focus record')" :aria-label="label('聚焦记录','Focus record')" @click="focus"><Focus :size="18" /></button></div>
      <dl v-if="selected"><dt>{{ label('来源','Source') }}</dt><dd>{{ selected.sample&&data.sampling.vertex_kind==='generated'?label('生成顶点','Generated vertex'):label('原始行','Source row') }} {{ selected.source }}</dd><dt>XYZ</dt><dd>{{ selected.position.map(displayNumber).join(', ') }}</dd><dt>{{ label('状态','Status') }}</dt><dd>{{ status }}</dd><dt v-if="!selected.sample">{{ label('实测侧','Measured side') }}</dt><dd v-if="!selected.sample">{{ ['A','B',label('未归属','Unassigned'),label('重叠','Overlap')][selected.side] }}</dd><dt>{{ label('配对记录','Partner record') }}</dt><dd>{{ selected.partner<0?'—':selected.partner }}</dd><dt v-if="!selected.sample">{{ label('距离证据','Distance evidence') }}</dt><dd v-if="!selected.sample">{{ distanceText }}</dd><dt v-if="selected.sample">{{ label('邻接事实','Observed context') }}</dt><dd v-if="selected.sample">{{ context }}</dd></dl>
    </template>
  </section>
</template>
<script setup lang="ts">
import {computed,onBeforeUnmount,ref,shallowRef,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {Focus} from '@lucide/vue'
import {readCloudCapabilities} from '../services/measurement-resource.service'
import {object} from './preview-data'
import {displayNumber} from './view-presentation'
import {decodeEdgeDiagnostic,pairStatusNames} from './edge-display'
const props=defineProps<{payload:Record<string,unknown>;projectId:string}>()
const emit=defineEmits<{select:[value:{payload:Record<string,unknown>;points:number[][]|null}];focus:[value:{payload:Record<string,unknown>;points:number[][]}]}>()
const {locale}=useI18n(),label=(cn:string,en:string)=>locale.value==='zh-CN'?cn:en
const data=shallowRef<Awaited<ReturnType<typeof decodeEdgeDiagnostic>>|null>(null),selected=ref<ReturnType<NonNullable<typeof data.value>['record']>|null>(null),index=ref(0),error=ref(''),loading=ref(false)
let controller:AbortController|null=null,generation=0,loaded:Record<string,unknown>|null=null
const reports=computed(()=>Array.isArray(data.value?.edge.reports)?data.value!.edge.reports.map(object):[])
function qualityGroups(report:Record<string,unknown>){
  const groups=[{id:String(report.target_id),quality:report.quality},...(Array.isArray(report.segments)?report.segments.map(value=>{const segment=object(value);return {id:String(segment.segment_id),quality:segment.quality}}):[])]
  return groups.filter(group=>group.quality).map(group=>{const checks=object(group.quality).checks;return {id:group.id,checks:Array.isArray(checks)?checks.map(object):[]}})
}
const distanceText=computed(()=>{
  const metrics=selected.value?.metrics
  if(!metrics)return ''
  const unit=String(object(data.value?.edge.evaluation).length_unit??'')
  const value=(i:number)=>`${Number.isFinite(metrics[i])?displayNumber(metrics[i]!):'—'} ${unit}`.trim()
  return object(data.value?.edge.method).kind==='height-jump'
    ?`${label('面内间隙','Planar gap')}: ${value(0)} / ${label('三维距离','3D distance')}: ${value(1)} / ${label('有符号高差','Signed height difference')}: ${value(2)}`
    :`${label('三维距离','3D distance')}: ${value(1)}`
})
const status=computed(()=>{const s=selected.value;if(!s)return '';if(!s.sample){const pair=pairStatusNames[s.status]!;return label(pair[0]!,pair[1]!)}const names=[['法向无效','Invalid normal'],['邻点不足','Insufficient neighbors'],['邻域截断','Saturated neighborhood'],['重复坐标','Duplicate coordinates'],['邻点法向无效','Invalid neighbor normal']];return names.filter((_,i)=>s.status&(1<<i)).map(p=>label(p[0]!,p[1]!)).join(' / ')||(s.candidate?label('缺支持候选','Missing-support candidate'):label('完整支持','Complete support'))})
const context=computed(()=>{const s=selected.value;if(!s)return '';return [['未知缺支持','Unknown support gap'],['已知无效观测','Known invalid observation'],['缺采集行','Missing acquisition row'],['ROI 裁剪','ROI cut'],['采集范围边界','Acquisition limit']].filter((_,i)=>s.context&(1<<i)).map(p=>label(p[0]!,p[1]!)).join(' / ')||'—'})
function points(){const s=selected.value,d=data.value;return s&&d?[s.position,...(s.partner>=0?[d.record(s.partner).position]:[])]:null}
function select(){if(!data.value||!loaded)return;try{selected.value=data.value.record(index.value)}catch{selected.value=null}emit('select',{payload:loaded,points:points()})}
function focus(){const p=points();if(p&&loaded)emit('focus',{payload:loaded,points:p})}
function release(){generation++;controller?.abort();controller=null;data.value?.dispose();data.value=null;selected.value=null;if(loaded)emit('select',{payload:loaded,points:null});loaded=null}
async function load(){release();error.value='';loading.value=true;const token=generation,payload=props.payload;controller=new AbortController();const signal=controller.signal
  try{const body=object(payload.edge_diagnostics);if(body.state!=='ready')throw new Error(String(body.reason??'cloud_preview_invalid'));const policy=(await readCloudCapabilities(props.projectId,signal)).renderer;if(!policy)throw new Error('cloud_renderer_unconfigured');const result=await decodeEdgeDiagnostic(payload,policy,signal);if(signal.aborted||token!==generation){result.dispose();return}loaded=payload;data.value=result;index.value=0;select()}
  catch(e){if(!signal.aborted&&token===generation)error.value=e instanceof Error?e.message:'cloud_preview_invalid'}finally{if(token===generation)loading.value=false}}
watch(()=>[props.payload,props.projectId],()=>void load(),{immediate:true})
watch(index,select)
onBeforeUnmount(release)
</script>
<style scoped>
.edge-panel{display:grid;gap:10px;min-width:0;font-size:12px}.controls,.target{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.controls input{width:90px;min-width:0;color:var(--am-text);background:var(--am-input);border:1px solid var(--am-border);padding:5px;border-radius:4px}.controls button{width:30px;height:30px;display:grid;place-items:center}dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 12px;margin:0}dd{margin:0;overflow-wrap:anywhere}
</style>
