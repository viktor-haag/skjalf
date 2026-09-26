import { getCSPNonce } from '@nextcloud/auth'
import { generateUrl } from '@nextcloud/router'

// AppAPI injects this entry into its embedded page. Set nonce and public path
// before loading the Vue/CSS chunk so Nextcloud CSP permits style-loader and the
// chunk is fetched through the authenticated AppAPI proxy.
const nonce = getCSPNonce()
if (nonce) {
  __webpack_nonce__ = nonce
}
__webpack_public_path__ = generateUrl('/apps/app_api/proxy/skjalf/js/')

import(/* webpackChunkName: "skjalf-app" */ './app').catch((error) => {
  console.error('Skjalf could not load its interface.', error)
  const target = document.getElementById('content') || document.getElementById('content-vue')
  if (target) {
    const message = document.createElement('p')
    message.className = 'skjalf-load-error'
    message.textContent = 'Skjalf konnte seine Oberfläche nicht laden. Bitte lade die Seite neu.'
    target.replaceChildren(message)
  }
})
