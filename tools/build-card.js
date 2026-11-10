// Builds the remote card's pages from the Phone remote add-on of CleanYourTV (by Edenik, MIT): its phone page, in every language
// CleanYourTV has, with the card's shim in front of its script and the pictures pointed at Home Assistant.
//   CYTV_SRC=/path/to/cleanyourtv-WebOS node tools/build-card.js          writes custom_components/cleanyourtv/frontend/pages/<lang>.html
//   ... node tools/build-card.js --check                                   exit 1 when they are not up to date
// The page is used as it is, so it looks and works exactly like the Phone remote on a phone. A change of the page that the build cannot
// place (the strings it replaces) stops the build instead of making a card that half works.
'use strict';
const fs = require('fs'),
  path = require('path');
const src = process.env.CYTV_SRC;
if (!src) {
  console.error('set CYTV_SRC to a cleanyourtv-WebOS checkout');
  process.exit(2);
}
const page = require(path.join(src, 'addons/catalog/phoneremote/page.js'));
const i18n = require(path.join(src, 'helper/i18n.js'));
const shim = fs.readFileSync(path.join(__dirname, '..', 'frontend-src', 'shim.js'), 'utf8');
const out = path.join(__dirname, '..', 'custom_components', 'cleanyourtv', 'frontend', 'pages');
const langs = fs
  .readdirSync(path.join(src, 'i18n'))
  .filter(f => /^[a-z]{2}\.json$/.test(f))
  .map(f => f.slice(0, 2))
  .sort();

