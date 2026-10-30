<template>
  <div class="geometry-fields">
    <label v-for="field in fields" :key="field.path"><span>{{ field.label }}<template v-if="field.unit"> ({{ field.unit }})</template></span>
      <select v-if="field.type==='select'" :aria-label="field.label" :value="get(modelValue,field.path)??''" @change="set(field.path,($event.target as HTMLSelectElement).value)"><option value="" disabled></option><option v-for="option in field.options" :key="option" :value="option">{{ option }}</option></select>
      <component :is="field.type==='matrix'?'details':'div'" v-else-if="field.type==='vector'||field.type==='matrix'||field.type==='pair'" :class="field.type==='matrix'?'matrix':'vector'" >
        <summary v-if="field.type==='matrix'">3 × 3</summary><div class="vector" :class="{pair:field.type==='pair'}">
        <span v-for="i in field.type==='matrix'?9:field.type==='pair'?2:3" :key="i" class="cell"><small>{{ component(field,i-1) }}</small><input type="number" step="any" :aria-label="`${field.label} ${i}`" :title="`${field.label} ${component(field,i-1)}${field.unit?' ('+field.unit+')':''}`" :value="cell(field,i-1)" @input="setCell(field,i-1,$event)"></span>
        </div>
      </component>
      <input v-else :type="field.type==='number'?'number':'text'" step="any" :aria-label="field.label" :value="get(modelValue,field.path)??''" :list="suggestions?.[field.path]?.length?`${uid}-${field.path}`:undefined" @input="set(field.path,field.type==='number'?number($event):($event.target as HTMLInputElement).value)">
      <datalist v-if="suggestions?.[field.path]?.length" :id="`${uid}-${field.path}`"><option v-for="id in suggestions[field.path]" :key="id" :value="id" /></datalist>
    </label>
  </div>
</template>
<script setup lang="ts">
import { useId } from 'vue'
import { get,put,type Field,type Form } from './form'
const props=defineProps<{modelValue:Form;fields:Field[];suggestions?:Record<string,string[]>}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>(),uid=useId()
function number(e:Event){const i=e.target as HTMLInputElement;return i.validity.badInput?NaN:i.value===''?null:Number(i.value)}
function component(field:Field,i:number){return field.components?.[i]??(field.type==='matrix'?`${Math.floor(i/3)+1},${i%3+1}`:field.type==='vector'?['X','Y','Z'][i]:String(i+1))}
function set(path:string,value:unknown){emit('update:modelValue',put(props.modelValue,path,value))}
function cell(field:Field,i:number){const v=get(props.modelValue,field.path);return Array.isArray(v)?(field.type==='matrix'?(v[Math.floor(i/3)] as unknown[]|undefined)?.[i%3]:v[i])??'':''}
function setCell(field:Field,i:number,e:Event){const values=Array.from({length:field.type==='matrix'?9:field.type==='pair'?2:3},(_,j)=>cell(field,j)===''?null:cell(field,j));values[i]=number(e);set(field.path,field.type==='matrix'?[values.slice(0,3),values.slice(3,6),values.slice(6,9)]:values)}
</script>
<style scoped>
.geometry-fields { display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px; }
label { display:grid;gap:4px;font-size:12px;min-width:0;align-content:start; }
input,select { width:100%;min-width:0;padding:6px;border:1px solid var(--am-border);border-radius:4px;background:var(--am-input);color:var(--am-text);font:inherit; }
.vector {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px}
.pair {grid-template-columns:repeat(2,minmax(0,1fr))}
.vector>.vector{grid-column:1/-1}.matrix summary{cursor:pointer;padding:5px 0}
.cell{display:grid;gap:3px;min-width:0}.cell small{color:var(--am-text-muted);font-size:11px}
</style>
