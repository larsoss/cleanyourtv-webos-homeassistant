// The add-on's manifest as CleanYourTV's loader checks it (needs CYTV_SRC: a cleanyourtv-WebOS checkout), and index.json up to date.
'use strict';
const path = require('path'),
  fs = require('fs'),
  cp = require('child_process');
const root = path.join(__dirname, '..', 'tv-addon');
const m = JSON.parse(fs.readFileSync(path.join(root, 'catalog', 'homeassistant', 'addon.json'), 'utf8'));
let failed = 0;
const ok = (c, what) => {
  console.log((c ? 'ok   ' : 'FAIL ') + what);
  if (!c) failed++;
};
if (process.env.CYTV_SRC) {
  const addons = require(path.join(process.env.CYTV_SRC, 'helper', 'addons.js'));
  const r = addons.check(m, '1.6.20');
  ok(!r.error, 'the loader accepts addon.json' + (r.error ? ': ' + r.error : ''));
}
const idx = cp.spawnSync(process.execPath, [path.join(root, 'make-index.js'), '--check'], { encoding: 'utf8' });
ok(idx.status === 0, 'tv-addon/index.json is up to date (node tv-addon/make-index.js)');
const index = JSON.parse(fs.readFileSync(path.join(root, 'index.json'), 'utf8'));
const e = index.addons.filter(a => a.id === 'homeassistant')[0];
ok(e && e.version === m.version, 'the index lists the version of addon.json');
process.exit(failed ? 1 : 0);
