import type { RouteRecordRaw } from 'vue-router'

import { authRoutes } from '@/modules/auth/routes'
import { projectRoutes } from '@/modules/projects/routes'
import { taskRoutes } from '@/modules/tasks/routes'
import ErrorView from '@/views/ErrorView.vue'
import ModulePlaceholderView from '@/views/ModulePlaceholderView.vue'
import NotFoundView from '@/views/NotFoundView.vue'
import StartupView from '@/views/StartupView.vue'

function placeholderRoute(path: string, title: string, description: string, scopes: string[]): RouteRecordRaw {
  return {
    path,
    component: ModulePlaceholderView,
    props: { title, description },
    meta: { requiredScopes: scopes },
  }
}

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: StartupView,
    meta: { shell: 'blank', requiresAuth: false },
  },
  ...authRoutes,
  ...projectRoutes,
  ...taskRoutes,
  placeholderRoute('/datasets', '数据集', '数据集导入、导出和 DatasetVersion 页面将在第一条业务闭环后接入。', [
    'datasets:read',
  ]),
  placeholderRoute('/models', '模型', '模型版本、验证、评估、转换和训练输出文件页面将在模型链路阶段接入。', [
    'models:read',
  ]),
  placeholderRoute('/deployments', '部署', 'DeploymentInstance、health、warmup 和推理调试页面将在部署链路阶段接入。', [
    'models:read',
  ]),
  placeholderRoute('/workflows/templates', '流程模板', 'LiteGraph workflow editor 将在 node catalog 和模板校验链路固定后接入。', [
    'workflows:read',
  ]),
  placeholderRoute('/workflows/applications', '流程应用', 'FlowApplication、AppRuntime 和 WorkflowRun 页面将在 workflow runtime 阶段接入。', [
    'workflows:read',
  ]),
  placeholderRoute('/integrations/trigger-sources', '集成端点', 'TriggerSource 配置和协议入口管理将在 workflow app 调用链路后接入。', [
    'workflows:read',
  ]),
  placeholderRoute('/custom-nodes', '自定义节点', '第一阶段只读 node catalog 页面将在基础壳层稳定后接入。', [
    'workflows:read',
  ]),
  placeholderRoute('/settings', '设置', '用户、token、运行时配置和诊断设置将在基础会话链路后接入。', ['auth:read']),
  {
    path: '/forbidden',
    component: ErrorView,
    props: { kind: 'forbidden' },
    meta: { shell: 'blank', requiresAuth: false },
  },
  {
    path: '/offline',
    component: ErrorView,
    props: { kind: 'offline' },
    meta: { shell: 'blank', requiresAuth: false },
  },
  {
    path: '/:pathMatch(.*)*',
    component: NotFoundView,
    meta: { shell: 'blank', requiresAuth: false },
  },
]