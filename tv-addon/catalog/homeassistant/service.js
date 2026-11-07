// Home Assistant: the TV tells Home Assistant what it is doing, the moment it changes, and Home Assistant controls the TV.
// The integration (custom_components/cleanyourtv in this repository) finds the TV by itself (LG's SSDP announcement, then /api/hello) and
// pairs once: while "Pair Home Assistant" is open on this add-on's page (three minutes, like the button of a Hue bridge), or at any time
// when "Pair without asking" is on. Then:
//   GET  /api/hello                   no token: {service: 'cleanyourtv-homeassistant', version, open, mac, model} (open: it would pair now)
//   POST /api/pair {name}             -> {token, name}
//   GET  /api/state?since=<seq>       waits (up to 25 s) until something changed after <seq>, then answers the whole state:
//                                     {seq, power, app, media: {state, appId}, volume: {level, max, mute, output}, live, name}
//   POST /api/action {t, ...}         key, text, del, enter, move, click, scroll, launch, live, tvpower, volume, mute
//   GET  /api/apps | /api/inputs | /api/channels | /api/logo/<number> | /api/icon/<app id>
//   POST /api/unpair                  Home Assistant forgets this TV: its token stops working
// Every call but /api/hello and /api/pair carries "Authorization: Bearer <token>". The LAN listener (port 8801) runs while the add-on is on.
// The add-on's own page (index.html) asks, through the loader at /api/addons/homeassistant:
//   GET /status        the pairing window, "pair without asking", the paired Home Assistants, what the TV reports now
//   POST /pair         opens the pairing window (three minutes); POST /pair {stop:true} closes it
//   POST /trust {on}   "Pair without asking": every Home Assistant on the network may pair (off by default)
//   POST /revoke {id}  forgets one Home Assistant ({all:true}: every one)
// What the TV reports comes from LG's own services, followed with luna-send subscriptions while a Home Assistant asked in the last two
// minutes: the app in front (applicationManager), whether its video plays or is paused (com.webos.media: every app that plays through
// the TV's media pipeline, also Netflix and Live TV), the volume (audio) and the power state (tvpower). Checked on an LG 65UP77006LB
// (webOS 6.5.3): playState "playing" for Live TV in Home and "paused" for Netflix.
// Live TV: when Home plays a stream, the stream's address is matched against the playlist (on the TV only: the address can hold the
// provider's key and is never sent), which gives the channel's number, name, group and the programme from the guide.
// remotekeys.js and ws.js are the Phone remote add-on's (by Edenik, MIT), copied so this add-on works without it.
'use strict';
const http = require('http'),
  crypto = require('crypto'),
  spawn = require('child_process').spawn,
  nodeUrl = require('url');

const PORT = 8801, // after the Phone remote (8799) and the page that adds a repository (8800)
  PAIR_MS = 3 * 60 * 1000,
  MAX_CLIENTS = 5,
  WAIT_MS = 25000, // a long poll answers after this long even when nothing changed
  ACTIVE_MS = 2 * 60 * 1000, // the TV is followed while a Home Assistant asked this recently
  TRIES = 5, // pairing tries per address per minute
  LIST_MS = 60000, // the playlist (for matching a stream) is read again after this long
  RATE = { burst: 80, perSecond: 50 }; // actions a client may send (the card's touchpad moves the pointer many times a second)
const TOKEN = /^([0-9a-f]{8})\.([0-9a-f]{32})$/;
const SUBS = {
  app: ['luna://com.webos.applicationManager/getForegroundAppInfo', { subscribe: true }],
  media: ['luna://com.webos.media/getForegroundAppInfo', { subscribe: true }],
  volume: ['luna://com.webos.service.audio/master/getVolume', { subscribe: true }],
  power: ['luna://com.webos.service.tvpower/power/getPowerState', { subscribe: true }],
};
const POWER = {
  off: { m: 'turnOffScreen', a: {} },
  on: { m: 'turnOnScreen', a: {} },
  standby: { m: 'powerOff', a: { reason: 'remoteKey' } },
  reboot: { m: 'reboot', a: { reason: 'remoteKey' } },
  shutdown: { m: 'shutDown', a: { reason: 'remoteKey' } },
};
const HOME = 'com.webos.app.home';
const VERSION = (() => {
  try {
    return require('./addon.json').version;
  } catch (_) {
    return '';
  }
})();

