/* Runs in the card's frame before the Phone remote's own script (tools/build-card.js puts it there). The page was written for a
   WebSocket to the TV; here the WebSocket and the three list requests are answered by the card (window.frameElement.__cytv), which asks
   Home Assistant, which asks the TV. Everything else is the Phone remote's page as it is. */
(function () {
  var B = window.frameElement && window.frameElement.__cytv;
  if (!B) return;
  try {
    localStorage.setItem('cytv-remote', B.secret); /* the page is "paired": the pairing is Home Assistant's own */
    if (B.model) localStorage.setItem('cytv-tvname', B.model);
  } catch (e) {}
  /* light or dark, as Home Assistant's theme (the card sets it again when the theme changes) */
  if (B.dark && !B.dark()) document.documentElement.classList.add('light');
  else document.documentElement.classList.add('dark');
  /* the close button: in the top bar, beside the power button and in its style, when the card is closable (a popup, the remote page) */
  var cyx = null;
  window.CYTV_CLOSE = function (show) {
    if (cyx) cyx.style.display = show ? '' : 'none';
  };
  document.addEventListener('DOMContentLoaded', function () {
    var pwr = document.getElementById('pwr');
    if (!pwr || !B.close) return;
    cyx = document.createElement('button');
    cyx.id = 'cyx';
    cyx.className = 'info';
    cyx.setAttribute('aria-label', 'Close');
    cyx.innerHTML = '<svg class=ic viewBox="0 0 24 24" aria-hidden=true><path d="M18 6 6 18M6 6l12 12"/></svg>';
    cyx.addEventListener('click', function () { B.close(); });
    pwr.parentNode.insertBefore(cyx, pwr);
    window.CYTV_CLOSE(B.closable && B.closable());
  });
  window.CYTV_PIC = B.pic; /* pictures: /api/cleanyourtv/<entry>/... (the build puts it in front of the page's own paths) */
  /* the wrapper of an app, as far as this page needs one: Home Assistant wakes the TV (Wake-on-LAN or the screen back on) */
  window.CYTV_APP = {
    wake: function () { B.wake(); return true; },
    deviceName: function () { return 'Home Assistant'; },
    up: function () { return B.connected(); },
    /* a key press: in the Home Assistant Companion app (iPhone and Android) the app's own haptics, which the frontend passes on from a
       "haptic" event on its window (iOS has no navigator.vibrate, and a switch tick needs the finger on the switch); in a browser,
       navigator.vibrate where there is one */
    buzz: function () {
      try {
        var W = window.frameElement.ownerDocument.defaultView;
        if (W.externalApp || (W.webkit && W.webkit.messageHandlers && W.webkit.messageHandlers.externalBus)) {
          W.dispatchEvent(new W.CustomEvent('haptic', { detail: 'light' }));
          return;
        }
      } catch (e) {}
      try { if (navigator.vibrate) navigator.vibrate(8); } catch (e) {}
    }
  };
  var socks = [];
  function FakeWS() {
    var w = this;
    w.readyState = 0;
    socks.push(w);
    setTimeout(function () {
      if (!B.connected()) { w.readyState = 3; if (w.onclose) w.onclose({ code: 1006 }); return; }
      w.readyState = 1;
      if (w.onopen) w.onopen({});
    }, 30);
  }
  FakeWS.prototype.reply = function (o) {
    var w = this;
    if (w.readyState !== 1) return;
    setTimeout(function () { if (w.readyState === 1 && w.onmessage) w.onmessage({ data: JSON.stringify(o) }); }, 0);
  };
  FakeWS.prototype.send = function (text) {
    var w = this, m;
    try { m = JSON.parse(text); } catch (e) { return; }
    if (m.t === 'hello') return w.reply({ t: 'ready', name: 'Home Assistant', tv: B.model, keys: B.keys, mac: B.mac, wol: true, seen: 0, created: 0 });
    if (m.t === 'ping') return w.reply({ t: 'pong' });
    if (m.t === 'power') return w.reply({ t: 'power', state: B.power() });
    if (m.t === 'logout') return w.reply({ t: 'ack', n: m.n, ok: false, e: 'Remove the TV in Home Assistant instead' });
    B.action(m).then(function (r) {
      if (m.n !== undefined) w.reply({ t: 'ack', n: m.n, ok: !!(r && r.ok), e: (r && r.error) || '' });
    }, function (e) {
      if (m.n !== undefined) w.reply({ t: 'ack', n: m.n, ok: false, e: String((e && e.message) || e || 'failed') });
    });
  };
  FakeWS.prototype.close = function () {
    if (this.readyState === 3) return;
    this.readyState = 3;
    var i = socks.indexOf(this);
    if (i >= 0) socks.splice(i, 1);
    if (this.onclose) this.onclose({ code: 1000 });
  };
  window.WebSocket = FakeWS;
  /* the card says when Home Assistant's view of the TV changed: a new power state is passed on, a lost TV closes the "socket" */
  B.onChange(function () {
    socks.slice().forEach(function (w) {
      if (!B.connected()) { w.readyState = 3; if (w.onclose) w.onclose({ code: 1006 }); var i = socks.indexOf(w); if (i >= 0) socks.splice(i, 1); }
      else w.reply({ t: 'power', state: B.power() });
    });
  });
  /* the page's three lists */
  var RealXHR = window.XMLHttpRequest;
  function FakeXHR() { this.status = 0; this.responseText = ''; this.readyState = 0; }
  FakeXHR.prototype.open = function (method, url) { this._u = String(url); this._m = method; };
  FakeXHR.prototype.setRequestHeader = function () {};
  FakeXHR.prototype.send = function () {
    var x = this, m = /^\/api\/(apps|inputs|live)\b/.exec(x._u);
    if (!m) { x.status = 404; x.readyState = 4; if (x.onload) setTimeout(function () { x.onload(); }, 0); return; }
    B.list(m[1]).then(function (j) {
      x.status = j && !j.error ? 200 : 503;
      x.responseText = JSON.stringify(j || {});
      x.readyState = 4;
      if (x.onload) x.onload();
    }, function () {
      x.status = 503;
      x.readyState = 4;
      if (x.onerror) x.onerror(); else if (x.onload) x.onload();
    });
  };
  FakeXHR.prototype.abort = function () {};
  window.XMLHttpRequest = FakeXHR;
  window.__RealXHR = RealXHR;
})();
