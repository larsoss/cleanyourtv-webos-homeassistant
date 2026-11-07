/* CleanYourTV remote card: the Phone remote of CleanYourTV (Edenik's page, MIT) in a Home Assistant card.
 *
 *   type: custom:cleanyourtv-remote
 *   entity: media_player.your_tv     (the CleanYourTV media player)
 *   height: 720                      (optional, in pixels)
 *
 * The page itself is in pages/<language>.html (made by tools/build-card.js). It runs in a frame of the same origin; this card answers
 * its WebSocket and its list requests by asking Home Assistant (the cleanyourtv/* WebSocket commands of the integration).
 */
(() => {
  const BASE = new URL('.', import.meta.url).pathname; // /cleanyourtv_static/
  const VERSION = new URL(import.meta.url).searchParams.get('v') || '';
  const KEYS = ['UP', 'DOWN', 'LEFT', 'RIGHT', 'ENTER', 'BACK', 'HOME', 'MENU', 'EXIT', 'INFO', 'POWER', 'VOLUMEUP', 'VOLUMEDOWN',
    'MUTE', 'CHANNELUP', 'CHANNELDOWN', 'PLAY', 'PAUSE', 'STOP', 'REWIND', 'FASTFORWARD', 'RED', 'GREEN', 'YELLOW', 'BLUE',
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'];
  let langsP = null;
  const langs = () => (langsP = langsP || fetch(BASE + 'langs.json?v=' + VERSION).then(r => r.json()).catch(() => ['en']));

  class CleanYourTVRemote extends HTMLElement {
    setConfig(config) {
      if (!config || !config.entity) throw new Error('entity: the CleanYourTV media player');
      this._config = Object.assign({ height: 720 }, config);
      this._listeners = [];
      this._built = false;
      if (this._frame) this._build();
    }

    static getStubConfig(hass) {
      const ents = (hass && hass.entities) || {};
      const id = Object.keys(ents).find(e => e.startsWith('media_player.') && ents[e].platform === 'cleanyourtv');
      return { entity: id || 'media_player.lg_tv' };
    }

    getCardSize() {
      return Math.ceil((this._config ? this._config.height : 720) / 50);
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (!this.shadowRoot) this._render();
      if (first || !this._built) this._build();
      const st = hass.states[this._config.entity];
      const key = st ? [st.attributes.connected, st.attributes.power_state, st.state].join('|') : 'none';
      if (key !== this._last) {
        this._last = key;
        this._listeners.forEach(cb => {
          try {
            cb();
          } catch (e) {}
        });
      }
    }

    _render() {
      const root = this.attachShadow({ mode: 'open' });
      root.innerHTML = `<style>
        ha-card{overflow:hidden;background:#121318}
        iframe{display:block;width:100%;border:0;background:#121318}
        .msg{padding:16px;color:var(--primary-text-color)}
      </style><ha-card><div class="msg" id="msg"></div><iframe id="f" title="CleanYourTV remote" allow="vibrate"></iframe></ha-card>`;
      this._frame = root.getElementById('f');
      this._msg = root.getElementById('msg');
    }

    _say(text) {
      this._msg.textContent = text;
      this._msg.style.display = text ? 'block' : 'none';
    }

    async _build() {
      if (!this._hass || !this._frame || this._building) return;
      this._building = true;
      try {
        const hass = this._hass,
          entity = this._config.entity;
        this._frame.style.height = this._config.height + 'px';
        let info;
        try {
          info = await hass.callWS({ type: 'cleanyourtv/card', entity_id: entity });
        } catch (e) {
          this._say(`${entity} is not a CleanYourTV media player.`);
          return;
        }
        this._say('');
        const card = this;
        const attr = () => {
          const s = card._hass.states[entity];
          return (s && s.attributes) || {};
        };
        this._frame.__cytv = {
          secret: info.secret,
          pic: '/api/cleanyourtv/' + info.entry_id,
          model: info.model,
          mac: info.mac,
          keys: KEYS,
          connected: () => attr().connected === true,
          power: () => attr().power_state || (attr().connected ? 'Active' : ''),
          action: m => card._hass.callWS({ type: 'cleanyourtv/action', entry_id: info.entry_id, action: m }),
          list: kind => card._hass.callWS({ type: 'cleanyourtv/list', entry_id: info.entry_id, kind }),
          wake: () => card._hass.callService('media_player', 'turn_on', { entity_id: entity }),
          onChange: cb => card._listeners.push(cb),
        };
        const want = String((hass.locale && hass.locale.language) || hass.language || 'en').slice(0, 2);
        const lang = (await langs()).includes(want) ? want : 'en';
        const html = await fetch(`${BASE}pages/${lang}.html?v=${VERSION}`).then(r => r.text());
        this._listeners = [];
        this._frame.srcdoc = html;
        this._built = true;
      } finally {
        this._building = false;
      }
    }
  }

  if (!customElements.get('cleanyourtv-remote')) customElements.define('cleanyourtv-remote', CleanYourTVRemote);
  window.customCards = window.customCards || [];
  if (!window.customCards.some(c => c.type === 'cleanyourtv-remote'))
    window.customCards.push({
      type: 'cleanyourtv-remote',
      name: 'CleanYourTV remote',
      description: 'The Phone remote of CleanYourTV: buttons, touchpad, apps and Live TV.',
      preview: false,
    });
})();
