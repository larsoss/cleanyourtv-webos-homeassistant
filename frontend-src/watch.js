/* The Watch tab of the remote card (tools/build-card.js appends it to the page, after the page's own script).

   It shows what there is to carry on watching on the Jellyfin server of this TV: the episode to watch next of every series, and the
   films that were started and not finished, as posters. A poster is a button: it turns the TV on if it has to, opens a Jellyfin
   client and plays, from where it was left. Everything comes from Home Assistant (cleanyourtv/library and cleanyourtv/play), so no
   Jellyfin address or key is in the browser. */
(function () {
  var L = window.CYTV_LIB;
  if (!L) return;
  var WORDS = {
    en: { tab: 'Watch', series: 'Series', movies: 'Films', none: 'Nothing to carry on with', off: 'Set up a Jellyfin server in the options of this integration to see what you can watch.', starting: 'Starting…', left: '%s min left' },
    nl: { tab: 'Kijken', series: 'Series', movies: 'Films', none: 'Niets om verder te kijken', off: 'Stel een Jellyfin-server in bij de opties van deze integratie om te zien wat je kunt kijken.', starting: 'Starten…', left: 'nog %s min' },
    de: { tab: 'Ansehen', series: 'Serien', movies: 'Filme', none: 'Nichts zum Weiterschauen', off: 'Richte in den Optionen dieser Integration einen Jellyfin-Server ein.', starting: 'Startet…', left: 'noch %s Min' },
    fr: { tab: 'Regarder', series: 'Séries', movies: 'Films', none: 'Rien à reprendre', off: 'Configurez un serveur Jellyfin dans les options de cette intégration.', starting: 'Démarrage…', left: '%s min restantes' },
    es: { tab: 'Ver', series: 'Series', movies: 'Películas', none: 'Nada que continuar', off: 'Configura un servidor Jellyfin en las opciones de esta integración.', starting: 'Iniciando…', left: 'quedan %s min' },
    it: { tab: 'Guarda', series: 'Serie', movies: 'Film', none: 'Niente da riprendere', off: 'Configura un server Jellyfin nelle opzioni di questa integrazione.', starting: 'Avvio…', left: '%s min rimasti' },
    pt: { tab: 'Ver', series: 'Séries', movies: 'Filmes', none: 'Nada para continuar', off: 'Configure um servidor Jellyfin nas opções desta integração.', starting: 'A iniciar…', left: 'faltam %s min' },
  };
  var W = WORDS[(L.lang || 'en').slice(0, 2)] || WORDS.en;
  var CSS =
    '#wa{flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:6px 20px 12px}' +
    '#wa h4{font:600 12px/1 ui-sans-serif,system-ui;letter-spacing:.08em;text-transform:uppercase;color:#9aa0b4;margin:10px 2px 8px}' +
    '#wa .wagrid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}' +
    '#wa .wac{position:relative;display:flex;flex-direction:column;gap:5px;padding:0;border:0;background:none;text-align:left;cursor:pointer;-webkit-tap-highlight-color:transparent}' +
    '#wa .wap{position:relative;width:100%;aspect-ratio:2/3;border-radius:10px;overflow:hidden;background:#20222b;box-shadow:0 2px 8px rgba(0,0,0,.25)}' +
    '#wa .wap img{width:100%;height:100%;object-fit:cover;display:block}' +
    '#wa .wac:active .wap{transform:scale(.97)}#wa .wap{transition:transform .12s ease}' +
    '#wa .wab{position:absolute;left:0;right:0;bottom:0;height:4px;background:rgba(0,0,0,.45)}#wa .wab b{display:block;height:100%;background:#ff8a5b}' +
    '#wa .wat{font:600 12.5px/1.25 ui-sans-serif,system-ui;color:#f4f5f7;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
    '#wa .was{font:500 11px/1.25 ui-sans-serif,system-ui;color:#9aa0b4;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
    '#wa .wamsg{font:500 13px/1.5 ui-sans-serif,system-ui;color:#9aa0b4;padding:18px 2px;text-align:center}' +
    '#wa .wac.busy .wap{opacity:.45}#wa .wac.busy:after{content:"";position:absolute;left:50%;top:28%;width:22px;height:22px;margin:-11px;' +
    'border:2px solid rgba(255,255,255,.3);border-top-color:#ff8a5b;border-radius:50%;animation:waspin .8s linear infinite}' +
    '@keyframes waspin{to{transform:rotate(360deg)}}' +
    'html.light #wa .wat{color:#16181f}html.light #wa .wap{background:#e3e5ec}';
  var tb = document.getElementById('bwa');
  if (tb) {
    tb.lastChild.textContent = W.tab; /* the page's own tabs are named by CleanYourTV's translations; this one is named here */
    tb.setAttribute('aria-label', W.tab);
  }
  var st = document.createElement('style');
  st.textContent = CSS;
  document.head.appendChild(st);

  function el(id) {
    return document.getElementById(id);
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  var loaded = false,
    busy = false;

  function section(name, rows) {
    if (!rows.length) return '';
    return (
      '<h4>' +
      esc(name) +
      '</h4><div class=wagrid>' +
      rows
        .map(function (r) {
          var left = r.minutes_left ? W.left.replace('%s', r.minutes_left) : r.sub;
          return (
            '<button class=wac data-item="' +
            esc(r.id) +
            '"><span class=wap><img loading=lazy alt="" src="' +
            esc(L.pic + '/poster/' + encodeURIComponent(r.poster) + '?t=' + encodeURIComponent(L.token)) +
            '">' +
            (r.progress ? '<i class=wab><b style="width:' + Math.max(2, Math.min(100, r.progress)) + '%"></b></i>' : '') +
            '</span><span class=wat>' +
            esc(r.title) +
            '</span><span class=was>' +
            esc(r.progress ? left : r.sub) +
            '</span></button>'
          );
        })
        .join('') +
      '</div>'
    );
  }

  function draw(j) {
    var box = el('wa');
    if (!box) return;
    if (j && j.error) {
      box.innerHTML = '<p class=wamsg>' + esc(j.error) + '</p>';
      return;
    }
    if (!j || !j.jellyfin) {
      box.innerHTML = '<p class=wamsg>' + esc(W.off) + '</p>';
      return;
    }
    var html = section(W.series, j.series || []) + section(W.movies, j.movies || []);
    box.innerHTML = html || '<p class=wamsg>' + esc(W.none) + '</p>';
    Array.prototype.forEach.call(box.querySelectorAll('.wac'), function (b) {
      b.addEventListener('click', function () {
        play(b);
      });
    });
  }

  function play(b) {
    if (busy) return;
    busy = true;
    b.className = 'wac busy';
    L.play(b.getAttribute('data-item')).then(
      function (r) {
        busy = false;
        b.className = 'wac';
        if (r && r.ok === false) alert(r.error || 'failed');
        else setTimeout(load, 1000);
      },
      function (e) {
        busy = false;
        b.className = 'wac';
        alert(String((e && e.message) || e || 'failed'));
      }
    );
  }

  function load() {
    var box = el('wa');
    if (!box) return;
    if (!loaded) box.innerHTML = '<p class=wamsg>…</p>';
    L.list().then(
      function (j) {
        loaded = true;
        draw(j);
      },
      function (e) {
        draw({ error: String((e && e.message) || e || 'failed'), jellyfin: true });
      }
    );
  }

  window.CYTV_WATCH = function () {
    load();
  };
})();
