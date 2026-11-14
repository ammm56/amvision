<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ zh?'拟面支持范围':'Plane fitting support' }} · {{ object(modelValue).kind==='parameters'?String(object(object(modelValue).roi).roi_id||'-'):(zh?'完整输入点云':'Entire input cloud') }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" :title="zh?'拟面支持范围':'Plane fitting support'" :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" confirm-variant="primary" :confirm-disabled="disabled||issues.length>0" @confirm="apply" @cancel="open=false">
    <div class="plane-support"><label>{{ zh?'范围来源':'Support source' }}
      <select :value="draft.kind" :disabled="disabled" @change="changeMode">
        <option value="cloud">{{ zh?'完整输入点云':'Entire input cloud' }}</option>
        <option value="parameters">{{ zh?'显式 ROI':'Explicit ROI' }}</option>
      </select>
    </label>
    <RoiEditor v-if="draft.kind==='parameters'" :model-value="draft" :disabled="disabled" :allow-input="false" :draft-issues="draftIssues" @update:model-value="draft=$event" />
    <p v-if="issues.length" role="alert">{{ zh?'ROI 待完善':'ROI incomplete' }}</p></div>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import type {ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import RoiEditor from './RoiEditor.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {copy,object,newRoi,planeSupportIssues,type Form} from './form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;disabled?:boolean;inputSources?:ParameterEditorSources;draftIssues?:(value:unknown)=>string[]}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const open=ref(false)
const emptyRoi=()=>({kind:'parameters',roi:newRoi(),bounds:[]})
const draft=ref<Form>({kind:'cloud'})
const issues=computed(()=>planeSupportIssues(draft.value))
function changeMode(event:Event){
  if(props.disabled)return
  draft.value=(event.target as HTMLSelectElement).value==='cloud'?{kind:'cloud'}:emptyRoi()
}
function show(){if(props.disabled)return;draft.value=props.modelValue===undefined?{kind:'cloud'}:copy(object(props.modelValue));open.value=true}
function apply(){if(!props.disabled&&!issues.value.length){emit('update:modelValue',copy(draft.value));open.value=false}}
watch([()=>props.modelValue,()=>props.disabled,()=>JSON.stringify(props.inputSources)],()=>{open.value=false},{deep:true})
</script>
<style src="./editor.css" scoped></style>
<style scoped>.plane-support{display:grid;gap:8px;min-width:0}</style>
