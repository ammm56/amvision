<template>
  <span v-if="asset" class="file-summary">{{ zh?'使用资源中的字段与坐标定义':'Fields and coordinates from asset' }}</span>
  <button v-else type="button" class="geometry-open" :disabled="disabled" @click="show">
    {{ zh?'点云文件设置':'Point cloud file settings' }}<small>{{ summary }}</small>
  </button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" class="file-dialog" :title="zh?'点云文件设置':'Point cloud file settings'" size="wide" scroll-body confirm-variant="primary" initial-focus="first-field"
      :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" :confirm-disabled="disabled||asset||malformed||issues.length>0"
      @confirm="apply" @cancel="open=false">
      <p v-if="malformed" role="alert">{{ zh?'现有配置结构不合法，未覆盖原配置。':'Existing configuration has an invalid structure and has not been replaced.' }}</p>
      <template v-else>
        <section class="file-section">
          <h3>{{ zh?'文件与坐标':'File and coordinates' }}</h3>
          <div class="file-grid">
            <label>{{ zh?'文件格式与编码':'Format and encoding' }}<UiSelect v-model="draft.profile_id" :options="[...[{ value: '', label: String(choose), disabled: true }], ...(profiles ?? []).flatMap((p) => [{ value: p, label: String(profileLabel(p)), disabled: false }])]" floating /></label>
            <label>{{ zh?'长度单位':'Length unit' }}<UiSelect :model-value="draft.spatial.length_unit??''" @change="setUnit" :options="[...[{ value: '', label: String(zh?'未确认':'Unknown'), disabled: false }], ...(['mm','m','um']).flatMap((u) => [{ value: u, label: String(u), disabled: false }])]" floating /></label>
            <label>{{ zh?'单位来源':'Unit source' }}<UiSelect v-model="draft.spatial.unit_source" :disabled="draft.spatial.length_unit===null" :options="[...(draft.spatial.length_unit===null ? [{ value: 'unknown', label: String(zh?'未确认':'Unknown'), disabled: false }] : []), ...[{ value: 'configuration', label: String(zh?'工程配置':'Configuration'), disabled: false }], ...[{ value: 'metadata', label: String(zh?'文件元数据':'File metadata'), disabled: false }]]" floating /></label>
            <label>{{ zh?'坐标系标识':'Coordinate frame' }}<input v-model="draft.spatial.frame_id" maxlength="128"></label>
            <label>{{ zh?'坐标系手性':'Handedness' }}<UiSelect :model-value="draft.spatial.axes.handedness" @change="setHandedness" :options="[...[{ value: 'unknown', label: String(zh?'未确认':'Unknown'), disabled: false }], ...[{ value: 'right', label: String(zh?'右手系':'Right-handed'), disabled: false }], ...[{ value: 'left', label: String(zh?'左手系':'Left-handed'), disabled: false }]]" floating /></label>
            <label>{{ zh?'轴定义来源':'Axes source' }}<UiSelect v-model="draft.spatial.axes.definition_source" :disabled="draft.spatial.axes.handedness==='unknown'" :options="[...(draft.spatial.axes.handedness==='unknown' ? [{ value: 'unknown', label: String(zh?'未确认':'Unknown'), disabled: false }] : []), ...[{ value: 'configuration', label: String(zh?'工程配置':'Configuration'), disabled: false }], ...[{ value: 'metadata', label: String(zh?'文件元数据':'File metadata'), disabled: false }]]" floating /></label>
            <label v-for="(_,i) in draft.spatial.axes.axis_labels" :key="i">{{ (zh?'轴名称 ':'Axis label ')+(i+1) }}<input v-model="draft.spatial.axes.axis_labels[i]" maxlength="128"></label>
          </div>
        </section>
        <section class="file-section">
          <header><h3>{{ zh?'文件字段对应':'File field mapping' }}</h3><div class="field-actions">
            <button v-if="textLayouts[draft.profile_id]" type="button" @click="layoutConfirm=true">{{ zh?'采用所选文本列布局':'Use selected text layout' }}</button>
            <label>{{ zh?'添加属性':'Add attribute' }}<UiSelect v-model="addKind" :options="[...[{ value: 'normal', label: String(zh?'法向':'Normals'), disabled: false }], ...[{ value: 'color-rgb', label: 'RGB', disabled: false }], ...[{ value: 'validity', label: String(zh?'有效标记':'Validity'), disabled: false }], ...[{ value: 'scalar', label: String(zh?'强度 / 其他标量':'Intensity / other scalar'), disabled: false }]]" floating /></label>
            <button type="button" :title="zh?'添加字段':'Add field'" :aria-label="zh?'添加字段':'Add field'" @click="addField"><Plus :size="16" /></button>
          </div></header>
          <div v-for="(field,i) in draft.field_mapping" :key="i" class="mapping-row">
            <div class="mapping-heading"><strong>{{ i+1 }}. {{ kindLabel(field.semantic) }}</strong><button type="button" :disabled="field.semantic==='position'" :title="zh?'删除字段':'Remove field'" :aria-label="(zh?'删除字段 ':'Remove field ')+(i+1)" @click="draft.field_mapping.splice(i,1)"><Trash2 :size="16" /></button></div>
            <div class="mapping-fields">
              <label>{{ zh?'目标属性名':'Target attribute' }}<input v-model="field.target_name" :readonly="field.semantic!=='scalar'" maxlength="128"></label>
              <label>{{ zh?'数据类型':'Data type' }}<UiSelect v-model="field.dtype" :options="[...[{ value: '', label: String(choose), disabled: true }], ...(allowedTypes(field) ?? []).flatMap((d) => [{ value: d, label: String(d), disabled: false }])]" floating /></label>
              <label>{{ zh?'属性单位':'Attribute unit' }}<input :value="field.unit??''" :readonly="field.semantic!=='scalar'" :placeholder="field.semantic==='scalar'?(zh?'未确认':'Unknown'):'—'" @input="field.unit=($event.target as HTMLInputElement).value||null"></label>
              <div class="source-columns"><label v-for="(_,j) in field.source_names" :key="j">{{ sourceLabel(field,j) }}<input v-model="field.source_names[j]" maxlength="128"></label></div>
            </div>
          </div>
        </section>
        <ul v-if="issues.length" class="file-errors" role="alert"><li v-for="(issue,i) in issues" :key="i">{{ issueLabel(issue) }}</li></ul>
      </template>
    </ConfirmDialog>
    <ConfirmDialog v-if="open&&layoutConfirm" :title="zh?'替换字段布局？':'Replace field layout?'" :confirm-label="zh?'替换':'Replace'" :cancel-label="zh?'取消':'Cancel'" @confirm="resetLayout" @cancel="layoutConfirm=false">
      <p>{{ zh?'当前字段对应将替换为所选文本格式的固定列布局。':'Current field mappings will be replaced by the selected text format column layout.' }}</p>
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import UiSelect from '@/shared/ui/components/Select.vue'
import {computed,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {Plus,Trash2} from '@lucide/vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import type {ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import {object} from './form'
import {profiles,dtypes,newFileOptions,newFileMapping,isFileOptionsShape,fileOptionsIssues,copyFileOptions,textLayouts,textLayoutMappings,type FileMapping,type FieldKind,type FileIssue} from './cloud-file-form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;parameters?:Record<string,unknown>;inputSources?:ParameterEditorSources}>()
const emit=defineEmits<{'update:modelValue':[value:ReturnType<typeof newFileOptions>]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),choose=computed(()=>zh.value?'请选择':'Select')
const asset=computed(()=>object(props.parameters?.source).kind==='asset')
const open=ref(false),malformed=ref(false),layoutConfirm=ref(false),draft=ref(newFileOptions()),addKind=ref<FieldKind>('scalar')
const issues=computed(()=>fileOptionsIssues(draft.value))
const summary=computed(()=>isFileOptionsShape(props.modelValue)?`${profileLabel(props.modelValue.profile_id)} · ${props.modelValue.spatial.length_unit??(zh.value?'单位未确认':'Unknown unit')}`:(zh.value?'未配置':'Not configured'))
const profileNames:Record<string,[string,string]>={
  'ply-ascii':['PLY · 文本','PLY · ASCII'],'ply-binary-le':['PLY · 二进制小端','PLY · Binary LE'],'ply-binary-be':['PLY · 二进制大端','PLY · Binary BE'],
  'pcd-ascii':['PCD · 文本','PCD · ASCII'],'pcd-binary':['PCD · 二进制','PCD · Binary'],'pcd-binary-compressed':['PCD · 压缩二进制','PCD · Compressed binary'],
  'xyz-whitespace':['XYZ · 坐标','XYZ · Positions'],'xyzn-whitespace':['XYZN · 坐标和法向','XYZN · Positions and normals'],'xyzi-whitespace':['XYZI · 坐标和强度','XYZI · Positions and intensity'],'xyzrgb-whitespace':['XYZRGB · 坐标和颜色','XYZRGB · Positions and color'],
}
function profileLabel(p:string){return profileNames[p]?.[zh.value?0:1]??p}
function kindLabel(k:string){return ({position:zh.value?'位置':'Position',normal:zh.value?'法向':'Normals','color-rgb':'RGB',validity:zh.value?'有效标记':'Validity',scalar:zh.value?'标量':'Scalar'} as Record<string,string>)[k]??k}
function sourceLabel(f:FileMapping,i:number){const component=f.semantic==='color-rgb'?['R','G','B'][i]:f.components===3?['X','Y','Z'][i]:'';return `${zh.value?'文件字段':'File field'}${component?' '+component:''}`}
function allowedTypes(f:FileMapping){return ['position','normal'].includes(f.semantic)?['float32','float64']:['color-rgb','validity'].includes(f.semantic)?['uint8']:dtypes}
function setUnit(e:string | number | boolean | null){const value=String(e);draft.value.spatial.length_unit=value||null;draft.value.spatial.unit_source=value?'configuration':'unknown'}
function setHandedness(e:string | number | boolean | null){const value=String(e);draft.value.spatial.axes.handedness=value;draft.value.spatial.axes.definition_source=value==='unknown'?'unknown':'configuration'}
function addField(){draft.value.field_mapping.push(newFileMapping(addKind.value))}
function resetLayout(){draft.value.field_mapping=textLayoutMappings(draft.value.profile_id,draft.value.field_mapping);layoutConfirm.value=false}
function show(){if(props.disabled||asset.value)return;malformed.value=props.modelValue!=null&&!isFileOptionsShape(props.modelValue);draft.value=isFileOptionsShape(props.modelValue)?copyFileOptions(props.modelValue):newFileOptions();layoutConfirm.value=false;open.value=true}
function apply(){if(props.disabled||asset.value||malformed.value||issues.value.length)return;emit('update:modelValue',copyFileOptions(draft.value));open.value=false}
function issueLabel(issue:FileIssue){
  const names:Record<string,string>={configuration:'配置结构',profile_id:'文件格式',profile_version:'配置版本',spatial:'空间定义',frame_id:'坐标系标识',length_unit:'长度单位',unit_source:'单位来源',axes:'轴定义',handedness:'坐标系手性',definition_source:'轴定义来源',axis_labels:'轴名称',field_mapping:'字段对应',positions:'位置字段',target_name:'目标属性名',source_names:'文件字段',dtype:'数据类型',components:'分量',unit:'属性单位',semantic:'字段用途'}
  const path=issue.path.split('.').map(p=>zh.value?(names[p]??p):p.replaceAll('_',' ')).join(' / ')
  const messages={required:zh.value?'请填写或选择合法值':'A valid value is required',invalid:zh.value?'配置不一致或不合法':'Invalid or inconsistent configuration',duplicate:zh.value?'字段重复':'Duplicate field',layout:zh.value?'与所选文本格式的固定列布局不一致':'Does not match selected text column layout'}
  return `${path}: ${messages[issue.code]}`
}
watch([()=>props.modelValue,()=>props.nodeType,()=>props.disabled,()=>JSON.stringify(props.parameters?.source),()=>JSON.stringify(props.inputSources)],()=>{open.value=false;layoutConfirm.value=false},{deep:true})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
.geometry-open small{display:block;font-size:11px;margin-top:4px;overflow-wrap:anywhere}.file-summary{font-size:12px;color:var(--am-text-muted)}
.file-section{padding:12px 0;border-bottom:1px solid var(--am-border)}h3{font-size:14px;margin:0 0 12px}.file-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
input{box-sizing:border-box;min-width:0;width:100%;padding:6px;border:1px solid var(--am-border);border-radius:4px;background:var(--am-input);color:var(--am-text);font:inherit}
header,.field-actions,.mapping-heading{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:space-between}.field-actions{justify-content:flex-end}button{font:inherit}button svg{display:block}.field-actions button,.mapping-heading button{padding:6px;border:1px solid var(--am-border);border-radius:4px;background:var(--am-input);color:var(--am-text)}button:disabled{opacity:.5}
.mapping-row{padding:12px 0;border-top:1px solid var(--am-border)}.mapping-heading{font-size:12px;margin-bottom:8px}.mapping-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.source-columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;grid-column:1/-1}.file-errors{font-size:12px;color:var(--am-danger-text);overflow-wrap:anywhere;padding-left:20px}
@media(max-width:640px){.file-grid,.mapping-fields{grid-template-columns:1fr}.source-columns{grid-template-columns:1fr}.field-actions{justify-content:flex-start}header{align-items:flex-start}}
</style>
