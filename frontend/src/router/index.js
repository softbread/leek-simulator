import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Process from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'
import MarketConfigView from '../views/MarketConfigView.vue'
import MarketSimulationView from '../views/MarketSimulationView.vue'
import MarketResultsView from '../views/MarketResultsView.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home
  },
  {
    path: '/market/runs/:runId',
    name: 'MarketConfig',
    component: MarketConfigView,
    props: true
  },
  {
    path: '/market/runs/:runId/simulate',
    name: 'MarketSimulation',
    component: MarketSimulationView,
    props: true
  },
  {
    path: '/market/runs/:runId/results',
    name: 'MarketResults',
    component: MarketResultsView,
    props: true
  },
  {
    path: '/process/:projectId',
    name: 'Process',
    component: Process,
    props: true
  },
  {
    path: '/simulation/:simulationId',
    name: 'Simulation',
    component: SimulationView,
    props: true
  },
  {
    path: '/simulation/:simulationId/start',
    name: 'SimulationRun',
    component: SimulationRunView,
    props: true
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    component: ReportView,
    props: true
  },
  {
    path: '/interaction/:reportId',
    name: 'Interaction',
    component: InteractionView,
    props: true
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
