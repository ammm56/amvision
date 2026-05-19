import type { RouteRecordRaw } from 'vue-router'

import DatasetOperationsPage from './pages/DatasetOperationsPage.vue'

export const datasetRoutes: RouteRecordRaw[] = [
  {
    path: '/datasets',
    component: DatasetOperationsPage,
    meta: { requiredScopes: ['datasets:read'] },
  },
]