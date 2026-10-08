<template>
  <button type="button" class="calibration-edit" :disabled="disabled" @click="show">{{ count }} · {{ text.points }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" :title="text.points" :confirm-label="text.apply" :cancel-label="text.cancel" confirm-variant="primary" size="wide" scroll-body :confirm-disabled="!valid || disabled" @cancel="close" @confirm="apply">
      <div class="calibration-workspace">
        <p>{{ text.help }} · {{ parameters?.unit || 'millimeter' }}</p>
        <p v-if="error" role="alert" class="calibration-error">{{ error }}</p>
        <label>{{ text.image }}<input type="file" accept=".png,image/png" @change="loadImage"></label>
        <div class="calibration-main">
          <button v-if="imageUrl" type="button" class="calibration-image" @click="viewerOpen = true"><img :src="imageUrl" :alt="text.image"><span>{{ text.mark }} {{ selected + 1 }}</span></button>
          <div class="calibration-table"><table><thead><tr><th>#</th><th>Image X</th><th>Image Y</th><th>World X</th><th>World Y</th><th></th></tr></thead><tbody>
            <tr v-for="(point,index) in draft" :key="index" :class="{selected:index===selected}" @click="selected=index">
              <td>{{ index+1 }}</td><template v-for="space in spaces" :key="space"><td v-for="axis in [0,1]" :key="axis"><input v-model.number="point[space][axis]" type="number" step=".001" :aria-label="`${space} ${index+1} ${axis}`"></td></template>
              <td><button type="button" :aria-label="`${text.remove} ${index+1}`" @click.stop="draft.splice(index,1);selected=Math.min(selected,draft.length-1)">×</button></td>
            </tr>
          </tbody></table></div>
        </div>
        <Button variant="secondary" :disabled="draft.length>=4096" @click="draft.push({image:[0,0],world:[0,0]});selected=draft.length-1">{{ text.add }}</Button>
        <p v-if="!valid" class="calibration-error">{{ text.invalid }}</p>
      </div>
    </ConfirmDialog>
  </Teleport>
  <ImageViewer :open="viewerOpen" :image="viewerImage" :preview-disabled="true" dialog-layer @close="viewerOpen=false" @apply-interaction="mark" />
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Button from '@/shared/ui/components/Button.vue'
import ImageViewer from '@/shared/ui/components/ImageViewer.vue'
interface Point { image:[number,number];world:[number,number] }
const props=defineProps<{modelValue:unknown;disabled?:boolean;parameters?:Record<string,unknown>;parameterName?:string}>()
const emit=defineEmits<{'update:modelValue':[value:Point[]]}>()
const {locale}=useI18n()
const text=computed(()=>locale.value==='zh-CN'?{points:props.parameterName==='validation_points'?'独立验证点':'控制点',apply:'应用',cancel:'取消',help:'原图坐标与独立参考平面坐标一一对应。验证点不得参与拟合；图像仅用于选点，不会自动保存。',image:'选点原图（PNG）',mark:'标记点',remove:'移除',add:'添加点',invalid:'请检查点数、重复点、有限数值和图像范围。',badImage:'图片须为 64 MB 内 PNG，尺寸必须与节点 Image Width/Height 一致。'}:{points:props.parameterName==='validation_points'?'Independent validation points':'Control points',apply:'Apply',cancel:'Cancel',help:'Pair original-image coordinates with independent plane coordinates. Validation points are excluded from fitting. The image is only used for picking and is not saved.',image:'Point picking image (PNG)',mark:'Mark point',remove:'Remove',add:'Add point',invalid:'Check count, duplicate points, finite values and image bounds.',badImage:'Use a PNG up to 64 MB matching the node Image Width/Height.'})
const spaces=['image','world'] as const
const open=ref(false),viewerOpen=ref(false),error=ref(''),imageUrl=ref(''),selected=ref(0),draft=ref<Point[]>([])
const count=computed(()=>Array.isArray(props.modelValue)?props.modelValue.length:0)
const width=computed(()=>Number(props.parameters?.image_width)),height=computed(()=>Number(props.parameters?.image_height))
let generation=0
const valid=computed(()=>draft.value.length>=(props.parameterName==='validation_points'?2:props.parameters?.model==='homography'?4:3)&&draft.value.length<=4096&&new Set(draft.value.map(p=>JSON.stringify(p.image))).size===draft.value.length&&new Set(draft.value.map(p=>JSON.stringify(p.world))).size===draft.value.length&&draft.value.every(p=>[...p.image,...p.world].every(Number.isFinite)&&p.image[0]>=0&&p.image[1]>=0&&p.image[0]<width.value&&p.image[1]<height.value))
const viewerImage=computed(()=>imageUrl.value?{title:text.value.points,nodeId:'calibration-points',src:imageUrl.value,width:width.value,height:height.value,mediaType:'image/png',overlays:draft.value.map((p,i)=>({kind:'point',id:String(i),label:String(i+1),pointsXy:[p.image],bboxXyxy:null,lineXyxy:null,circle:null,targetParameters:[],parameters:{}})),interaction:draft.value[selected.value]?{mode:'edit',coordinateSpace:'image',tools:[{tool:'point',maxPoints:1,targetParameters:['image'],initialPointsXy:[draft.value[selected.value].image]}]}:null}:null)
function close(){generation++;open.value=false;viewerOpen.value=false;if(imageUrl.value)URL.revokeObjectURL(imageUrl.value);imageUrl.value=''}
function show(){close();error.value='';selected.value=0;try{const original=Array.isArray(props.modelValue)?props.modelValue:[];if(original.some(p=>!p||!Array.isArray(p.image)||p.image.length!==2||!Array.isArray(p.world)||p.world.length!==2))throw new Error();draft.value=JSON.parse(JSON.stringify(original))}catch{draft.value=[];error.value=text.value.invalid}open.value=true}
function apply(){if(valid.value&&!props.disabled){emit('update:modelValue',JSON.parse(JSON.stringify(draft.value)));close()}}
async function loadImage(event:Event){const file=(event.target as HTMLInputElement).files?.[0],token=generation;if(!file)return;try{const b=new Uint8Array(await file.slice(0,24).arrayBuffer());if(file.size>64*1024*1024||b.length!==24||b[0]!==137||b[1]!==80||b[2]!==78||b[3]!==71)throw new Error();const view=new DataView(b.buffer);if(view.getUint32(16)!==width.value||view.getUint32(20)!==height.value||width.value*height.value>16_000_000)throw new Error();if(token!==generation)return;if(imageUrl.value)URL.revokeObjectURL(imageUrl.value);imageUrl.value=URL.createObjectURL(file);error.value=''}catch{if(token===generation)error.value=text.value.badImage}}
function mark(event:{pointsXy?:Array<[number,number]>;onApplied?:(ok:boolean)=>void}){const p=draft.value[selected.value];if(p&&event.pointsXy?.length){p.image=[...event.pointsXy[0]];event.onApplied?.(true)}else event.onApplied?.(false)}
onBeforeUnmount(close)
</script>
<style scoped>
.calibration-edit { width:100%; text-align:left; padding:6px 8px; color:var(--am-text); background:var(--am-input); border:1px solid var(--am-border); border-radius:var(--am-radius-sm); font:inherit; cursor:pointer; }
.calibration-workspace { display:grid; gap:12px; font-size:13px; }
.calibration-main { display:flex; flex-wrap:wrap; gap:12px; }
.calibration-table { flex:1 1 400px; max-height:360px; overflow:auto; border:1px solid var(--am-border); }
table { width:100%; min-width:500px; border-collapse:collapse; }
th,td { padding:6px; text-align:left; border-bottom:1px solid var(--am-border); }
th { position:sticky; top:0; background:var(--am-surface); }
tr.selected { background:var(--am-row-selected); }
input { width:100%; min-width:65px; padding:6px; color:var(--am-text); background:var(--am-input); border:1px solid var(--am-border); border-radius:var(--am-radius-sm); font:inherit; }
input:focus-visible { outline:2px solid var(--am-input-focus-ring); }
.calibration-image { width:220px; align-self:start; display:grid; gap:8px; padding:8px; color:var(--am-text); background:var(--am-surface); border:1px solid var(--am-border); cursor:pointer; }
.calibration-image img { max-width:100%; max-height:220px; object-fit:contain; }
.calibration-error { color:var(--am-danger-text); }
</style>
