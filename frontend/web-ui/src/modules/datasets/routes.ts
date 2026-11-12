import type { RouteRecordRaw } from 'vue-router'

const DatasetRecordPage = () => import('./pages/DatasetRecordPage.vue')
const DatasetCatalogPage = () => import('./pages/DatasetCatalogPage.vue')
const DatasetVersionPage = () => import('./pages/DatasetVersionPage.vue')
const DatasetTransferPage = () => import('./pages/DatasetTransferRoute.vue')

export const datasetRoutes: RouteRecordRaw[] = [
  {
    path: '/datasets/:datasetId/versions/:versionId/tools/:operation',
    component: () => import('./pages/DatasetOperationRoute.vue'),
    meta: { requiredScopes: ['datasets:read'] },
  },
  {
    path: '/datasets',
    component: DatasetCatalogPage,
    meta: { requiredScopes: ['datasets:read'] },
  },
  {
    path: '/datasets/import',
    component: DatasetTransferPage,
    meta: { requiredScopes: ['datasets:write'] },
  },
  {
    path: '/datasets/export',
    component: DatasetTransferPage,
    meta: { requiredScopes: ['datasets:write'] },
  },
  {
    path: '/datasets/:datasetId/versions/:versionId',
    component: DatasetVersionPage,
    meta: { requiredScopes: ['datasets:read'] },
  },
  {
    path: '/datasets/imports/:datasetImportId',
    component: DatasetRecordPage,
    props: { kind: 'imports' },
    meta: { requiredScopes: ['datasets:read'] },
  },
  {
    path: '/datasets/exports/:datasetExportId',
    component: DatasetRecordPage,
    props: { kind: 'exports' },
    meta: { requiredScopes: ['datasets:read'] },
  },
]
