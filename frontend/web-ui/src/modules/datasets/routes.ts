import type { RouteRecordRaw } from 'vue-router'

const DatasetExportDetailPage = () => import('./pages/DatasetExportDetailPage.vue')
const DatasetImportDetailPage = () => import('./pages/DatasetImportDetailPage.vue')
const DatasetOperationsPage = () => import('./pages/DatasetOperationsPage.vue')

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
  {
    path: '/datasets/exports/:datasetExportId',
    component: DatasetExportDetailPage,
    meta: { requiredScopes: ['datasets:read'] },
  },
]
