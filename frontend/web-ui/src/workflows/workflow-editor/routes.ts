import type { RouteRecordRaw } from 'vue-router'

const WorkflowEditorPage = () => import('./pages/WorkflowEditorPage.vue')
const WorkflowAppListPage = () => import('./pages/WorkflowAppListPage.vue')

export const workflowEditorRoutes: RouteRecordRaw[] = [
  {
    path: '/workflows',
    redirect: '/workflows/apps',
  },
  {
    path: '/workflows/apps',
    component: WorkflowAppListPage,
    meta: { requiredScopes: ['workflows:read'] },
  },
  {
    path: '/workflows/graph',
    redirect: '/workflows/graph/new',
  },
  {
    path: '/workflows/graph/new',
    component: WorkflowEditorPage,
    meta: { requiredScopes: ['workflows:write'], graphWorkbench: true },
  },
  {
    path: '/workflows/graph/apps/:applicationId',
    component: WorkflowEditorPage,
    meta: { requiredScopes: ['workflows:read'], graphWorkbench: true },
  },
  {
    path: '/workflows/apps/new',
    redirect: '/workflows/graph/new',
  },
  {
    path: '/workflows/apps/:applicationId/edit',
    redirect: (to) => `/workflows/graph/apps/${encodeURIComponent(String(to.params.applicationId ?? ''))}`,
  },
  {
    path: '/workflows/templates',
    redirect: '/workflows/apps',
  },
  {
    path: '/workflows/templates/new',
    redirect: '/workflows/graph/new',
  },
  {
    path: '/workflows/templates/:templateId/versions/:templateVersion/edit',
    redirect: '/workflows/apps',
  },
  {
    path: '/workflows/applications',
    redirect: '/workflows/apps',
  },
]
