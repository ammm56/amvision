import {createApp,h,ref} from 'vue'
import {createI18n} from 'vue-i18n'
import '../../../frontend/web-ui/src/shared/styles/tokens/brand.css'
import '../../../frontend/web-ui/src/shared/styles/tokens/semantic.css'
import '../../../frontend/web-ui/src/shared/styles/tokens/light.css'
import '../../../frontend/web-ui/src/shared/styles/tokens/dark.css'
import '../../../frontend/web-ui/src/shared/styles/base.css'
import CloudViewer from '../../../frontend/web-ui/src/workflows/workflow-editor/point-cloud/CloudViewer.vue'
import {rendererUsage} from '../../../frontend/web-ui/src/workflows/workflow-editor/point-cloud/preview-data'
import {loadRuntimeConfig} from '../../../frontend/web-ui/src/platform/runtime/runtime-config'
import BoundarySettingsEditor from '../../../custom_nodes/_metrology3d_nodes/frontend/BoundarySettingsEditor.vue'
import DimensionSettingsEditor from '../../../custom_nodes/_metrology3d_nodes/frontend/DimensionSettingsEditor.vue'
import {newDimension} from '../../../custom_nodes/_metrology3d_nodes/frontend/dimension-form'
import {parameterCloudPreviewsKey,parameterPreviewStateKey} from '../../../frontend/web-ui/src/workflows/workflow-editor/parameters/editor-context'

await loadRuntimeConfig()
const query=new URLSearchParams(location.search),candidate=query.get('candidate')??'',context=query.get('context')==='1'
const candidates=await (await fetch('/candidate-index.json')).json() as {name:string;point_count:number;rms_mm:number;max_residual_mm:number}[]
const chosen=candidates.find(row=>row.name===candidate)
const response=await fetch('/real-preview.json'+(candidate?'?candidate='+encodeURIComponent(candidate):''))
if(!response.ok)throw new Error('Candidate preview unavailable')
let payload=await response.json()
if(candidate&&context){
  const full=await (await fetch('/real-preview.json')).json()
  if(full.observation_id!==payload.observation_id)throw new Error('Candidate observation mismatch')
  payload={...full,geometry:payload.geometry}
}
const app=createApp({setup(){
  const visible=ref(true),narrow=ref(false),usage=ref('')
  const curves=payload.geometry?.curves??[],boundary=ref(curves.find((c:{kind:string})=>c.kind==='boundary')?.method.parameters),line=ref(curves.find((c:{kind:string})=>c.kind==='line')?.method.parameters)
  const dimensions=ref({...newDimension('measure-edge-pair'),evaluation:{kind:'feature',frame_id:payload.spatial.frame_id,length_unit:payload.spatial.length_unit},query_position:{kind:'plane-uv',uv:[null,null]},direction:{kind:'axis',axis:null}})
  return()=>h('main',{style:{margin:'16px',width:narrow.value?'390px':'calc(100% - 32px)',fontFamily:'Arial, sans-serif',color:'#16252d','--am-border':'#cbd4da','--am-text':'#16252d','--am-surface':'#fff','--am-surface-soft':'#eef2f4','--am-brand-primary':'#167d85','--am-success-surface':'#d6efea'}},[
    h('header',[h('strong','1-1_0.ply'),h('button',{onClick:()=>narrow.value=!narrow.value},'切换窄屏'),h('button',{onClick:()=>visible.value=!visible.value},visible.value?'关闭显示':'重新打开'),h('button',{onClick:()=>usage.value=JSON.stringify(rendererUsage())},'检查释放'),h('output',usage.value)]),
    ...(candidates.length?[
      h('label',['候选区域 ',h('select',{value:candidate,onChange:(event:Event)=>{location.search=new URLSearchParams({candidate:(event.target as HTMLSelectElement).value,context:context?'1':'0'}).toString()}},[h('option',{value:''},'完整点云'),...candidates.map(row=>h('option',{value:row.name},row.name))])]),
      ...(chosen?[h('button',{onClick:()=>{location.search=new URLSearchParams({candidate,context:context?'0':'1'}).toString()}},context?'局部实测点':'全件位置'),h('p',`候选，未审核；全高 XY 搜索范围，非正式拟面支持。点数 ${chosen.point_count}；SVD RMS ${chosen.rms_mm.toFixed(6)} mm；最大残差 ${chosen.max_residual_mm.toFixed(6)} mm。`)]:[]),
    ]:[]),
    ...(boundary.value?[h(BoundarySettingsEditor,{modelValue:boundary.value,nodeType:'custom.metrology3d.extract-boundary','onUpdate:modelValue':v=>{boundary.value=v}}),h(BoundarySettingsEditor,{modelValue:line.value,nodeType:'custom.metrology3d.fit-line','onUpdate:modelValue':v=>{line.value=v}}),h(DimensionSettingsEditor,{modelValue:dimensions.value,nodeType:'custom.metrology3d.measure-edge-pair','onUpdate:modelValue':v=>{dimensions.value=v as typeof dimensions.value}})]:[]),
    visible.value?h(CloudViewer,{payload,projectId:'test',allowPick:true}):null,
  ])
}})
app.provide(parameterCloudPreviewsKey,()=>[{id:'complete',label:'1-1_0.ply',projectId:'test',payload}])
app.provide(parameterPreviewStateKey,()=>({runId:payload.observation_id,succeeded:true}))
app.use(createI18n({legacy:false,locale:'zh-CN',messages:{'zh-CN':{}}}));app.mount('#app')
