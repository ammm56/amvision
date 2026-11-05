<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ zh?'法向估计':'Estimate normals' }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" class="geometry-dialog" :title="zh?'法向估计':'Estimate normals'" size="wide" scroll-body
      :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" :confirm-disabled="disabled||!normalsValid(draft)" @confirm="apply" @cancel="open=false">
      <MetrologyWorkspace>
        <template #parameters>
          <label>{{ zh?'邻域':'Neighborhood' }}<select :value="neighborhood.kind" @change="changeNeighborhood">
            <option value="knn">{{ zh?'最近 K 点':'K nearest' }}</option><option value="radius">{{ zh?'半径内全部点':'All within radius' }}</option><option value="hybrid">{{ zh?'半径与数量上限':'Radius with count limit' }}</option>
          </select></label>
          <label v-if="neighborhood.kind==='knn'">{{ zh?'距离约束':'Distance constraint' }}<select :value="support.kind" @change="changeSupport"><option value="unrestricted">{{ zh?'不截断距离':'Unrestricted' }}</option><option value="bounded">{{ zh?'有限距离':'Bounded' }}</option></select></label>
          <GeometryFields v-model="draft" :fields="neighborFields" />
          <fieldset><legend>{{ zh?'质量条件':'Quality' }}</legend><GeometryFields v-model="draft" :fields="qualityFields" /></fieldset>
          <label>{{ zh?'定向':'Orientation' }}<select :value="orientation.kind" @change="changeOrientation"><option value="unoriented">{{ zh?'无符号法向轴':'Unsigned axis' }}</option><option value="direction">{{ zh?'参考方向':'Reference direction' }}</option><option value="viewpoint">{{ zh?'观测点':'Viewpoint' }}</option></select></label>
          <GeometryFields v-model="draft" :fields="orientationFields" />
          <label v-if="orientation.kind==='viewpoint'">{{ zh?'朝向':'Facing' }}<select v-model="orientation.facing"><option value="toward">{{ zh?'朝向观测点':'Toward viewpoint' }}</option><option value="away">{{ zh?'远离观测点':'Away from viewpoint' }}</option></select></label>
          <GeometryFields v-model="draft" :fields="spatialFields" />
          <label>{{ zh?'已有法向':'Existing normals' }}<select v-model="draft.existing_normals"><option value="reject">{{ zh?'拒绝覆盖':'Reject replacement' }}</option><option value="replace">{{ zh?'明确替换':'Replace explicitly' }}</option></select></label>
          <label class="check"><input v-model="draft.diagnostics" type="checkbox">{{ zh?'保留逐点诊断':'Keep per-point diagnostics' }}</label>
        </template>
        <template #view="{presentation}">
          <section class="normal-view"><CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" />
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
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import GeometryFields from './GeometryFields.vue'
import {copy,type Form,type Field} from './form'
import {newNormals,newNeighborhood,newOrientation,normalsValid,normalsRecord} from './normals-form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),label=(cn:string,en:string)=>zh.value?cn:en
const open=ref(false),draft=ref<Form>(newNormals()),initial=ref(''),previewId=ref('')
const neighborhood=computed(()=>normalsRecord(draft.value.neighborhood)),support=computed(()=>normalsRecord(neighborhood.value.support)),orientation=computed(()=>normalsRecord(draft.value.orientation))
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value)),changed=computed(()=>JSON.stringify(draft.value)!==initial.value)
const number=(path:string,cn:string,en:string,unit?:string):Field=>({path,type:'number',label:label(cn,en),unit})
const unit=computed(()=>String(draft.value.length_unit||''))
const neighborFields=computed<Field[]>(()=>neighborhood.value.kind==='knn'?[number('neighborhood.neighbors','其他邻居数 K','Other neighbors K'),...(support.value.kind==='bounded'?[number('neighborhood.support.max_distance','最大支持距离','Maximum support distance',unit.value)]:[])]:[number('neighborhood.radius','邻域半径','Neighborhood radius',unit.value),...(neighborhood.value.kind==='hybrid'?[number('neighborhood.max_neighbors','最多其他邻居数','Maximum other neighbors')]:[])])
const qualityFields=computed(()=>[number('quality.min_support_points','最少支持点数（含自身）','Minimum support (including self)'),number('quality.min_normal_gap','最小法向特征间隙','Minimum normal gap'),number('quality.max_rms','最大 RMS','Maximum RMS',unit.value),number('quality.max_surface_variation','最大表面变化率','Maximum surface variation')])
const orientationFields=computed<Field[]>(()=>orientation.value.kind==='unoriented'?[]:[{path:orientation.value.kind==='direction'?'orientation.direction':'orientation.position',type:'vector',label:label(orientation.value.kind==='direction'?'参考方向':'观测点',orientation.value.kind==='direction'?'Reference direction':'Viewpoint'),unit:orientation.value.kind==='viewpoint'?unit.value:undefined},number('orientation.min_abs_cosine','最小绝对余弦','Minimum absolute cosine')])
const spatialFields=computed<Field[]>(()=>[{path:'frame_id',label:label('坐标系','Coordinate frame')},{path:'length_unit',type:'select',options:['m','mm','um'],label:label('长度单位','Length unit')}])
function show(){draft.value=props.modelValue&&typeof props.modelValue==='object'?{...newNormals(),...copy(props.modelValue) as Form}:newNormals();initial.value=JSON.stringify(draft.value);previewId.value='';open.value=true}
function changeNeighborhood(e:Event){draft.value={...draft.value,neighborhood:newNeighborhood((e.target as HTMLSelectElement).value)}}
function changeSupport(e:Event){const kind=(e.target as HTMLSelectElement).value;draft.value={...draft.value,neighborhood:{...neighborhood.value,support:{kind,...(kind==='bounded'?{max_distance:null}:{})}}}}
function changeOrientation(e:Event){draft.value={...draft.value,orientation:newOrientation((e.target as HTMLSelectElement).value)}}
function apply(){if(!props.disabled&&normalsValid(draft.value)){emit('update:modelValue',copy(draft.value));open.value=false}}
watch([()=>props.modelValue,()=>props.nodeType,()=>props.disabled,()=>JSON.stringify(props.inputSources)],()=>{open.value=false;previewId.value=''})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
label{display:grid;gap:6px;margin:10px 0;min-width:0}select{width:100%;min-width:0}fieldset{margin:12px 0;padding:10px;border:1px solid var(--am-border);min-width:0}legend{font-size:13px}.check{display:flex;align-items:center}.normal-view{display:grid;gap:10px;min-width:0}.geometry-dialog :deep(.confirm-dialog){width:min(1240px,calc(100vw - 36px))}
</style>
