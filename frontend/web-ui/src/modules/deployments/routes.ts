import type { RouteRecordRaw } from 'vue-router'

import DeploymentOperationsPage from './pages/DeploymentOperationsPage.vue'

export const deploymentRoutes: RouteRecordRaw[] = [
  {
    path: '/deployments',
    component: DeploymentOperationsPage,
    meta: { requiredScopes: ['models:read'] },
  },
]