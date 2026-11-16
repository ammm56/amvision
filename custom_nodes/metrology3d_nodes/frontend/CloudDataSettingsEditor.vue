<template>
  <button type="button" class="geometry-open" :disabled="disabled" @click="show">{{ title }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" :title="title" size="wide" scroll-body confirm-variant="primary" :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" :confirm-disabled="!!issues.length||disabled" @confirm="apply" @cancel="open=false">
    <section class="data-fields">
      <template v-if="parameterName==='finite_fields'">
        <div v-for="(field,i) in fields" :key="i" class="data-row"><label>{{ zh?'字段':'Field' }} {{ i+1 }}<input :value="field" :disabled="field==='positions'" :list="listId" @input="replaceField(i,($event.target as HTMLInputElement).value)"></label><button :disabled="field==='positions'" :title="zh?'移除字段':'Remove field'" :aria-label="zh?'移除字段':'Remove field'" @click="draft=fields.filter((_,index)=>index!==i)"><Trash2 :size="16" /></button></div>
        <button :title="zh?'添加字段':'Add field'" :aria-label="zh?'添加字段':'Add field'" @click="draft=[...fields,'']"><Plus :size="16" /></button>
      </template>
      <template v-else-if="parameterName==='sentinels'">
        <fieldset v-for="(row,i) in rows" :key="i"><legend>{{ zh?'无效值规则':'Invalid-value rule' }} {{ i+1 }}</legend><div class="data-row"><label>{{ zh?'字段':'Field' }}<input :value="row.field" :list="listId" @input="updateRow(i,{...row,field:($event.target as HTMLInputElement).value})"></label><label>{{ zh?'匹配方式':'Match' }}<select :value="row.match" @change="updateRow(i,{...row,match:($event.target as HTMLSelectElement).value})"><option value="all">{{ zh?'所有分量相同':'All components' }}</option><option value="any">{{ zh?'任一分量相同':'Any component' }}</option></select></label><button :title="zh?'删除规则':'Remove rule'" :aria-label="zh?'删除规则':'Remove rule'" @click="draft=rows.filter((_,index)=>index!==i)"><Trash2 :size="16" /></button></div>
          <div class="data-row"><label v-for="(value,j) in values(row)" :key="j">{{ zh?'分量':'Component' }} {{ j+1 }}<input :value="value??''" inputmode="decimal" @input="setSentinel(i,j,($event.target as HTMLInputElement).value)"></label><button :disabled="values(row).length>=3" :title="zh?'添加分量':'Add component'" :aria-label="zh?'添加分量':'Add component'" @click="updateRow(i,{...row,values:[...values(row),null]})"><Plus :size="16" /></button><button :disabled="values(row).length<=1" :title="zh?'移除分量':'Remove component'" :aria-label="zh?'移除分量':'Remove component'" @click="updateRow(i,{...row,values:values(row).slice(0,-1)})"><Trash2 :size="16" /></button></div>
        </fieldset>
        <button :title="zh?'添加规则':'Add rule'" :aria-label="zh?'添加规则':'Add rule'" @click="draft=[...rows,{field:'',match:'all',values:[null]}]"><Plus :size="16" /></button>
      </template>
      <template v-else>
        <label>{{ zh?'着色方式':'Color mode' }}<select :value="color.mode" @change="changeColor(($event.target as HTMLSelectElement).value)"><option value="" disabled>{{ zh?'请选择':'Select' }}</option><option value="solid">{{ zh?'统一颜色':'Solid' }}</option><option value="rgb">{{ zh?'原始 RGB':'Original RGB' }}</option><option value="scalar">{{ zh?'字段色标':'Scalar field' }}</option></select></label>
        <template v-if="color.mode==='scalar'"><label>{{ zh?'字段':'Field' }}<input :value="color.field" :list="listId" @input="draft={...color,field:($event.target as HTMLInputElement).value}"></label><label>{{ zh?'分量索引（从 0 开始）':'Component index (from 0)' }}<input type="number" min="0" step="1" :value="color.component" @input="draft={...color,component:($event.target as HTMLInputElement).valueAsNumber}"></label><label>{{ zh?'色标范围':'Color range' }}<select :value="object(color.range).mode" @change="draft={...color,range:($event.target as HTMLSelectElement).value==='fixed'?{mode:'fixed',min:'',max:''}:{mode:'finite-range'}}"><option value="finite-range">{{ zh?'显示样本有限值范围':'Finite displayed range' }}</option><option value="fixed">{{ zh?'固定范围':'Fixed range' }}</option></select></label><div v-if="object(color.range).mode==='fixed'" class="data-row"><label v-for="bound in ['min','max']" :key="bound">{{ bound==='min'?(zh?'最小值':'Minimum'):(zh?'最大值':'Maximum') }}<input inputmode="decimal" :value="object(color.range)[bound]" @input="draft={...color,range:{...object(color.range),[bound]:($event.target as HTMLInputElement).value}}"></label></div></template>
      </template>
      <datalist :id="listId"><option v-for="name in suggestions" :key="name" :value="name" /></datalist>
      <p v-if="issues.length" role="alert">{{ zh?'配置不完整或无效，请检查字段、数值和范围。':'Incomplete or invalid fields, values or range.' }}</p>
    </section>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,ref,watch,useId} from 'vue'
