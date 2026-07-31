/**
 * @copyright Copyright (c) 2024 Skjalf Team
 *
 * @author Skjalf Team
 *
 * @license AGPL-3.0-or-later
 */

import App from './App.vue'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { translate as t } from '@nextcloud/l10n'

/**
 * @global
 * @type {typeof import('@nextcloud/l10n').translate}
 */
const translate = t

/**
 * @global
 * @type {typeof import('@nextcloud/router').generateUrl}
 */
const generateUrl = generateUrl

const pinia = createPinia()

const AppNextcloud = createApp(App, {
  translate,
  generateUrl,
})

AppNextcloud.use(pinia)
AppNextcloud.mount('#skjalf-search-content')

export default AppNextcloud
