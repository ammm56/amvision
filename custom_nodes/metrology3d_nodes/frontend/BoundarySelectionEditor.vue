<template>
  <fieldset class="boundary-selection">
    <legend>{{ zh?'支持选择':'Support selection' }}</legend>
    <label>{{ zh?'选择方式':'Selection mode' }}<select :value="mode" @change="setMode(($event.target as HTMLSelectElement).value)"><option value="segment_ids">{{ zh?'明确段':'Explicit segments' }}</option><option v-if="!segmentsOnly" value="group_ids">{{ zh?'目标片段组':'Target fragment groups' }}</option></select></label>
    <label v-for="id in choices" :key="id"><input type="checkbox" :checked="selected.includes(id)" @change="toggle(id,($event.target as HTMLInputElement).checked)">{{ id }}</label>
    <template v-if="!choices.length"><div v-for="(id,index) in selected" :key="index" class="row"><input :aria-label="zh?'支持 ID':'Support ID'" :value="id" @input="setId(index,($event.target as HTMLInputElement).value)"><button type="button" :title="zh?'删除':'Remove'" @click="publish(selected.filter((_,i)=>i!==index))"><Trash2 :size="16" /></button></div><button type="button" :title="zh?'添加支持':'Add support'" @click="publish([...selected,''])"><Plus :size="16" /></button></template>
  </fieldset>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import {Plus,Trash2} from '@lucide/vue'
import {object,type Form} from './form'
const props=defineProps<{modelValue:unknown;segments:string[];groups?:string[];segmentsOnly?:boolean}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const mode=computed(()=>{const p=object(props.modelValue);return Array.isArray(p.group_ids)&&p.group_ids.length?'group_ids':('group_ids' in p&&!('segment_ids' in p)?'group_ids':'segment_ids')})
const selected=computed(()=>(Array.isArray(object(props.modelValue)[mode.value])?object(props.modelValue)[mode.value]:[]) as string[])
const choices=computed(()=>mode.value==='group_ids'?props.groups??[]:props.segments)
function publish(ids:string[]){emit('update:modelValue',{feature_id:object(props.modelValue).feature_id,[mode.value]:ids})}
function setMode(key:string){emit('update:modelValue',{feature_id:object(props.modelValue).feature_id,[key]:[]})}
function toggle(id:string,on:boolean){publish(on?[...selected.value,id]:selected.value.filter(v=>v!==id))}
function setId(index:number,id:string){const next=[...selected.value];next[index]=id;publish(next)}
</script>
<style scoped>
.boundary-selection{display:grid;gap:8px;border:1px solid var(--am-border);padding:10px;min-width:0}.boundary-selection label{display:flex;align-items:center;gap:8px}.boundary-selection input[type=checkbox]{width:16px;flex:none}.row{display:grid;grid-template-columns:minmax(0,1fr) 30px;gap:6px}.boundary-selection button{width:30px;height:30px;display:grid;place-items:center}.boundary-selection select{min-width:0;flex:1}
</style>
