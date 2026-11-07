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
function build(lang) {
  let html = page.phonePage(i18n, lang, '', '');
  for (const [a, b] of EDITS) {
    const n = html.split(a).length - 1;
    if (n < 1) throw new Error(lang + ': the page no longer has ' + a + ' (the Phone remote changed: update tools/build-card.js)');
    html = html.split(a).join(b);
  }
  // the shim runs first: it is the first script of the page
  const at = html.indexOf('<script');
  if (at < 0) throw new Error(lang + ': no script in the page');
  html = html.slice(0, at) + '<script>' + shim + '</script>' + html.slice(at);
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
