import type { RouteRecordRaw } from 'vue-router'

import DatasetImportDetailPage from './pages/DatasetImportDetailPage.vue'
import DatasetOperationsPage from './pages/DatasetOperationsPage.vue'

export const datasetRoutes: RouteRecordRaw[] = [
  {
    path: '/datasets',
    component: DatasetOperationsPage,
    meta: { requiredScopes: ['datasets:read'] },
  },
  {
    path: '/datasets/imports/:datasetImportId',
    component: DatasetImportDetailPage,
    meta: { requiredScopes: ['datasets:read'] },
  },
]