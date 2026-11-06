<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ label('标定栅格','Calibrated raster') }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" class="geometry-dialog" :title="label('标定栅格转点云','Raster to cloud')" size="wide" scroll-body
      :confirm-label="label('应用','Apply')" :cancel-label="label('取消','Cancel')" :confirm-disabled="disabled||!rasterValid(draft)" @confirm="apply" @cancel="open=false">
      <MetrologyWorkspace>
        <template #parameters>
          <label>{{ label('输入来源','Input source') }}<select aria-label="Input source" :value="draft.kind" @change="changeInput"><option value="file">{{ label('文件','File') }}</option><option value="local-array">{{ label('同机标定数组','Same-host calibrated array') }}</option></select></label>
          <dl v-if="draft.kind==='local-array'"><dt>{{ label('标定来源','Calibration source') }}</dt><dd>{{ label('本次载荷','Current payload') }}</dd></dl>
          <template v-else>
            <GeometryFields v-model="draft" :fields="inputFields" />
            <fieldset><legend>{{ label('标定身份与坐标','Calibration and coordinates') }}</legend><GeometryFields v-model="draft" :fields="identityFields" /></fieldset>
            <label>{{ label('投影模型','Projection model') }}<select aria-label="Projection model" :value="projection.kind" @change="changeProjection"><option value="rectified-pinhole">{{ label('已去畸变针孔深度','Rectified pinhole depth') }}</option><option value="orthographic-height">{{ label('正交高度网格','Orthographic height grid') }}</option></select></label>
            <label v-if="projection.kind==='rectified-pinhole'">{{ label('深度定义','Depth definition') }}<select v-model="projection.depth_kind"><option value="axial-z">{{ label('轴向 Z','Axial Z') }}</option><option value="ray-range">{{ label('沿射线距离','Ray range') }}</option></select></label>
            <GeometryFields v-model="draft" :fields="projectionFields" />
            <fieldset><legend>{{ label('尺度与无效值','Scale and invalid values') }}</legend><GeometryFields v-model="draft" :fields="valueFields" />
              <div class="sentinels"><span>{{ label('原始无效值','Raw invalid values') }}</span><button type="button" :title="label('添加无效值','Add invalid value')" :aria-label="label('添加无效值','Add invalid value')" @click="addSentinel"><Plus :size="16" /></button></div>
              <div v-for="(_,i) in sentinels" :key="i" class="sentinel"><input type="number" step="any" :aria-label="`${label('原始无效值','Raw invalid value')} ${i+1}`" :value="sentinels[i]??''" @input="setSentinel(i,$event)"><button type="button" :title="label('删除无效值','Remove invalid value')" :aria-label="label('删除无效值','Remove invalid value')" @click="removeSentinel(i)"><Trash2 :size="16" /></button></div>
            </fieldset>
          </template>
        </template>
        <template #view="{presentation}">
          <section class="raster-view"><CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" />
            <CloudViewer v-if="preview" :key="preview.id" :presentation="presentation" :payload="preview.payload" :project-id="preview.projectId" allow-pick />
          </section>
        </template>
      </MetrologyWorkspace>
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {Plus,Trash2} from '@lucide/vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import GeometryFields from './GeometryFields.vue'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import {copy,object,put,type Form,type Field} from './form'
import {newProjection,newRasterInput,rasterDtypes,rasterValid} from './raster-form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const {locale}=useI18n(),label=(cn:string,en:string)=>locale.value==='zh-CN'?cn:en
const open=ref(false),draft=ref<Form>(newRasterInput()),initial=ref(''),previewId=ref('')
const raster=computed(()=>object(draft.value.raster)),projection=computed(()=>object(raster.value.projection)),validity=computed(()=>object(raster.value.validity))
const sentinels=computed(()=>Array.isArray(validity.value.invalid_raw_values)?validity.value.invalid_raw_values:[])
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value)),changed=computed(()=>JSON.stringify(draft.value)!==initial.value)
const field=(path:string,cn:string,en:string,type?:Field['type'],options?:string[]):Field=>({path,label:label(cn,en),type,options})
const inputFields=computed(()=>[field('file_format','文件格式','File format','select',['npy','png','tiff']),field('raster.width','列数','Columns','number'),field('raster.height','行数','Rows','number'),field('raster.dtype','原始类型','Raw type','select',rasterDtypes),field('raster.position_dtype','坐标存储类型','Position type','select',['float32','float64'])])
const identityFields=computed(()=>[field('raster.calibration_id','标定 ID','Calibration ID'),field('raster.calibration_revision','标定修订','Calibration revision'),field('raster.spatial.frame_id','输出坐标系','Output frame'),field('raster.spatial.length_unit','长度单位','Length unit','select',['m','mm','um'])])
const projectionFields=computed(()=>projection.value.kind==='rectified-pinhole'?['fx','fy','cx','cy'].map(n=>field(`raster.projection.${n}`,`${n}（像素）`,`${n} (pixels)`,'number')):[field('raster.projection.origin','零行零列零高原点','Zero-height origin at row/column zero','vector'),field('raster.projection.column_direction','列单位方向','Column unit direction','vector'),field('raster.projection.row_direction','行单位方向','Row unit direction','vector'),field('raster.projection.height_direction','高度单位方向','Height unit direction','vector'),field('raster.projection.column_step','列步距','Column spacing','number'),field('raster.projection.row_step','行步距','Row spacing','number')])
const valueFields=computed(()=>[field('raster.value_scale','原值乘数','Raw multiplier','number'),field('raster.value_offset','物理偏移','Physical offset','number'),field('raster.validity.minimum','物理下限（空为不限）','Physical minimum (empty: unbounded)','number'),field('raster.validity.maximum','物理上限（空为不限）','Physical maximum (empty: unbounded)','number')])
function show(){draft.value=props.modelValue&&typeof props.modelValue==='object'?copy(object(props.modelValue)):newRasterInput();initial.value=JSON.stringify(draft.value);previewId.value='';open.value=true}
function changeInput(e:Event){draft.value=newRasterInput((e.target as HTMLSelectElement).value)}
function changeProjection(e:Event){draft.value=put(draft.value,'raster.projection',newProjection((e.target as HTMLSelectElement).value))}
function setSentinel(i:number,e:Event){const values=[...sentinels.value],input=e.target as HTMLInputElement;values[i]=input.validity.badInput?NaN:input.value===''?null:Number(input.value);draft.value=put(draft.value,'raster.validity.invalid_raw_values',values)}
function addSentinel(){draft.value=put(draft.value,'raster.validity.invalid_raw_values',[...sentinels.value,null])}
function removeSentinel(i:number){draft.value=put(draft.value,'raster.validity.invalid_raw_values',sentinels.value.filter((_,j)=>i!==j))}
function apply(){if(!props.disabled&&rasterValid(draft.value)){emit('update:modelValue',copy(draft.value));open.value=false}}
watch([()=>props.modelValue,()=>props.nodeType,()=>props.disabled,()=>JSON.stringify(props.inputSources)],()=>{open.value=false;previewId.value=''})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
label{display:grid;gap:6px;margin:10px 0;min-width:0}select,input{width:100%;min-width:0;background:var(--am-input);color:var(--am-text);border:1px solid var(--am-border);border-radius:4px;padding:6px}fieldset{margin:12px 0;padding:10px;border:1px solid var(--am-border);min-width:0}legend{font-size:13px}.raster-view{display:grid;gap:10px;min-width:0}.sentinels,.sentinel{display:flex;align-items:center;gap:8px;margin-top:8px}.sentinels{justify-content:space-between}.sentinel button,.sentinels button{display:grid;place-items:center;flex:none;width:30px;height:30px}.geometry-dialog :deep(.confirm-dialog){width:min(1240px,calc(100vw - 36px))}
</style>
