import type { RouteRecordRaw } from 'vue-router'

import { authRoutes } from '@/modules/auth/routes'
import { customNodeRoutes } from '@/modules/custom-nodes/routes'
import { datasetRoutes } from '@/modules/datasets/routes'
import { deploymentRoutes } from '@/modules/deployments/routes'
import { inferenceRoutes } from '@/modules/inference/routes'
import { integrationRoutes } from '@/modules/integrations/routes'
import { modelRoutes } from '@/modules/models/routes'
import { projectRoutes } from '@/modules/projects/routes'
import { settingsRoutes } from '@/modules/settings/routes'
import { taskRoutes } from '@/modules/tasks/routes'
import { workflowEditorRoutes } from '@/workflows/workflow-editor/routes'
import ErrorView from '@/views/ErrorView.vue'
import NotFoundView from '@/views/NotFoundView.vue'
import StartupView from '@/views/StartupView.vue'

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: StartupView,
    meta: { shell: 'blank', requiresAuth: false },
  },
  ...authRoutes,
  ...projectRoutes,
  ...taskRoutes,
  ...datasetRoutes,
  ...modelRoutes,
  ...deploymentRoutes,
  ...inferenceRoutes,
  ...integrationRoutes,
  ...workflowEditorRoutes,
  ...customNodeRoutes,
  ...settingsRoutes,
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