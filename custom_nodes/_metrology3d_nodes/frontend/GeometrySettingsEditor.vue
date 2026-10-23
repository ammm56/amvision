<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ plane?(zh?'平面拟合':'Plane fit'):(zh?'建立坐标系':'Build frame') }} · {{ String(object(modelValue)[plane?'feature_id':'pose_id']||'-') }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" :title="plane?(zh?'平面拟合':'Plane fit'):(zh?'建立坐标系':'Build frame')" size="wide" scroll-body confirm-variant="primary" :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" :confirm-disabled="!!issues.length||disabled" @confirm="apply" @cancel="open=false">
    <div class="geometry-workspace">
      <div class="geometry-toolbar">
        <label v-if="plane">{{ zh?'算法':'Algorithm' }}<select :value="object(draft.algorithm).kind" @change="algorithm(($event.target as HTMLSelectElement).value)"><option value="svd">SVD</option><option value="ransac-svd">RANSAC + SVD</option></select></label>
        <template v-else>
          <label>{{ zh?'原点':'Origin' }}<select :value="object(draft.origin).kind" @change="origin(($event.target as HTMLSelectElement).value)"><option value="anchor-projection">{{ zh?'锚点投影':'Anchor projection' }}</option><option value="three-planes">{{ zh?'三面交点':'Three-plane intersection' }}</option></select></label>
          <label>{{ zh?'X 轴':'X axis' }}<select :value="object(draft.x_axis).kind" :disabled="object(draft.origin).kind==='three-planes'" @change="axis(($event.target as HTMLSelectElement).value)"><option value="direction">{{ zh?'显式方向':'Explicit direction' }}</option><option value="plane-intersection">{{ zh?'主次面交线':'Datum intersection' }}</option></select></label>
        </template>
      </div>
      <GeometryFields v-model="draft" :fields="fields" :suggestions="suggestions" />
      <GeometryFields v-model="draft" :fields="[{path:'quality_policy.policy_id',label:zh?'质量策略 ID':'Quality policy ID'},{path:'quality_policy.policy_version',label:zh?'质量策略版本':'Quality policy version',type:'number'}]" />
      <WorkflowLimitRulesEditor :model-value="object(draft.quality_policy).rules" quality @update:model-value="draft=put(draft,'quality_policy.rules',$event)" />
      <p v-if="issues.length" role="alert">{{ zh?'待完善':'Incomplete' }}: {{ issues.join(' · ') }}</p>
      <p v-if="referenceIssues.length" role="status">{{ referenceIssues.join(' · ') }}</p>
    </div>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import WorkflowLimitRulesEditor from '@/workflows/workflow-editor/components/WorkflowLimitRulesEditor.vue'
import type {ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import {normalizeLimitRule} from '@/workflows/workflow-editor/parameters/limit-rules'
import GeometryFields from './GeometryFields.vue'
import {object,copy,newSettings,geometryIssues,put,type Form,type Field} from './form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources;draftIssues?:(value:unknown)=>string[]}>(),emit=defineEmits<{'update:modelValue':[value:Form]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),plane=computed(()=>props.nodeType.endsWith('fit-plane'))
const open=ref(false),draft=ref<Form>({})
const suggestions=computed(()=>{const ids=(props.inputSources?.features??[]).filter(s=>s.nodeTypeId==='custom.metrology3d.fit-plane').map(s=>object(s.parameters.settings).feature_id).filter((v):v is string=>typeof v==='string');return {'primary_feature_id':ids,'x_axis.secondary_feature_id':ids,'origin.tertiary_feature_id':ids}})
const issues=computed(()=>geometryIssues(plane.value?'fit-plane':'build-frame',draft.value))
const referenceIssues=computed(()=>open.value?props.draftIssues?.(draft.value)??[]:[])
const fields=computed<Field[]>(()=>{
  const label=(cn:string,en:string)=>zh.value?cn:en,vector=(path:string,cn:string,en:string):Field=>({path,label:label(cn,en),type:'vector'})
  if(plane.value)return [
    {path:'feature_id',label:label('特征 ID','Feature ID')},vector('positive_normal','正法向（单位向量）','Positive unit normal'),{path:'min_orientation_cosine',label:label('最小定向余弦','Minimum orientation cosine'),type:'number'},
    ...(object(draft.value.algorithm).kind==='ransac-svd'?[{path:'algorithm.distance_threshold',label:label('内点距离阈值（点云单位）','Inlier distance (cloud unit)'),type:'number'},{path:'algorithm.sample_size',label:label('采样点数','Sample count'),type:'number'},{path:'algorithm.iterations',label:label('迭代次数','Iterations'),type:'number'},{path:'algorithm.probability',label:label('成功概率','Probability'),type:'number'}] as Field[]:[]),
  ]
  return [
    {path:'pose_id',label:label('位姿 ID','Pose ID')},{path:'target_frame_id',label:label('目标坐标系 ID','Target frame ID')},{path:'primary_feature_id',label:label('主基准特征 ID','Primary datum ID')},vector('positive_z','Z 正方向（单位向量）','Positive unit Z'),
    ...(object(draft.value.origin).kind==='anchor-projection'?[vector('origin.anchor','源坐标锚点 XYZ','Source anchor XYZ')]:[{path:'origin.tertiary_feature_id',label:label('第三基准特征 ID','Tertiary datum ID')}]),
    ...(object(draft.value.x_axis).kind==='direction'?[vector('x_axis.direction','X 正方向（单位向量）','Positive unit X')]:[{path:'x_axis.secondary_feature_id',label:label('次基准特征 ID','Secondary datum ID')},vector('x_axis.positive_direction','交线正方向（单位向量）','Positive unit intersection direction')]),
  ]
})
function show(){draft.value=Object.keys(object(props.modelValue)).length?copy(object(props.modelValue)):newSettings(plane.value);open.value=true}
function algorithm(kind:string){draft.value={...draft.value,algorithm:kind==='svd'?{kind}:{kind,distance_threshold:null,sample_size:null,iterations:null,probability:null}}}
function axis(kind:string){draft.value={...draft.value,x_axis:kind==='direction'?{kind,direction:[null,null,null]}:{kind,secondary_feature_id:'',positive_direction:[null,null,null]}}}
function origin(kind:string){draft.value={...draft.value,origin:kind==='anchor-projection'?{kind,anchor:[null,null,null]}:{kind,tertiary_feature_id:''}};const q=object(draft.value.quality_policy),rules=(Array.isArray(q.rules)?q.rules:[]).map(normalizeLimitRule).filter(r=>r.item_id!=='origin_condition');if(kind==='three-planes'){if(object(draft.value.x_axis).kind!=='plane-intersection')axis('plane-intersection');rules.push(normalizeLimitRule({item_id:'origin_condition',unit:'1'}))}draft.value=put(draft.value,'quality_policy.rules',rules)}
function apply(){if(!issues.value.length&&!props.disabled){emit('update:modelValue',copy(draft.value));open.value=false}}
watch(()=>[props.modelValue,props.disabled,props.nodeType],()=>{open.value=false})
</script>
<style src="./editor.css" scoped></style>
