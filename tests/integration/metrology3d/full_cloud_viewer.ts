import {createApp,h,ref} from 'vue'
import {createI18n} from 'vue-i18n'
import CloudViewer from '../../../frontend/web-ui/src/workflows/workflow-editor/point-cloud/CloudViewer.vue'
import {rendererUsage} from '../../../frontend/web-ui/src/workflows/workflow-editor/point-cloud/preview-data'
import {loadRuntimeConfig} from '../../../frontend/web-ui/src/platform/runtime/runtime-config'

await loadRuntimeConfig()
const payload=await (await fetch('/real-preview.json')).json()
const app=createApp({setup(){
  const visible=ref(true),narrow=ref(false),usage=ref('')
  return()=>h('main',{style:{margin:'16px',width:narrow.value?'390px':'calc(100% - 32px)',fontFamily:'Arial, sans-serif',color:'#16252d','--am-border':'#cbd4da','--am-text':'#16252d','--am-surface':'#fff','--am-surface-soft':'#eef2f4','--am-brand-primary':'#167d85','--am-success-surface':'#d6efea'}},[
    h('header',[h('strong','1-1_0.ply'),h('button',{onClick:()=>narrow.value=!narrow.value},'切换窄屏'),h('button',{onClick:()=>visible.value=!visible.value},visible.value?'关闭显示':'重新打开'),h('button',{onClick:()=>usage.value=JSON.stringify(rendererUsage())},'检查释放'),h('output',usage.value)]),
    visible.value?h(CloudViewer,{payload,projectId:'test',allowPick:true}):null,
  ])
}})
app.use(createI18n({legacy:false,locale:'zh-CN',messages:{'zh-CN':{}}}));app.mount('#app')
