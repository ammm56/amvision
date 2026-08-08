import type { RouteRecordRaw } from 'vue-router'

const DeploymentOperationsPage = () => import('./pages/DeploymentOperationsPage.vue')

export const deploymentRoutes: RouteRecordRaw[] = [
  {
    path: '/deployments',
    component: DeploymentOperationsPage,
    meta: { requiredScopes: ['models:read'] },
  },
]
