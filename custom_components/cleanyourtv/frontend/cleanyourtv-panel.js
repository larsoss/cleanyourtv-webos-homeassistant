/* The CleanYourTV remote as a page of its own (the sidebar's "TV remote", and Open on the TV's device page): the remote card, as large
 * as a phone, in the middle of the page. ?entry=<config entry> picks the TV; with several TVs there is a choice at the top. */
import './cleanyourtv-remote.js';

class CleanYourTVPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) this._render();
    this._pick();
    if (this._card) this._card.hass = hass;
  }

  set narrow(v) {
    this._narrow = v;
  }

  _render() {
    const root = this.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>
      :host{display:block;background:var(--primary-background-color)}
      .bar{flex:none;display:flex;align-items:center;height:56px;padding:0 8px;color:var(--app-header-text-color,var(--primary-text-color));background:var(--app-header-background-color,var(--primary-background-color))}
      .bar h1{font:400 20px/1 var(--ha-font-family-body,Roboto,sans-serif);margin:0 0 0 8px;flex:1}
      select{font:inherit;background:transparent;color:inherit;border:1px solid var(--divider-color);border-radius:8px;padding:6px}
      .wrap{box-sizing:border-box;width:100%;max-width:440px;margin:0 auto}
      .msg{padding:24px;color:var(--primary-text-color)}
    </style><div class="bar"><ha-menu-button></ha-menu-button><h1 id="t">TV</h1><select id="s" hidden></select></div><div class="wrap" id="w"></div>`;
    root.getElementById('s').addEventListener('change', e => this._show(e.target.value));
    // the remote is as high as it needs, at most the room under the bar: the page never scrolls
    const w = root.getElementById('w');
    // the room: from the top of the remote to the bottom of the window (whatever Home Assistant puts around the page, the app's safe areas)
    const fit = () => this._card && this._card.setHeight(null, Math.max(360, Math.floor(window.innerHeight - w.getBoundingClientRect().top) - 4));
    if (window.ResizeObserver) new ResizeObserver(fit).observe(w);
    window.addEventListener('resize', fit);
    this._fit = fit;
  }

  // close: back to the page the remote was opened from (a dashboard, the device page), or to the default dashboard without one
  _leave() {
    if (history.length > 1) return history.back();
    history.pushState(null, '', '/');
    window.dispatchEvent(new CustomEvent('location-changed', { detail: { replace: false } }));
  }

  async _pick() {
    if (this._tvs) return;
    this._tvs = [];
    const mb = this.shadowRoot.querySelector('ha-menu-button');
    if (mb) {
      mb.hass = this._hass;
      mb.narrow = this._narrow;
    }
    try {
      this._tvs = await this._hass.callWS({ type: 'cleanyourtv/tvs' });
    } catch (e) {}
    const w = this.shadowRoot.getElementById('w');
    if (!this._tvs.length) {
      w.innerHTML = '<div class="msg">No CleanYourTV TV is set up yet.</div>';
      return;
    }
    const want = new URLSearchParams(location.search).get('entry');
    const first = this._tvs.find(t => t.entry_id === want) || this._tvs[0];
    const s = this.shadowRoot.getElementById('s');
    if (this._tvs.length > 1) {
      s.hidden = false;
      s.innerHTML = this._tvs.map(t => `<option value="${t.entry_id}">${t.title.replace(/</g, '&lt;')}</option>`).join('');
      s.value = first.entry_id;
    }
    this._show(first.entry_id);
  }

  _show(entryId) {
    const tv = this._tvs.find(t => t.entry_id === entryId);
    if (!tv) return;
    this.shadowRoot.getElementById('t').textContent = tv.title;
    const w = this.shadowRoot.getElementById('w');
    w.innerHTML = '';
    const card = document.createElement('cleanyourtv-remote');
    card.setConfig({ entity: tv.entity_id, plain: true });
    card.closeAction = () => this._leave(); // the ✕ in the remote's top bar: back
    w.appendChild(card);
    card.hass = this._hass;
    this._card = card;
    this._fit();
  }
}

if (!customElements.get('cleanyourtv-panel')) customElements.define('cleanyourtv-panel', CleanYourTVPanel);
