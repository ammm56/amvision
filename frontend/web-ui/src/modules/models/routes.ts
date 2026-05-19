import type { RouteRecordRaw } from 'vue-router'

import ModelOperationsPage from './pages/ModelOperationsPage.vue'

export const modelRoutes: RouteRecordRaw[] = [
  {
    path: '/models',
    component: ModelOperationsPage,
    meta: { requiredScopes: ['models:read', 'tasks:read'] },
  },
]