import {useI18n} from 'vue-i18n'
import {Plus,Trash2} from '@lucide/vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {parameterSourceSignature,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import {object,copy,type Form} from './form'
import {cloudDataIssues,sentinelValue} from './cloud-data-form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;parameterName:string;disabled?:boolean;inputSources?:ParameterEditorSources}>(),emit=defineEmits<{'update:modelValue':[value:unknown]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),listId=useId(),open=ref(false),draft=ref<unknown>(null)
const title=computed(()=>props.parameterName==='finite_fields'?(zh.value?'有限值检查字段':'Finite-value fields'):props.parameterName==='sentinels'?(zh.value?'无效值规则':'Invalid-value rules'):(zh.value?'点云着色':'Point cloud color'))
const fields=computed(()=>Array.isArray(draft.value)?draft.value as string[]:[]),rows=computed(()=>Array.isArray(draft.value)?draft.value.map(object):[]),color=computed(()=>object(draft.value))
const suggestions=computed(()=>[...new Set((props.inputSources?.cloud??[]).flatMap(s=>{const output=object(s.previewOutput);return Array.isArray(output.fields)?output.fields.map(f=>String(object(f).name)):[]}))])
const issues=computed(()=>cloudDataIssues(props.parameterName,draft.value))
function show(){if(props.disabled)return;draft.value=props.modelValue===undefined?(props.parameterName==='color'?{mode:''}:[]):copy(props.modelValue);open.value=true}
function apply(){if(!issues.value.length&&!props.disabled){emit('update:modelValue',copy(draft.value));open.value=false}}
function values(row:Form):unknown[]{return Array.isArray(row.values)?row.values:[]}
function replaceField(i:number,value:string){draft.value=fields.value.map((v,index)=>index===i?value:v)}
function updateRow(i:number,value:Form){draft.value=rows.value.map((v,index)=>index===i?value:v)}
function setSentinel(i:number,j:number,text:string){const row=rows.value[i]!;updateRow(i,{...row,values:values(row).map((v,index)=>index===j?(sentinelValue(text)??text):v)})}
function changeColor(mode:string){draft.value=mode==='scalar'?{mode,field:'',component:null,range:{mode:'finite-range'}}:{mode}}
watch(()=>props.modelValue,()=>{open.value=false},{deep:true})
watch([()=>props.disabled,()=>props.parameterName,()=>parameterSourceSignature(props.inputSources)],()=>{open.value=false})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
.data-fields{display:grid;gap:12px}.data-row{display:flex;align-items:end;gap:8px;flex-wrap:wrap}label{display:grid;gap:5px;min-width:120px;flex:1}input,select{width:100%;min-width:0;padding:6px;border:1px solid var(--am-border);background:var(--am-input);color:var(--am-text);border-radius:4px}fieldset{border:1px solid var(--am-border);display:grid;gap:10px}button{color:var(--am-text);background:var(--am-input);border:1px solid var(--am-border);padding:6px;border-radius:4px}p[role=alert]{color:var(--am-danger-text)}
</style>
