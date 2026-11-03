import fs from 'node:fs'
import path from 'node:path'
import {scenes} from './scenes.js'
const root=path.resolve(import.meta.dirname,'../..')
const specs=path.join(root,'prompts/设置完整设计请求')
const descriptions={details:'运行状态展开模型训练消费者明细（三列、9项）与技术信息；所有技术ID完整保留，行下方展开不挤压表格列。',normal:'保留本页正常字段和功能，具体数据以设计样稿中的当前页面为准。',create:'创建用户弹窗：用户名、显示名称、密码，页面权限、操作权限、全部/指定项目，是否同时创建长期Token。正文可滚动，底部取消和创建固定；未填写时创建禁用。',access:'编辑权限弹窗：页面权限、全部操作与单项操作、全部/指定项目；全部操作启用时所有单项显示选中并禁用。保留取消和保存。',delete:'删除普通用户确认：显示目标名称，短句说明会话和Token失效，项目/数据集/模型不受影响；取消为中性，删除为实红。',revoke:'撤销Token确认：显示Token名称，说明调用将无法认证、无法恢复；取消与红色撤销。','token-form':'用户详情中展开Token行内创建：名称、有效期整数小时、创建按钮；留空有效期表示永久。','token-result':'新Token一次性展示：只使用DEMO-ONLY-NOT-A-VALID-TOKEN占位，复制按钮和关闭入口；一行提醒仅本次显示。',password:'用户密码重置展开：新密码，撤销现有会话默认选中，撤销长期Token默认不选；未填写时提交禁用。',readonly:'用户管理只读：一行说明当前仅可查看，创建、权限修改、删除、禁用、撤销均禁用，读取内容正常显示。',projects:'启动页面选择项目页面，隐藏项目与运行实例字段；恢复默认与保存保持原位置，未修改时保存禁用。',invalid:'应用模式的原运行实例已删除，保留原目标的失效提示，提示重新选择；不能显示运行成功，保存禁用。','leave-confirm':'离开启动设置确认：提示未保存修改；继续编辑、放弃修改并离开。',loading:'首次获取服务状态：未获取，不显示假正常或错误，元数据以—显示，Worker表显示读取中。',partial:'服务信息中backend-worker为部分异常；六项Profile仅conversion未响应，5/6，32秒前、心跳超时；其他行保持正常。',stale:'连接中断：保留上次正常数据、上次检查时间，顶部黄色待确认提示与重新检查；不把所有服务改红。',error:'当前NVIDIA profile必需的Python依赖异常：torch导入失败，tensorrt未安装，其他依赖已安装中性；短提示、重新检查、技术详情默认收起。',cpu:'设备信息CPU-only：CPU推理是正常模式，CUDA、TensorRT和可选NPU显示中性未配置，OpenVINO可用；不显示故障。'}
fs.mkdirSync(specs,{recursive:true})
for(const s of scenes){
  const common=`为AMVAR工业视觉工作站设计“${s.name}”。当前日期2026-11-02，视口${s.width}×${s.height}，保留当前设置导航和合理页面结构，优化控件、分组、表格与信息层级。左侧全局导航64px、设置导航220px，无独立顶栏。正文14px，表格13px，局部标题18px；Lucide细线图标、现有AM品牌图，不创造新装饰。\n${descriptions[s.state]||descriptions.normal}\n所有选中单选/多选使用品牌绿色底与纯白圆点/勾，不得绘制黑色标记。权限分组标题清楚，选择行易点击。运行状态首屏突出健康与数量；Worker技术信息在本区可展开；点击消费者数量，在对应表格行下方展开全宽明细，三列排列完整名称，字段完整保留，避免窄单元格碎行和超高行。表格中性表头，表单对齐且宽度合适，Token输入与按钮等高。仅一张完整界面。使用均匀纯色背景，无渐变、暗角、纹理。正常状态少说明，错误保留短原因和下一步。长表可滚动，数字不拆字，弹窗遮罩覆盖整个页面且不挤压背景，正文滚动，底部操作可见。全部数据为设计样例，禁止真实密码与Token。${s.id.endsWith('short')?'短屏保留Logo点击展开导航，不添加顶部展开按钮。':''}\n本轮采用Vue 3隔离样稿的浏览器渲染输出，固定DOM和主题变量，不把此规格记为ImageGen实际调用。样稿场景：${s.id}。\n`
  for(const [theme,cn] of [['light','亮色'],['dark','暗色']]){
    const text=common+(theme==='light'?'亮色：页面#F6F7F9、导航/面板#FFFFFF，正文#344054、标题#171A1F，边框#E4E7EC。':'暗色：页面/全局导航#101010、设置导航/面板#171918，正文#E9EEEB，标题#F2F2F2，边框#343936。只切换主题颜色，不改变任何元素几何位置。')+'\n品牌#00D992保持，主按钮白字；已配置、已安装、可选未配置用中性；运行正常/可用用绿点加中性正文；异常红色，待确认黄色。hover和focus中性灰。\n'
    fs.writeFileSync(path.join(specs,`${s.name}-${cn}.txt`),text)
  }
  if(s.state==='normal'&&!s.id.endsWith('short'))fs.writeFileSync(path.join(specs,`${s.name}.txt`),common+'亮暗共用同一布局，仅改变主题变量。\n')
}
fs.writeFileSync(path.join(root,'prototypes/settings/scenes.json'),JSON.stringify(scenes,null,2))
console.log(`已写入 ${scenes.length*2} 份中文状态规格与9份正常页基础规格`)

// 消费者数量可点击；在对应表格行下方展开全宽明细，三列排列完整名称，避免窄单元格碎行和超高行。