const sha = s => crypto.createHash('sha256').update(String(s)).digest();
const same = (a, b) => crypto.timingSafeEqual(sha(a), sha(b));
const cleanName = n =>
  String(n || '')
    .replace(/[\u0000-\u001f\u007f<>"&]/g, '')
    .trim()
    .slice(0, 40) || 'Home Assistant';
const json = (res, o, code) => {
  res.writeHead(code || 200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
  res.end(JSON.stringify(o));
};
function readBody(req) {
  return new Promise(resolve => {
    let b = '',
      big = false;
    req.on('data', c => {
      if (big) return;
      b += c;
      if (b.length > 8192) big = true;
    });
    req.on('end', () => {
      if (big) return resolve({});
      try {
        resolve(JSON.parse(b || '{}'));
      } catch (_) {
        resolve({});
      }
    });
    req.on('error', () => resolve({}));
  });
}

// One luna-send subscription, started again when it ends (backing off to a minute while it keeps failing). Each JSON line goes to onMsg.
function subscribe(uri, payload, onMsg) {
  let proc = null,
    stopped = false,
    delay = 2000,
    timer = null;
  function run() {
    if (stopped) return;
    let buf = '';
    try {
      proc = spawn('luna-send', ['-i', uri, JSON.stringify(payload)], { stdio: ['pipe', 'pipe', 'ignore'] });
    } catch (_) {
      return again();
    }
    proc.stdout.on('data', d => {
      delay = 2000;
      buf += d.toString('utf8');
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const l of lines) {
        if (l.indexOf('{') < 0) continue;
        try {
          onMsg(JSON.parse(l.slice(l.indexOf('{'))));
        } catch (_) {}
      }
    });
    proc.on('error', again);
    proc.on('close', again);
  }
  function again() {
    proc = null;
    if (stopped || timer) return;
    timer = setTimeout(() => {
      timer = null;
      run();
    }, delay);
    if (timer.unref) timer.unref();
    delay = Math.min(delay * 2, 60000);
  }
  run();
  return () => {
    stopped = true;
    clearTimeout(timer);
    if (proc)
      try {
        proc.kill();
      } catch (_) {}
  };
}

// opts (tests): port (0 = any), host, keys, subscribe, api (the service's loopback address), lanIp
function create(ctx, opts) {
  const o = opts || {};
  const API = String(o.api || 'http://127.0.0.1:8765');
  const L = ctx.luna || (() => Promise.resolve({ returnValue: false }));
  const sub = o.subscribe || subscribe;
  const lanIp = o.lanIp || (ctx.util && ctx.util.lanIp) || (() => '');
  let keys = o.keys || null; // made on first use: it may ask the TV for its control socket
  const getKeys = () => keys || (keys = require('./remotekeys').create(ctx));

  const settings = () => Object.assign({ clients: [] }, ctx.settings.get());
  const save = fn => {
    const s = settings();
    s.clients = (s.clients || []).slice();
    fn(s);
    ctx.settings.set({ clients: s.clients });
  };
  const find = id => settings().clients.filter(c => c.id === id)[0] || null;

  // ---- what the TV reports ----
  const state = { seq: 1, power: '', app: '', media: { state: '', appId: '' }, volume: null, live: null };
  const waiters = [];
  function changed() {
    state.seq++;
    waiters.splice(0).forEach(w => w());
  }
  function set(key, v) {
    if (JSON.stringify(state[key]) === JSON.stringify(v)) return;
    state[key] = v;
    changed();
  }
  let stops = [],
    lastAsked = 0,
    idleTimer = null;
  function follow() {
    lastAsked = Date.now();
    if (!stops.length) {
      stops = [
        sub(SUBS.app[0], SUBS.app[1], m => {
          if (typeof m.appId === 'string') set('app', m.appId);
        }),
        sub(SUBS.media[0], SUBS.media[1], m => {
          if (!Array.isArray(m.foregroundAppInfo)) return;
          const f = m.foregroundAppInfo.filter(x => x && x.type === 'media')[0] || null;
          set('media', { state: f ? String(f.playState || '') : '', appId: f ? String(f.appId || '') : '' });
          matchLive();
        }),
        sub(SUBS.volume[0], SUBS.volume[1], m => {
          const v = m.volumeStatus || m;
          if (typeof v.volume !== 'number' && typeof v.muteStatus !== 'boolean') return;
          const cur = state.volume || {};
          set('volume', {
            level: typeof v.volume === 'number' ? v.volume : cur.level,
            max: typeof v.maxVolume === 'number' ? v.maxVolume : cur.max || 100,
            mute: typeof v.muteStatus === 'boolean' ? v.muteStatus : !!cur.mute,
            output: String(v.soundOutput || cur.output || ''),
          });
        }),
        sub(SUBS.power[0], SUBS.power[1], m => {
          if (typeof m.state === 'string') set('power', m.state);
        }),
      ];
    }
    if (!idleTimer) {
      idleTimer = setInterval(() => {
        if (Date.now() - lastAsked > ACTIVE_MS && !waiters.length) return unfollow();
        if (state.media.appId === HOME) matchLive(); // the programme of the guide moves on while the channel stays
      }, 30000);
      if (idleTimer.unref) idleTimer.unref();
    }
  }
  function unfollow() {
    stops.forEach(s => s());
    stops = [];
    clearInterval(idleTimer);
    idleTimer = null;
    // what is not followed is not known: the next client starts from what the subscriptions say first
    state.power = '';
    state.app = '';
    state.media = { state: '', appId: '' };
    state.volume = null;
    state.live = null;
  }

  // ---- Live TV: which channel plays ----
  let playlist = null,
    playlistAt = 0;
  async function channels() {
    if (playlist && Date.now() - playlistAt < LIST_MS) return playlist;
    const r = await apiGet('/api/live/channels');
    playlist = Array.isArray(r.channels) ? r.channels : [];
    playlistAt = Date.now();
    return playlist;
  }
  let matching = 0;
  async function matchLive() {
    const my = ++matching;
    if (state.media.appId !== HOME || !state.media.state) return set('live', null);
    let uri = '';
    try {
      const r = await L('luna://com.webos.media/getActivePipelines', {}, { wait: 3000 });
      const list = Array.isArray(r) ? r : Array.isArray(r && r.pipelines) ? r.pipelines : [];
      const p = list.filter(x => x && x.type === 'media' && x.appId === HOME && x.is_foreground && x.uri)[0];
      uri = p ? String(p.uri) : '';
    } catch (_) {}
    if (my !== matching) return;
    if (!uri) return set('live', null);
    const list = await channels();
    let c = list.filter(ch => ch[5] === uri || (Array.isArray(ch[12]) && ch[12].some(a => a && a[0] === uri)))[0];
    if (!c) {
      // a stream that is not the playlist's address as it is (a redirect, a variant): the channel Live TV marked as played last
      const st = await apiGet('/api/live/state');
      const k = Array.isArray(st.recent) ? st.recent[0] : '';
      c = k ? list.filter(ch => ch[6] === k)[0] : null;
    }
    if (my !== matching) return;
    if (!c) return set('live', null);
    const live = { num: c[0], name: String(c[2] || ''), group: String(c[3] || ''), logo: /^https?:\/\//i.test(String(c[4] || '')) };
    const g = await apiGet('/api/live/epg?ids=' + encodeURIComponent(String(c[1] || '')));
    const e = g && g[c[1]] && g[c[1]].now;
    if (e) live.programme = { start: e[0], end: e[1], title: String(e[2] || ''), description: String(e[3] || '').slice(0, 500) };
    if (my === matching) set('live', live);
  }

  // ---- the service's loopback API ----
  function apiRequest(method, path, body) {
    return new Promise(resolve => {
      let done = false;
      const settle = v => {
        if (!done) {
          done = true;
          resolve(v || {});
        }
      };
      try {
        const u = nodeUrl.parse(API + path);
        const payload = body ? JSON.stringify(body) : '';
        const r = http.request(
          {
            hostname: u.hostname,
            port: u.port,
            path: u.path,
            method,
            headers: payload ? { 'content-type': 'application/json', 'content-length': Buffer.byteLength(payload) } : {},
          },
          s => {
            let d = '';
            s.on('data', c => (d += c));
            s.on('end', () => {
              try {
                settle(JSON.parse(d || '{}'));
              } catch (_) {
                settle({});
              }
            });
            s.on('error', () => settle({}));
            s.on('aborted', () => settle({}));
          }
        );
        r.on('error', () => settle({}));
        r.setTimeout(8000, () => {
          r.destroy();
          settle({});
        });
        r.end(payload);
      } catch (_) {
        settle({});
      }
    });
  }
  const apiGet = path => apiRequest('GET', path);
  function pipe(res, path) {
    try {
      const u = nodeUrl.parse(API + path);
      http
        .get({ hostname: u.hostname, port: u.port, path: u.path }, r => {
          if (r.statusCode !== 200) {
            r.resume();
            return json(res, { error: 'not found' }, 404);
          }
          res.writeHead(200, { 'content-type': r.headers['content-type'] || 'image/png', 'cache-control': 'max-age=3600' });
          r.pipe(res);
        })
        .on('error', () => json(res, { error: 'not found' }, 404));
    } catch (_) {
      json(res, { error: 'not found' }, 404);
    }
  }

  // ---- actions ----
  const ok = r => ({ ok: !!r && r.returnValue !== false, error: (r && r.errorText) || '' });
  const ACTIONS = {
    key: m => getKeys().press(String(m.k || '').toUpperCase()),
    text: m => getKeys().text(String(m.s || '')),
    del: m => getKeys().del(m.c),
    enter: () => getKeys().enter(),
    move: m => getKeys().move(m.dx, m.dy),
    click: () => getKeys().click(),
    scroll: m => getKeys().scroll(m.dy),
    launch: async m => {
      const id = String(m.id || '');
      if (!/^[\w.\-]+$/.test(id)) return { ok: false, error: 'bad app' };
      return ok(await apiRequest('POST', '/api/launch', { id }));
    },
    live: async m => {
      // Live TV in Home on that channel: Home opens Live TV, then the number is pressed, as Live TV takes a number from the remote
      const num = parseInt(m.num, 10);
      if (!(num >= 1 && num <= 99999)) return { ok: false, error: 'bad channel' };
      const r = await apiRequest('POST', '/api/launch', { id: HOME, params: { live: true } });
      if (r.returnValue) {
        const t = setTimeout(
          async () => {
            for (const d of String(num).split('')) {
              await getKeys().press(d);
              await new Promise(z => setTimeout(z, 150));
            }
          },
          o.liveWaitMs === undefined ? 3500 : o.liveWaitMs
        );
        if (t.unref) t.unref();
      }
      return ok(r);
    },
    // Live TV, where a playlist is added (the remote card's Live tab when there is none yet)
    liveSetup: async () => ok(await apiRequest('POST', '/api/launch', { id: HOME, params: { live: true } })),
    tvpower: async m => {
      const c = POWER[String(m.a || '')];
      if (!c) return { ok: false, error: 'bad action' };
      return ok(await L('luna://com.webos.service.tvpower/power/' + c.m, c.a, { wait: 5000 }));
    },
    volume: async m => {
      const v = Math.round(Number(m.level));
      if (!(v >= 0 && v <= 100)) return { ok: false, error: 'bad volume' };
      return ok(await L('luna://com.webos.service.audio/master/setVolume', { volume: v }, { wait: 3000 }));
    },
    // master/muteVolume {mute} on webOS 6.5 (checked on an LG 65UP77006LB; it has no setMute); setMuted {muted} on others
    mute: async m => {
      const r = await L('luna://com.webos.service.audio/master/muteVolume', { mute: !!m.on }, { wait: 3000 });
      if (r && r.returnValue !== false) return ok(r);
      return ok(await L('luna://com.webos.service.audio/master/setMuted', { muted: !!m.on }, { wait: 3000 }));
    },
  };

  // ---- pairing and tokens ----
  let pair = null; // {until, timer}: the pairing window
  const tries = {};
  const trusted = () => settings().trust === true;
  const open = () => !!pair || trusted();
  function openPair() {
    if (!pair) pair = { timer: null };
    pair.until = Date.now() + PAIR_MS;
    clearTimeout(pair.timer);
    pair.timer = setTimeout(closePair, PAIR_MS);
    if (pair.timer.unref) pair.timer.unref();
    sync();
  }
  function closePair() {
    if (!pair) return;
    clearTimeout(pair.timer);
    pair = null;
    sync();
  }
  function tryPair(addr, b) {
    const now = Date.now();
    const t = (tries[addr] || []).filter(x => now - x < 60000);
    if (t.length >= TRIES) return [429, { error: 'Too many tries. Wait a minute.' }];
    t.push(now);
    tries[addr] = t;
    if (!open())
      return [403, { error: 'The TV is not waiting. On the TV open the Home Assistant page and choose Pair Home Assistant.', reason: 'not_waiting' }];
    if (settings().clients.length >= MAX_CLIENTS) return [409, { error: 'Too many Home Assistants are paired. Remove one on the TV.' }];
    const id = crypto.randomBytes(4).toString('hex'),
      secret = crypto.randomBytes(16).toString('hex'),
      name = cleanName(b.name);
    save(s => s.clients.push({ id, name, hash: sha(secret).toString('hex'), created: now, seen: now, addr }));
    closePair(); // one Home Assistant per press, as with a Hue bridge
    console.log('homeassistant: ' + id + ' paired');
    return [200, { token: id + '.' + secret, name }];
  }
  // the client of a request with a good token, or null
  function client(req) {
    const h = String(req.headers.authorization || '');
    const m = TOKEN.exec(h.replace(/^Bearer\s+/i, '').trim());
    const c = m && find(m[1]);
    if (!c || !same(sha(m[2]).toString('hex'), c.hash)) return null;
    if (Date.now() - (c.seen || 0) > 60000)
      save(s => {
        const x = s.clients.filter(y => y.id === c.id)[0];
        if (x) x.seen = Date.now();
      });
    return c;
  }
  const bucket = {};
  function allowed(id) {
    const now = Date.now(),
      b = bucket[id] || (bucket[id] = { n: RATE.burst, at: now });
    b.n = Math.min(RATE.burst, b.n + ((now - b.at) / 1000) * RATE.perSecond);
    b.at = now;
    if (b.n < 1) return false;
    b.n--;
    return true;
  }

  // ---- the LAN listener ----
  // It listens while the add-on is on (switching the add-on off in Add-ons stops it): also with no Home Assistant paired, so that one the
  // TV removed hears 401 and asks to pair again, instead of finding nothing there. Every call but /api/pair needs a token.
  let srv = null,
    running = false;
  function sync() {
    if (running && !srv) {
      srv = http.createServer(onRequest);
      srv.on('error', e => {
        console.log('homeassistant: port ' + PORT + ': ' + e.message);
        srv = null;
      });
      srv.listen(o.port === undefined ? PORT : o.port, o.host || '0.0.0.0');
    } else if (!running && srv) {
      srv.close();
      srv = null;
    }
    if (!settings().clients.length) unfollow();
  }
  // the port is listening (or failed) by the time the page is answered
  const listening = () =>
    new Promise(resolve => {
      if (!srv || srv.listening) return resolve();
      const t = setTimeout(resolve, 1000);
      srv.once('listening', () => {
        clearTimeout(t);
        resolve();
      });
    });
  // the TV itself, for Home Assistant's device: the MAC address that Wake-on-LAN needs (the interface that is up) and the model
  let tv = null;
  async function tvInfo() {
    if (tv) return tv;
    const fs = require('fs');
    const found = [];
    ['eth0', 'wlan0'].forEach(n => {
      try {
        const a = fs.readFileSync((o.sysNet || '/sys/class/net') + '/' + n + '/address', 'utf8').trim();
        const up = fs.readFileSync((o.sysNet || '/sys/class/net') + '/' + n + '/operstate', 'utf8').trim() === 'up';
        if (/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(a) && a !== '00:00:00:00:00:00') found.push({ a: a.toUpperCase(), up });
      } catch (_) {}
    });
    const pick = found.filter(f => f.up)[0] || found[0];
    let model = '';
    try {
      const r = await L('luna://com.webos.service.tv.systemproperty/getSystemInfo', { keys: ['modelName', 'firmwareVersion'] }, { wait: 3000 });
      model = r && typeof r.modelName === 'string' ? r.modelName : '';
    } catch (_) {}
    tv = { mac: pick ? pick.a : '', model };
    return tv;
  }
  const pub = () => ({
    seq: state.seq,
    tv: tv || { mac: '', model: '' },
    power: state.power,
    app: state.app,
    media: state.media,
    volume: state.volume,
    live: state.live,
  });

  function onRequest(req, res) {
    const u = req.url.split('?')[0],
      q = req.url.split('?')[1] || '';
    const addr = String((req.socket && req.socket.remoteAddress) || '');
    if (req.headers.origin) return json(res, { error: 'forbidden' }, 403); // not for web pages: only Home Assistant calls this
    // what Home Assistant's discovery asks: is the add-on here, would it pair now, and which TV it is (the MAC is no secret on the LAN)
    if (req.method === 'GET' && u === '/api/hello')
      return tvInfo().then(i => json(res, { service: 'cleanyourtv-homeassistant', version: VERSION, open: open(), mac: i.mac, model: i.model }));
    if (req.method === 'POST' && u === '/api/pair')
      return readBody(req).then(b => {
        const r = tryPair(addr, b);
        json(res, r[1], r[0]);
      });
    const c = client(req);
    if (!c) return json(res, { error: 'unauthorized' }, 401);
    if (req.method === 'GET' && u === '/api/state') {
      follow();
      if (!tv) return tvInfo().then(() => json(res, pub()));
      const m = /(?:^|&)since=(\d+)/.exec(q);
      const since = m ? parseInt(m[1], 10) : 0;
      if (state.seq > since) return json(res, pub());
      let done = false;
      const answer = () => {
        if (done) return;
        done = true;
        clearTimeout(t);
        const i = waiters.indexOf(answer);
        if (i >= 0) waiters.splice(i, 1);
        try {
          json(res, pub());
        } catch (_) {}
      };
      const t = setTimeout(answer, o.waitMs || WAIT_MS);
      waiters.push(answer);
      res.on('close', () => {
        done = true;
        clearTimeout(t);
        const i = waiters.indexOf(answer);
        if (i >= 0) waiters.splice(i, 1);
      });
      return;
    }
    if (req.method === 'POST' && u === '/api/action')
      return readBody(req).then(async m => {
        const act = ACTIONS[m.t];
        if (!act) return json(res, { ok: false, error: 'unknown action' }, 400);
        if (!allowed(c.id)) return json(res, { ok: false, error: 'slow down' }, 429);
        let r;
        try {
          r = (await act(m)) || { ok: false, error: 'no answer' };
        } catch (e) {
          r = { ok: false, error: String((e && e.message) || e).slice(0, 160) };
        }
        json(res, { ok: !!r.ok, error: r.ok ? '' : r.error || 'failed' });
      });
    if (req.method === 'POST' && u === '/api/unpair') {
      save(s => {
        s.clients = s.clients.filter(x => x.id !== c.id);
      });
      json(res, { ok: true });
      return setTimeout(sync, 100);
    }
    if (req.method === 'GET' && u === '/api/apps')
      return apiGet('/api/apps').then(r =>
        json(res, {
          apps: (Array.isArray(r.apps) ? r.apps : []).filter(a => a && a.id && a.title).map(a => ({ id: String(a.id), title: String(a.title) })),
        })
      );
    if (req.method === 'GET' && u === '/api/inputs')
      return apiGet('/api/inputs').then(r =>
        json(res, {
          inputs: (Array.isArray(r.devices) ? r.devices : [])
            .filter(d => d && (d.appId || d.id))
            .map(d => ({ appId: String(d.appId || d.id), title: String(d.label || (d.port ? 'HDMI ' + d.port : '')), off: d.hdmiPlugIn === false })),
        })
      );
    if (req.method === 'GET' && u === '/api/channels')
      return channels().then(list =>
        json(res, {
          channels: list
            .map(ch => ({ num: parseInt(ch[0], 10) || 0, name: String(ch[2] || ''), group: String(ch[3] || ''), logo: /^https?:\/\//i.test(String(ch[4] || '')) }))
            .filter(ch => ch.num > 0 && ch.name),
        })
      );
    if (req.method === 'GET' && u.indexOf('/api/logo/') === 0) {
      const n = parseInt(u.slice('/api/logo/'.length), 10);
      return channels().then(list => {
        const ch = list.filter(x => parseInt(x[0], 10) === n)[0];
        if (!ch || !/^https?:\/\//i.test(String(ch[4] || ''))) return json(res, { error: 'no logo' }, 404);
        fetchLogo(String(ch[4]), res);
      });
    }
    if (req.method === 'GET' && u.indexOf('/api/icon/') === 0) {
      const id = u.slice('/api/icon/'.length);
      if (!/^[\w.\-]+$/.test(id)) return json(res, { error: 'not found' }, 404);
      return pipe(res, '/icon/' + encodeURIComponent(id));
    }
    json(res, { error: 'not found' }, 404);
  }

  // a channel logo, fetched by the TV (the playlist's address stays here): at most 512 KB, 5 seconds, two redirects
  function fetchLogo(address, res, hops) {
    let finished = false;
    const fail = () => {
      if (finished) return;
      finished = true;
      json(res, { error: 'no logo' }, 404);
    };
    try {
      const lib = address.indexOf('https:') === 0 ? require('https') : http;
      const u = nodeUrl.parse(address);
      const r = lib.get({ protocol: u.protocol, hostname: u.hostname, port: u.port, path: u.path }, s => {
        if ([301, 302, 303, 307, 308].indexOf(s.statusCode) >= 0 && s.headers.location && (hops || 0) < 2) {
          s.resume();
          finished = true;
          const next = nodeUrl.resolve(address, String(s.headers.location));
          return /^https?:\/\//i.test(next) ? fetchLogo(next, res, (hops || 0) + 1) : json(res, { error: 'no logo' }, 404);
        }
        if (s.statusCode !== 200) {
          s.resume();
          return fail();
        }
        const chunks = [];
        let size = 0;
        s.on('data', d => {
          size += d.length;
          if (size > 512 * 1024) {
            r.destroy();
            return fail();
          }
          chunks.push(d);
        });
        s.on('end', () => {
          if (finished) return;
          finished = true;
          res.writeHead(200, { 'content-type': s.headers['content-type'] || 'image/png', 'cache-control': 'max-age=3600' });
          res.end(Buffer.concat(chunks));
        });
        s.on('error', fail);
      });
      r.on('error', fail);
      r.setTimeout(5000, () => {
        r.destroy();
        fail();
      });
    } catch (_) {
      fail();
    }
  }

  // ---- the add-on's own page (through the loader) ----
  async function handle(req, res, path, body) {
    const read = () => (body ? body(req) : readBody(req));
    const u = path || '/';
    if (u === '/status' && req.method === 'GET')
      return json(res, {
        listening: !!(srv && srv.listening),
        address: lanIp() ? lanIp() + ':' + PORT : '',
        pairing: pair ? { until: pair.until } : null,
        trust: trusted(),
        clients: settings().clients.map(c => ({ id: c.id, name: c.name, created: c.created, seen: c.seen, addr: c.addr || '' })),
        now: pub(),
      });
    if (u === '/pair' && req.method === 'POST') {
      const b = (await read()) || {};
      if (b.stop) closePair();
      else openPair();
      await listening();
      return json(res, { pairing: pair ? { until: pair.until } : null });
    }
    if (u === '/trust' && req.method === 'POST') {
      const b = (await read()) || {};
      ctx.settings.set({ trust: b.on === true });
      return json(res, { trust: trusted() });
    }
    if (u === '/revoke' && req.method === 'POST') {
      const b = (await read()) || {};
      save(s => {
        s.clients = b.all ? [] : s.clients.filter(c => c.id !== b.id);
      });
      sync();
      return json(res, { ok: true });
    }
    json(res, { error: 'not found' }, 404);
  }

  return {
    handle,
    start() {
      running = true;
      sync();
    },
    stop() {
      running = false;
      closePair();
      sync();
      unfollow();
      waiters.splice(0).forEach(w => w());
      if (keys) keys.close();
    },
    address: () => (srv && srv.address()) || null,
    state: pub,
  };
}

module.exports = { create, subscribe, PORT };