// each one must be found exactly where it is expected
const EDITS = [
  // the logos and app icons: through Home Assistant (/api/cleanyourtv/<entry>/...), with the entry's secret as the token
  ['src="/api/logo/\'', 'src="\'+CYTV_PIC+\'/api/logo/\''],
  ['src="/icon/\'', 'src="\'+CYTV_PIC+\'/icon/\''],
  // the Live tab: the programme on now from the guide, with how far it is, under the channel's name (when the TV has a guide)
  [
    "'<span class=lvt>'+esc(c.name)+'</span></button>'",
    "'<span class=lvw><span class=lvt>'+esc(c.name)+'</span>'+(c.now&&c.now.title?'<span class=lvp>'+esc(c.now.title)+'</span><i class=lvb><b style=\"width:'+Math.max(0,Math.min(100,Math.round((Date.now()/1000-c.now.start)*100/Math.max(1,c.now.end-c.now.start))))+'%\"></b></i>':'')+'</span></button>'",
  ],
  [
    '</style>',
    '.lvgrid .lvw{flex:1;min-width:0;display:flex;flex-direction:column;align-items:flex-start}.lvgrid .lvw .lvt{flex:none;max-height:1.3em;white-space:nowrap;text-overflow:ellipsis;max-width:100%}' +
      '.lvgrid .lvp{font:500 11.5px/1.3 ui-sans-serif,system-ui;color:#9aa0b4;max-width:100%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;margin-top:2px}' +
      '.lvgrid .lvb{display:block;width:100%;height:3px;border-radius:2px;background:#2a2d38;margin-top:5px;overflow:hidden}.lvgrid .lvb b{display:block;height:100%;background:#ff8a5b}</style>',
  ],
];
// light mode: every colour of the page's stylesheet becomes a variable with the page's own (dark) colour, and html.light (set by the card when
// Home Assistant's theme is light) gives it the light one. A colour not in this list stays as it is in both modes (the accent, the colour keys).
const LIGHT = {
  // surfaces, from the page's background up
  '#101116': '#f2f3f7', '#111319': '#e9ebf0', '#13141a': '#ffffff', '#14161c': '#f7f8fa', '#14161d': '#f7f8fa', '#151720': '#eceef3',
  '#1a1c23': '#ffffff', '#1b1d25': '#ffffff', '#1c1f2a': '#ffffff', '#1d2028': '#f7f8fa', '#20222b': '#eceef3', '#232631': '#eceef3',
  '#23262f': '#e3e5ec', '#2a2d3a': '#e4e6ec', '#2a2d38': '#e3e5ec', '#2e3140': '#d9dce5', '#3a3e50': '#c9cdd8', '#3a3e4d': '#c9cdd8',
  // text
  '#f4f5f7': '#16181f', '#fff': '#000', '#dde0ea': '#2a2d38', '#c9ccd8': '#4a4f60', '#a3a8b8': '#626879', '#9aa0b4': '#6a7083',
  '#646b82': '#9aa0b2',
  // the accent when pressed, and the states
  '#ffb08f': '#e8692f', '#7be0a4': '#1f8a4c', '#f0d58a': '#a77b00', '#f0a0a0': '#c43c3c', '#ff9f9f': '#c43c3c',
  '#5a3434': '#f0c4c4', '#1d1517': '#fff1f1', '#6b2b2b': '#e9b0b0', '#2a1717': '#fff0f0', '#1d1714': '#fff4ee', '#5a3b2c': '#f5d2c0',
  '#5a3a2b': '#f5cdb8', '#241a17': '#fff1ea', '#6b4330': '#f0c0a5', '#2a1d18': '#ffeee5', '#12231b': '#e9f8ef', '#bfe9cf': '#1d5c37',
  '#2a2412': '#fff8e1', '#ffe9a8': '#6b5200',
  // see-through layers: white on dark becomes black on light
  'rgba(8,9,12,.66)': 'rgba(20,22,30,.35)', 'rgba(255,255,255,.05)': 'rgba(0,0,0,.05)', 'rgba(255,255,255,.06)': 'rgba(0,0,0,.07)',
  'rgba(255,255,255,.03)': 'rgba(0,0,0,.02)', 'rgba(255,255,255,.10)': 'rgba(0,0,0,.07)', 'rgba(163,168,184,.6)': 'rgba(98,104,121,.6)',
  'rgba(0,0,0,.45)': 'rgba(0,0,0,.15)',
};
function themed(html) {
  const a = html.indexOf('<style>'),
    b = html.indexOf('</style>', a);
  if (a < 0 || b < 0) throw new Error('no stylesheet in the page');
  const used = new Map();
  const css = html.slice(a + 7, b).replace(/#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?![0-9a-fA-F])|rgba\([^)]*\)/g, c => {
    const k = c.toLowerCase();
    if (!(k in LIGHT)) return c;
    if (!used.has(k)) used.set(k, '--cy' + used.size);
    return 'var(' + used.get(k) + ')';
  });
  const dark = [...used].map(([c, v]) => v + ':' + c).join(';'),
    light = [...used].map(([c, v]) => v + ':' + LIGHT[c]).join(';');
  return html.slice(0, a + 7) + ':root{' + dark + ';color-scheme:dark}html.light{' + light + ';color-scheme:light}' + css + html.slice(b);
}
function build(lang) {
  let html = page.phonePage(i18n, lang, '', '');
  for (const [a, b] of EDITS) {
    const n = html.split(a).length - 1;
    if (n < 1) throw new Error(lang + ': the page no longer has ' + a + ' (the Phone remote changed: update tools/build-card.js)');
    html = html.split(a).join(b);
  }
  html = themed(html);
  // in Home Assistant: the page is see-through (the remote stands on the card or the page around it, no box of its own), the remote sits
  // under the top bar instead of in the middle of the frame, and the close button (the shim's) keeps its distance from the power button
  html = html.replace(
    '</style>',
    'body,.tabbar{background:transparent}#kb>.cv{margin:10px 0 auto}#tp>.cv{margin:4px 0 auto}#cyx{flex:none}</style>'
  );
  // the shim runs first: it is the first script of the page
  const at = html.indexOf('<script');
  if (at < 0) throw new Error(lang + ': no script in the page');
  html = html.slice(0, at) + '<script>' + shim + '</script>' + html.slice(at);
  // the Home Screen app tags of the phone page (manifest, icon, full screen on iOS) mean nothing in a frame, and the manifest would be asked
  // of Home Assistant: out
  html = html.replace(/<link rel=(?:manifest|apple-touch-icon) [^>]*>/g, '').replace(/<meta name=(?:apple-mobile-web-app-[a-z-]+|mobile-web-app-capable) [^>]*>/g, '');
  // the page fills the frame: the card decides the size
  html = html.replace('<meta charset=utf-8>', '<meta charset=utf-8><base target=_self>');
  return html;
}
const check = process.argv.indexOf('--check') >= 0;
let stale = 0;
fs.mkdirSync(out, { recursive: true });
for (const l of langs) {
  const html = build(l),
    f = path.join(out, l + '.html');
  if (check) {
    if (!fs.existsSync(f) || fs.readFileSync(f, 'utf8') !== html) {
      console.error(f + ' is not up to date: run node tools/build-card.js');
      stale++;
    }
  } else fs.writeFileSync(f, html);
}
fs.writeFileSync(path.join(out, '..', 'langs.json'), JSON.stringify(langs) + '\n');
if (!check) console.log('wrote ' + langs.length + ' pages (' + langs.join(' ') + ')');
process.exit(stale ? 1 : 0);
