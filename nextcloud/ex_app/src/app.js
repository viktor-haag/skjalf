import Vue from 'vue'
import App from './App.vue'
import './style.css'

Vue.config.productionTip = false

const mountTarget = document.getElementById('content') || document.getElementById('content-vue')
if (!mountTarget) {
  throw new Error('Skjalf embedded page did not provide #content or #content-vue.')
}

new Vue({ render: h => h(App) }).$mount(mountTarget)
