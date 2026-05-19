import type { RouteRecordRaw } from 'vue-router'

import { authRoutes } from '@/modules/auth/routes'
import { projectRoutes } from '@/modules/projects/routes'
import { taskRoutes } from '@/modules/tasks/routes'
import ErrorView from '@/views/ErrorView.vue'
import ModulePlaceholderView from '@/views/ModulePlaceholderView.vue'
import NotFoundView from '@/views/NotFoundView.vue'
import StartupView from '@/views/StartupView.vue'

function placeholderRoute(path: string, titleKey: string, descriptionKey: string, scopes: string[]): RouteRecordRaw {
  return {
    path,
    component: ModulePlaceholderView,
    props: { titleKey, descriptionKey },
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
  placeholderRoute('/datasets', 'placeholders.datasetsTitle', 'placeholders.datasetsDescription', [
    'datasets:read',
  ]),
  placeholderRoute('/models', 'placeholders.modelsTitle', 'placeholders.modelsDescription', [
    'models:read',
  ]),
  placeholderRoute('/deployments', 'placeholders.deploymentsTitle', 'placeholders.deploymentsDescription', [
    'models:read',
  ]),
  placeholderRoute('/workflows/templates', 'placeholders.workflowTemplatesTitle', 'placeholders.workflowTemplatesDescription', [
    'workflows:read',
  ]),
  placeholderRoute('/workflows/applications', 'placeholders.workflowAppsTitle', 'placeholders.workflowAppsDescription', [
    'workflows:read',
  ]),
  placeholderRoute('/integrations/trigger-sources', 'placeholders.integrationsTitle', 'placeholders.integrationsDescription', [
    'workflows:read',
  ]),
  placeholderRoute('/custom-nodes', 'placeholders.customNodesTitle', 'placeholders.customNodesDescription', [
    'workflows:read',
  ]),
  placeholderRoute('/settings', 'placeholders.settingsTitle', 'placeholders.settingsDescription', ['auth:read']),
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