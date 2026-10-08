<template>
  <button type="button" class="limits-summary" :disabled="disabled" @click="show">{{ count }} · {{ text.title }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" class="limits-dialog" :title="text.title" :confirm-label="text.apply" :cancel-label="text.cancel" size="wide" scroll-body confirm-variant="primary" :confirm-disabled="!valid || disabled" @cancel="open=false" @confirm="apply">
    <div class="limits-workspace">
      <p>{{ text.help }}</p>
      <p v-if="available===null" role="status">{{ locale==='zh-CN'?'上游条目不可静态解析，请按配方定义检查 ID；不会从上次成功结果自动添加。':'Upstream items cannot be resolved statically. Review saved IDs; previous results never define required items.' }}</p>
      <div class="limits-tools"><label>{{ text.search }}<input v-model="search" type="search"></label><label>{{ text.group }}<SelectField v-model="group" :options="[{value:'',label:text.all},...groups.map(value=>({value,label:value}))]" /></label><Button variant="secondary" @click="selectVisible">{{ text.select }}</Button></div>
      <p role="status">{{ locale==='zh-CN'?`本页 ${pageRows.length} 项 · 筛选 ${visible.length} / ${draft.length} · 已选 ${selection.length}；切换筛选或翻页会清除选择。`:`${pageRows.length} items on this page · Filtered ${visible.length} / ${draft.length} · Selected ${selection.length}; changing filters or pages clears selection.` }}</p>
      <div class="limits-table"><table><thead><tr><th></th><th>{{ text.item }}</th><th>{{ text.unit }}</th><th>{{ text.lower }}</th><th>{{ text.upper }}</th><th>{{ text.required }}</th><th>{{ text.enabled }}</th><th></th></tr></thead><tbody>
        <tr v-for="index in pageRows" :key="index" :class="{'limits-invalid':rowErrors[index]}">
          <td><input v-model="selection" type="checkbox" :value="index" :aria-label="`${text.select} ${index+1}`"></td>
          <td><SelectField v-if="available" :model-value="draft[index]!.item_id" :options="itemOptions(draft[index]!.item_id)" :aria-label="`${text.item} ${index+1}`" @update:model-value="chooseItem(index,String($event))" /><input v-else v-model="draft[index]!.item_id" :aria-label="`${text.item} ${index+1}`"><small v-if="rowErrors[index]" role="alert">{{ rowErrors[index] }}</small></td>
          <td><span v-if="availableIndex.has(draft[index]!.item_id)" :title="draft[index]!.unit">{{ formatResultUnit(draft[index]!.unit) }}</span><input v-else v-model="draft[index]!.unit" :aria-label="`${text.unit} ${index+1}`"></td>
          <td v-for="bound in bounds" :key="bound"><div class="limits-bound"><input type="number" step="any" placeholder="—" :aria-label="`${text[bound]} ${index+1}`" :value="draft[index]![bound] ?? ''" @input="setBound(index,bound,$event)"><label><input v-model="draft[index]![bound==='lower'?'include_lower':'include_upper']" type="checkbox" :aria-label="`${text[bound==='lower'?'include_lower':'include_upper']} ${index+1}`">{{ locale==='zh-CN'?'含边界':'Inclusive' }}</label></div></td>
          <td v-for="key in flags" :key="key"><input v-model="draft[index]![key]" type="checkbox" :aria-label="`${text[key]} ${index+1}`"></td>
          <td><button type="button" :aria-label="`${text.remove} ${index+1}`" @click="remove(index)">×</button></td>
        </tr>
      </tbody></table></div>
      <PaginationControls v-if="visible.length>100" :offset="offset" :limit="100" :item-count="pageRows.length" :total-count="visible.length" @previous="offset-=100" @next="offset+=100" />
      <Button variant="secondary" :disabled="draft.length>=8192" @click="draft.push(normalizeLimitRule({item_id:'',unit:'millimeter'}))">{{ text.add }}</Button>
      <fieldset v-if="selection.length"><legend>{{ text.batch }} · {{ selection.length }}</legend>
        <label v-for="bound in bounds" :key="bound"><input v-model="batchEnabled[bound]" type="checkbox">{{ text[bound] }}<input :value="batch[bound] ?? ''" type="number" step="any" placeholder="—" :disabled="!batchEnabled[bound]" @input="setBatchBound(bound,$event)"></label>
        <label>{{ text.required }}<SelectField v-model="batchRequired" :options="[{value:null,label:text.keep},{value:true,label:text.yes},{value:false,label:text.no}]" /></label>
        <Button variant="secondary" :disabled="!batchValid" @click="applyBatch">{{ text.batchApply }}</Button>
      </fieldset>
      <Button v-if="undo" variant="secondary" @click="draft=undo;undo=null;selection=[]">{{ text.restore }}</Button>
      <p v-if="!valid" role="alert" class="limits-error">{{ text.invalid }}</p>
    </div>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,ref,inject,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import Button from '@/shared/ui/components/Button.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import {limitRuleError,normalizeLimitRule,type LimitRule} from '../parameters/limit-rules'
import {parameterEditorSourcesKey,parameterNumericItemsKey,type ParameterEditorSources} from '../parameters/editor-context'
import {staticNumericItems} from '../parameters/static-numeric-items'
import {formatResultUnit} from '@/shared/ui/image-viewer/result-format'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;disabled?:boolean;inputSources?:ParameterEditorSources}>(),emit=defineEmits<{'update:modelValue':[value:LimitRule[]]}>()
const resolve=inject(parameterEditorSourcesKey,undefined)
const providers=inject(parameterNumericItemsKey,{})
const available=computed(()=>staticNumericItems(props.inputSources,resolve,providers))
const availableIndex=computed(()=>new Map(available.value?.map(item=>[item.item_id,item])))
const availableOptions=computed(()=>(available.value??[]).map(item=>({value:item.item_id,label:item.label??item.item_id})))
function itemOptions(current:string){return availableIndex.value.has(current)?availableOptions.value:[{value:current,label:current||'—'},...availableOptions.value]}
function chooseItem(index:number,id:string){draft.value[index]!.item_id=id;const item=availableIndex.value.get(id);if(item)draft.value[index]!.unit=item.unit}
const {locale}=useI18n()
const text=computed(()=>locale.value==='zh-CN'?{title:'公差规则',apply:'应用',cancel:'取消',help:'按保存的检查项 ID 判定。空白表示不限制该侧；必检集合不随本次成功结果改变。',search:'搜索检查项',group:'分组',all:'全部',select:'选择',item:'检查项',unit:'单位',lower:'下限',upper:'上限',include_lower:'包含下限',include_upper:'包含上限',required:'必检',enabled:'启用',add:'添加规则',remove:'移除',batch:'批量设置',batchApply:'更新所选规则',restore:'恢复批量设置前',keep:'保持不变',yes:'是',no:'否',invalid:'检查重复 ID、无效数值和空区间；至少启用一个必检项。',identity:'检查 ID 和单位',number:'请输入有限数值',boolean:'必须是布尔值',bound:'至少设置一侧界限',interval:'区间为空或上下限倒置',duplicate:'ID 重复'}:{title:'Limits',apply:'Apply',cancel:'Cancel',help:'Checks use saved item IDs. Blank means no bound on that side. Required items never follow only successful observations.',search:'Search items',group:'Group',all:'All',select:'Select',item:'Item',unit:'Unit',lower:'Lower',upper:'Upper',include_lower:'Include lower',include_upper:'Include upper',required:'Required',enabled:'Enabled',add:'Add rule',remove:'Remove',batch:'Batch settings',batchApply:'Update selected rules',restore:'Restore before batch',keep:'Unchanged',yes:'Yes',no:'No',invalid:'Check duplicate IDs, invalid numbers and empty intervals; enable at least one required item.',identity:'Check ID and unit',number:'Finite number required',boolean:'Boolean required',bound:'At least one bound required',interval:'Empty or reversed interval',duplicate:'Duplicate ID'})
const bounds=['lower','upper'] as const,flags=['required','enabled'] as const
const open=ref(false),draft=ref<LimitRule[]>([]),undo=ref<LimitRule[]|null>(null),search=ref(''),group=ref<string|number|boolean|null>(''),selection=ref<number[]>([])
const batch=ref<{lower:number|null;upper:number|null}>({lower:null,upper:null}),batchEnabled=ref({lower:false,upper:false}),batchRequired=ref<boolean|string|number|null>(null)
const batchValid=computed(()=>bounds.every(bound=>!batchEnabled.value[bound]||batch.value[bound]===null||Number.isFinite(batch.value[bound])))
const count=computed(()=>Array.isArray(props.modelValue)?props.modelValue.length:0)
const groups=computed(()=>[...new Set(draft.value.map(r=>r.item_id.split(':')[0]!))])
const visible=computed(()=>draft.value.flatMap((r,i)=>r.item_id.toLowerCase().includes(search.value.toLowerCase())&&(!group.value||r.item_id.split(':')[0]===group.value)?[i]:[]))
const offset=ref(0),pageRows=computed(()=>visible.value.slice(offset.value,offset.value+100))
watch([search,group],()=>{selection.value=[];offset.value=0},{flush:'sync'})
watch(offset,()=>{selection.value=[]},{flush:'sync'})
watch(()=>visible.value.length,()=>{if(offset.value>=visible.value.length)offset.value=Math.max(0,Math.floor((visible.value.length-1)/100)*100)})
const rowErrors=computed(()=>{
  const counts=new Map<string,number>();for(const r of draft.value)counts.set(r.item_id,(counts.get(r.item_id)??0)+1)
  return draft.value.map(r=>{const problem=counts.get(r.item_id)!>1?'duplicate':limitRuleError(r);if(problem)return text.value[problem as keyof typeof text.value];if(r.enabled&&available.value){const item=availableIndex.value.get(r.item_id);if(!item)return locale.value==='zh-CN'?'上游配方缺少该项':'Missing from upstream recipe';if(item.unit!==r.unit)return locale.value==='zh-CN'?'单位与上游不一致，请重新选择检查项':'Unit differs from upstream; select the item again'}return ''})
})
const valid=computed(()=>draft.value.length>0&&draft.value.length<=8192&&!rowErrors.value.some(Boolean)&&draft.value.some(r=>r.enabled&&r.required))
function show(){draft.value=Array.isArray(props.modelValue)?props.modelValue.map(r=>normalizeLimitRule(JSON.parse(JSON.stringify(r??{})))):[];undo.value=null;offset.value=0;search.value='';group.value='';selection.value=[];batchEnabled.value={lower:false,upper:false};batchRequired.value=null;open.value=true}
function apply(){if(valid.value&&!props.disabled){emit('update:modelValue',JSON.parse(JSON.stringify(draft.value)));open.value=false}}
function setBound(index:number,bound:'lower'|'upper',event:Event){const input=event.target as HTMLInputElement;draft.value[index]![bound]=input.validity.badInput?NaN:input.value===''?null:Number(input.value)}
function remove(index:number){draft.value.splice(index,1);selection.value=[]}
function selectVisible(){selection.value=pageRows.value.every(i=>selection.value.includes(i))?[]:[...pageRows.value]}
function setBatchBound(bound:'lower'|'upper',event:Event){const input=event.target as HTMLInputElement;batch.value[bound]=input.validity.badInput?NaN:input.value===''?null:Number(input.value)}
function applyBatch(){if(!batchValid.value)return;undo.value=structuredClone(draft.value.map(r=>({...r})));for(const i of selection.value){const r=draft.value[i];if(!r||!pageRows.value.includes(i))continue;for(const bound of bounds)if(batchEnabled.value[bound])r[bound]=batch.value[bound];if(typeof batchRequired.value==='boolean')r.required=batchRequired.value}}
</script>
<style scoped>
.limits-dialog :deep(.confirm-dialog) { width:min(1100px,calc(100vw - 36px)); }
.limits-summary { width:100%; text-align:left; padding:6px 8px; border:1px solid var(--am-border); border-radius:var(--am-radius-sm); background:var(--am-input); color:var(--am-text); font:inherit; cursor:pointer; }
.limits-workspace { display:grid; gap:12px; font-size:13px; }
.limits-workspace p { margin:0; }
.limits-tools,fieldset { display:flex; align-items:end; flex-wrap:wrap; gap:12px; }
label { display:grid; gap:6px; }
.limits-table { max-height:440px; overflow:auto; border:1px solid var(--am-border); }
table { border-collapse:collapse; width:100%; min-width:850px; }
th,td { padding:6px; text-align:left; border-bottom:1px solid var(--am-border); }
th { position:sticky; top:0; background:var(--am-surface); white-space:nowrap; }
td:nth-child(2) { min-width:210px; } td:nth-child(3) { width:100px; } td:nth-child(4),td:nth-child(5) { width:120px; }
.limits-bound { display:grid;gap:6px; }
.limits-bound label { display:flex;align-items:center;font-size:11px;color:var(--am-text-muted);white-space:nowrap; }
input:not([type=checkbox]) { width:100%; min-width:0; padding:6px; border:1px solid var(--am-border); background:var(--am-input); color:var(--am-text); border-radius:var(--am-radius-sm); font:inherit; }
input[type=checkbox] { width:16px; height:16px; min-width:16px; padding:0; }
input:focus-visible { outline:2px solid var(--am-input-focus-ring); }
.limits-error,.limits-invalid small { color:var(--am-danger-text); display:block; }
.limits-invalid { background:color-mix(in srgb,var(--am-danger-text) 6%,transparent); }
fieldset { border:1px solid var(--am-border); padding:12px; }
</style>
