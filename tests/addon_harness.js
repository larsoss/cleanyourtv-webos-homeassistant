// Runs the TV add-on (tv-addon/catalog/homeassistant/service.js) on this computer, without a TV: luna, its subscriptions, the keys and the
// launcher's API are fakes. The Python tests talk to it as the integration talks to the TV.
// Usage: node addon_harness.js            (stdout: one JSON line per event; stdin: one command per line)
//   pair                       opens the pairing window ("Pair Home Assistant" on the TV): {"ev":"open"}
//   close                      closes it; trust on|off: "Pair without asking"
//   app <id> | media <appId> <playState> | volume <level> <mute> | power <state> | pipeline <uri>
//   revoke                     forgets every paired Home Assistant
'use strict';
const path = require('path'),
  http = require('http'),
  os = require('os'),
  readline = require('readline');
const HA = require(path.join(__dirname, '..', 'tv-addon', 'catalog', 'homeassistant', 'service.js'));
const say = o => process.stdout.write(JSON.stringify(o) + '\n');

let settings = {};
const store = { get: () => Object.assign({}, settings), set: o => (settings = Object.assign({}, settings, o)) };
const subs = {}; // uri -> onMsg
let pipelineUri = '';
const luna = (uri, params) => {
  say({ ev: 'luna', uri, params });
  if (/getActivePipelines$/.test(uri))
    return Promise.resolve(pipelineUri ? [{ type: 'media', appId: 'com.webos.app.home', is_foreground: true, uri: pipelineUri }] : []);
  return Promise.resolve({ returnValue: true });
};
const ack = () => Promise.resolve({ ok: true });
const keys = {
  press: k => (say({ ev: 'key', k }), ack()),
  move: (dx, dy) => (say({ ev: 'move', dx, dy }), ack()),
  click: () => (say({ ev: 'click' }), ack()),
  scroll: dy => (say({ ev: 'scroll', dy }), ack()),
  text: s => (say({ ev: 'text', s }), ack()),
  del: c => (say({ ev: 'del', c }), ack()),
  enter: () => (say({ ev: 'enter' }), ack()),
  close: () => {},
};
const subscribe = (uri, payload, onMsg) => {
  subs[uri] = onMsg;
  say({ ev: 'subscribe', uri });
  return () => {
    delete subs[uri];
    say({ ev: 'unsubscribe', uri });
  };
};
const send = (part, msg) => {
  const uri = Object.keys(subs).filter(u => u.indexOf(part) >= 0)[0];
  if (uri) subs[uri](msg);
  else say({ ev: 'not-subscribed', part });
};
const CH = [
  [1, 'npo1.nl', 'NPO 1', 'NL', 'http://127.0.0.1:1/none.png', 'http://iptv.example/live/user/pass/1.ts', 'key1', '', '', '', 0, [], []],
  [24, 'f1.nl', 'Viaplay F1', 'Sport', '', 'http://iptv.example/live/user/pass/24.ts', 'key24', '', '', '', 0, [], []],
];
const api = http.createServer((req, res) => {
  let b = '';
  req.on('data', d => (b += d));
  req.on('end', () => {
    const j = o => {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(o));
    };
    const u = req.url;
    if (u === '/api/apps') return j({ apps: [{ id: 'netflix', title: 'Netflix' }, { id: 'youtube.leanback.v4', title: 'YouTube' }] });
    if (u === '/api/inputs') return j({ devices: [{ appId: 'com.webos.app.hdmi1', label: 'HDMI 1', port: 1 }] });
    if (u === '/api/live/channels') return j({ channels: CH });
    if (u === '/api/live/state') return j({ fav: [], recent: ['key1'], failed: {} });
    if (u.indexOf('/api/live/epg') === 0) {
      const now = Math.floor(Date.now() / 1000);
      return j(/f1\.nl/.test(u) ? { 'f1.nl': { now: [now - 60, now + 3600, 'F1 Kwalificatie', 'Brazilië'], next: null } } : {});
    }
    if (u === '/api/launch') {
      say({ ev: 'launch', body: JSON.parse(b || '{}') });
      return j({ returnValue: true });
    }
    if (u.indexOf('/icon/') === 0) {
      res.writeHead(200, { 'content-type': 'image/png' });
      return res.end('PNG');
    }
    res.writeHead(404);
    res.end();
  });
});
api.listen(0, '127.0.0.1', async () => {
  const ha = HA.create(
    { settings: store, dataDir: os.tmpdir(), luna, util: { lanIp: () => '127.0.0.1' }, log: () => {} },
    { port: 0, host: '127.0.0.1', keys, luna, subscribe, api: 'http://127.0.0.1:' + api.address().port, liveWaitMs: 50, waitMs: 3000 }
  );
  ha.start();
  const call = (p, body) =>
    new Promise(resolve => {
      const res = {
        writeHead() {},
        end(t) {
          resolve(JSON.parse(t));
        },
      };
      ha.handle({ method: body ? 'POST' : 'GET', headers: {} }, res, p, async () => body || {});
    });
  if (process.argv.indexOf('--closed') < 0) await call('/pair', {});
  else await call('/pair', { stop: true });
  say({ ev: 'listening', port: ha.address().port });
  readline.createInterface({ input: process.stdin }).on('line', async line => {
    const a = line.trim().split(' ');
    const cmd = a[0];
    if (cmd === 'pair') say({ ev: 'open', pairing: (await call('/pair', {})).pairing });
    else if (cmd === 'close') say({ ev: 'closed', pairing: (await call('/pair', { stop: true })).pairing });
    else if (cmd === 'trust') say({ ev: 'trust', trust: (await call('/trust', { on: a[1] === 'on' })).trust });
    else if (cmd === 'app') send('applicationManager', { appId: a[1] });
    else if (cmd === 'media') send('com.webos.media', { foregroundAppInfo: [{ appId: a[1], type: 'media', playState: a[2] }] });
    else if (cmd === 'volume') send('audio', { volumeStatus: { volume: +a[1], muteStatus: a[2] === 'true', maxVolume: 100 } });
    else if (cmd === 'power') send('tvpower', { state: a.slice(1).join(' ') });
    else if (cmd === 'pipeline') pipelineUri = a[1] || '';
    else if (cmd === 'revoke') {
      await call('/revoke', { all: true });
      say({ ev: 'revoked' });
    } else if (cmd === 'status') say({ ev: 'status', status: await call('/status') });
  });
});
