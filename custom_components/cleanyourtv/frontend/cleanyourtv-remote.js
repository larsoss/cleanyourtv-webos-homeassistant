/* CleanYourTV remote card: the Phone remote of CleanYourTV (Edenik's page, MIT) in a Home Assistant card.
 *
 *   type: custom:cleanyourtv-remote
 *   entity: media_player.your_tv     (the CleanYourTV media player)
 *   height: auto                     (optional: auto = as high as the remote needs, at most the screen; or a number of pixels)
 *   theme: auto                      (optional: auto = as Home Assistant's theme, light or dark)
 *   close: auto                      (optional: a close button beside the power button; auto = only in a popup, true = always, false = never)
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

  // the popups the card can be in: Home Assistant's own dialogs, browser_mod, Bubble Card (and other cards that open on a #hash)
  const DIALOGS = ['HA-DIALOG', 'HA-MD-DIALOG', 'HA-ADAPTIVE-DIALOG', 'BROWSER-MOD-POPUP', 'HA-MORE-INFO-DIALOG', 'HUI-DIALOG-EDIT-CARD'];
  const up = el => el.parentNode || el.host || null; // through shadow roots
  const isBubble = el => el.classList && (el.classList.contains('bubble-pop-up') || el.classList.contains('pop-up'));

  class CleanYourTVRemote extends HTMLElement {
    setConfig(config) {
      if (!config || !config.entity) throw new Error('entity: the CleanYourTV media player');
      this._config = Object.assign({ height: 'auto' }, config);
      this._listeners = [];
      this._built = false;
      if (this._card) this._card.classList.toggle('plain', !!this._config.plain);
      if (this._frame) this._build();
      this._placeClose();
      this._theme();
    }

    static getStubConfig(hass) {
      const ents = (hass && hass.entities) || {};
      const id = Object.keys(ents).find(e => e.startsWith('media_player.') && ents[e].platform === 'cleanyourtv');
      return { entity: id || 'media_player.lg_tv' };
    }

    // a fixed height in pixels, or null for auto (no reload of the page inside); the remote page passes the room it has as the most
    setHeight(px, most) {
      if (!this._config) return;
      this._config.height = px || 'auto';
      this._most = most || 0;
      this._fit();
    }

    _fixed() {
      const h = Number(this._config && this._config.height);
      return h > 0 ? h : 0;
    }

    // how high the remote is when nothing in it has to scroll: its top bar, the buttons of the Remote tab and the tab bar
    _natural() {
      try {
        const d = this._frame.contentDocument;
        const head = d.querySelector('#remote .head'),
          cv = d.querySelector('#kb > .cv'),
          tabs = d.querySelector('#remote .tabbar');
        if (!head || !cv || !tabs || !head.offsetHeight) return 0;
        const m = parseFloat(getComputedStyle(cv).marginTop) || 0;
        return Math.ceil(head.offsetHeight + cv.offsetHeight + m + 8 + tabs.offsetHeight);
      } catch (e) {
        return 0;
      }
    }

    _watch() {
      if (this._ro) this._ro.disconnect();
      this._ro = null;
      let tries = 0;
      const look = () => {
        this._fit();
        try {
          const w = this._frame.contentWindow,
            d = this._frame.contentDocument;
          const parts = ['#remote .head', '#kb > .cv', '#remote .tabbar'].map(q => d.querySelector(q));
          if (w.ResizeObserver && parts.every(Boolean)) {
            this._ro = new w.ResizeObserver(() => this._fit());
            parts.forEach(el => this._ro.observe(el));
            return;
          }
        } catch (e) {}
        if (++tries < 40) setTimeout(look, 250);
      };
      look();
    }

    _fit() {
      if (!this._frame) return;
      const fixed = this._fixed();
      if (fixed) {
        this._frame.style.height = fixed + 'px';
        return;
      }
      // auto: as high as the remote needs, at most the window (a popup, a phone) and the room the remote page gives it
      let h = this._natural() || 680;
      h = Math.min(h, Math.max(420, (window.innerHeight || h) - 24));
      if (this._most) h = Math.min(h, this._most);
      this._frame.style.height = Math.max(360, h) + 'px';
    }

    getCardSize() {
      return Math.ceil((this._fixed() || 680) / 50);
    }

    // dark or light: the card's own setting, or Home Assistant's theme (its dark mode)
    _dark() {
      const t = this._config && this._config.theme;
      if (t === 'dark') return true;
      if (t === 'light') return false;
      const th = this._hass && this._hass.themes;
      if (th && typeof th.darkMode === 'boolean') return th.darkMode;
      return !window.matchMedia || window.matchMedia('(prefers-color-scheme: dark)').matches;
    }

    _theme() {
      const dark = this._dark();
      if (this._card) this._card.classList.toggle('light', !dark);
      // the frame's colour scheme matches its page, or the browser paints an opaque backdrop behind the see-through page
      if (this._frame) this._frame.style.colorScheme = dark ? 'dark' : 'light';
      try {
        const d = this._frame && this._frame.contentDocument;
        if (d && d.documentElement) {
          d.documentElement.classList.toggle('light', !dark);
          d.documentElement.classList.toggle('dark', dark);
        }
      } catch (e) {}
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (!this.shadowRoot) this._render();
      this._placeClose();
      this._theme();
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

    connectedCallback() {
      if (this.shadowRoot) this._placeClose();
    }

    _popup() {
      for (let el = up(this); el; el = up(el)) {
        if (DIALOGS.includes(el.tagName)) return { kind: 'dialog', el };
        if (isBubble(el)) return { kind: 'hash', el };
      }
      return null;
    }

    // the close button sits in the remote's own top bar, beside the power button (the page shows it when the card says so)
    _closable() {
      if (typeof this.closeAction === 'function') return true; // the remote page
      const want = this._config && this._config.close;
      return want === true || want === 'true' || ((want === undefined || want === 'auto') && !!this._popup());
    }

    _placeClose() {
      try {
        const w = this._frame && this._frame.contentWindow;
        if (w && typeof w.CYTV_CLOSE === 'function') w.CYTV_CLOSE(this._closable());
      } catch (e) {}
    }

    _close() {
      if (typeof this.closeAction === 'function') return this.closeAction();
      const p = this._popup();
      const fire = (el, type, detail) => el.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
      if (p && p.kind === 'dialog') {
        const d = p.el;
        if (typeof d.closeDialog === 'function') return d.closeDialog(); // browser_mod, more-info, HA's dialog managers
        if (typeof d.close === 'function') return d.close(); // ha-dialog, ha-md-dialog
      }
      if (window.browser_mod && typeof window.browser_mod.service === 'function') {
        try {
          window.browser_mod.service('close_popup', {});
        } catch (e) {}
      }
      if (location.hash) {
        // Bubble Card and the like: the popup is open while the address has its #hash
        history.replaceState(history.state, '', location.href.split('#')[0]);
        fire(window, 'location-changed', { replace: true });
      }
      fire(this, 'dialog-closed', {});
      fire(this, 'hass-more-info', { entityId: '' });
    }

    _render() {
      const root = this.attachShadow({ mode: 'open' });
      root.innerHTML = `<style>
        /* the page is see-through: the remote stands on the card's own background (or the page's, without a card frame) */
        ha-card{overflow:hidden}
        ha-card.plain{background:none;border:0;box-shadow:none}
        iframe{display:block;width:100%;border:0;background:transparent}
        .msg{padding:16px;color:var(--primary-text-color)}
      </style><ha-card><div class="msg" id="msg"></div><iframe id="f" title="CleanYourTV remote" allow="vibrate"></iframe></ha-card>`;
      this._frame = root.getElementById('f');
      this._msg = root.getElementById('msg');
      this._card = root.querySelector('ha-card');
      if (this._config && this._config.plain) this._card.classList.add('plain');
      this._frame.addEventListener('load', () => {
        this._theme();
        this._placeClose();
        // measured whenever the remote's parts change size: when the page shows the remote (after it connects), when its fonts are in
        this._watch();
      });
      window.addEventListener('resize', () => this._fit());
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
        this._fit();
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
          dark: () => card._dark(),
          closable: () => card._closable(),
          close: () => card._close(),
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
