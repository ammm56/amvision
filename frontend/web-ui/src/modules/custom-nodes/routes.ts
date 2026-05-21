import type { RouteRecordRaw } from 'vue-router'

const CustomNodeCatalogPage = () => import('./pages/CustomNodeCatalogPage.vue')

export const customNodeRoutes: RouteRecordRaw[] = [
  {
    path: '/custom-nodes',
    component: CustomNodeCatalogPage,
    meta: { requiredScopes: ['workflows:read'] },
  },
]