export const scenes = [
  ['preferences','设置-偏好','preferences','normal'],['startup','设置-启动页面','startup','normal'],['services','设置-运行状态','services','normal'],
  ['about','设置-关于','about','normal'],['host','设置-系统信息','host','normal'],['python','设置-Python运行时','python','normal'],['devices','设置-设备信息','devices','normal'],['session','设置-会话与权限','session','normal'],['accounts','设置-用户管理','accounts','normal'],
  ['create','创建用户','accounts','create'],['access','编辑权限','accounts','access'],['token-form','创建Token','accounts','token-form'],['token-result','Token创建结果','accounts','token-result'],['password','重置用户密码','accounts','password'],['delete','删除用户确认','accounts','delete'],['revoke','撤销Token确认','accounts','revoke'],['readonly','用户管理-只读','accounts','readonly'],
  ['startup-projects','启动页面-项目页面','startup','projects'],['startup-invalid','启动页面-目标失效','startup','invalid'],['leave-confirm','启动页面-离开确认','startup','leave-confirm'],
  ['services-loading','运行状态-首次加载','services','loading'],['services-partial','运行状态-部分异常','services','partial'],['services-stale','运行状态-断线待确认','services','stale'],['python-error','Python运行时-依赖异常','python','error'],['devices-cpu','设备信息-CPU模式','devices','cpu'],
  ['services-details','运行状态-技术与消费者明细','services','details',1133,1400],
  ['services-short','运行状态-短屏','services','normal',1366,768],['create-short','创建用户-短屏','accounts','create',1366,768]
].map(([id,name,page,state,width=1133,height=1142])=>({id,name,page,state,width,height}))
