<template>
  <section class="reference-rows">
    <fieldset v-for="(row,index) in rows" :key="index">
      <legend>{{ zh?'量项':'Measurement' }} {{ index+1 }}</legend>
      <GeometryFields :model-value="row" :fields="fields" :suggestions="suggestions" @update:model-value="update(index,$event)" />
      <label>{{ zh?'基准支持':'Datum support' }}<select :value="object(row.reference_policy).kind" @change="reference(index,($event.target as HTMLSelectElement).value)"><option value="measured-support">{{ zh?'基准处需实测支持':'Measured support required' }}</option><option value="plane-extension">{{ zh?'基准平面有限延伸':'Bounded datum plane extension' }}</option></select></label>
      <GeometryFields v-if="object(row.reference_policy).kind==='plane-extension'" :model-value="row" :fields="extension" @update:model-value="update(index,$event)" />
      <GeometryFields :model-value="row" :fields="quality" @update:model-value="update(index,$event)" />
      <WorkflowLimitRulesEditor :model-value="object(row.quality_policy).rules" :available-items="measurementQualityItems(false,unit,zh)" quality @update:model-value="update(index,put(row,'quality_policy.rules',$event))" />
      <button type="button" :title="zh?'删除量项':'Remove measurement'" :aria-label="zh?'删除量项':'Remove measurement'" @click="remove(index)"><Trash2 :size="16" /></button>
    </fieldset>
    <button type="button" :title="zh?'添加量项':'Add measurement'" :aria-label="zh?'添加量项':'Add measurement'" @click="emit('update:modelValue',[...rows,newReferenceMeasurement()])"><Plus :size="16" /></button>
  </section>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import {Plus,Trash2} from '@lucide/vue'
import GeometryFields from './GeometryFields.vue'
import WorkflowLimitRulesEditor from '@/workflows/workflow-editor/components/WorkflowLimitRulesEditor.vue'
import {object,put,type Form,type Field} from './form'
import {newReferenceMeasurement} from './measurement-form'
import {measurementQualityItems} from './quality-items'
const props=defineProps<{modelValue:unknown;unit:string;suggestions:Record<string,string[]>}>()
const emit=defineEmits<{'update:modelValue':[value:Form[]]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const rows=computed(()=>Array.isArray(props.modelValue)?props.modelValue.map(object):[])
const label=(cn:string,en:string)=>zh.value?cn:en
const fields=computed<Field[]>(()=>[{path:'item_id',label:label('测量项 ID','Measurement ID')},{path:'reference_feature_id',label:label('基准平面 ID','Reference plane ID')},{path:'support_radius',type:'number',unit:props.unit,label:label('支持搜索半径','Support radius')}])
const extension=computed<Field[]>(()=>[{path:'reference_policy.max_extension_distance',type:'number',unit:props.unit,label:label('最大基准延伸距离','Maximum datum extension')}])
const quality=computed<Field[]>(()=>[{path:'quality_policy.policy_id',label:label('质量策略 ID','Quality policy ID')},{path:'quality_policy.policy_version',type:'number',label:label('策略版本','Policy version')}])
function update(index:number,value:Form){emit('update:modelValue',rows.value.map((row,i)=>i===index?value:row))}
function remove(index:number){emit('update:modelValue',rows.value.filter((_,i)=>i!==index))}
function reference(index:number,kind:string){update(index,{...rows.value[index],reference_policy:kind==='plane-extension'?{kind,max_extension_distance:null}:{kind:'measured-support'}})}
</script>
<style src="./editor.css" scoped></style>
<style scoped>
.reference-rows{display:grid;gap:12px;min-width:0}
.reference-rows fieldset{display:grid;gap:8px;min-width:0;margin:0;padding:8px;border:1px solid var(--am-border);border-radius:4px}
.reference-rows legend{padding:0 4px;font-size:12px;font-weight:600;color:var(--am-text)}
.reference-rows button{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border:1px solid var(--am-border);border-radius:4px;background:var(--am-surface);color:var(--am-text);cursor:pointer}
</style>
