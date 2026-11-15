/* The Watch tab of the remote card (tools/build-card.js appends it to the page, after the page's own script).

   Series or films from the Jellyfin server of this TV: the episode to watch next of every series, and the films that were started
   and not finished, as posters of one size. A film plays at a tap; a series opens on its seasons, where an episode is picked. Playing
   turns the TV on if it has to, opens a Jellyfin client and starts where you left off. Everything goes through Home Assistant
   (cleanyourtv/library, /series and /play), so no Jellyfin address or key is in the browser. */
(function () {
  var L = window.CYTV_LIB;
  if (!L) return;
  var WORDS = {
    en: { tab: 'Watch', series: 'Series', movies: 'Films', none: 'Nothing to carry on with', off: 'Set up a Jellyfin server in the options of this integration to see what you can watch.', left: '%s min left', min: '%s min', back: 'Back', season: 'Season %s', next: 'Carry on with %s', ep: 'Episode %s' },
    nl: { tab: 'Kijken', series: 'Series', movies: 'Films', none: 'Niets om verder te kijken', off: 'Stel een Jellyfin-server in bij de opties van deze integratie om te zien wat je kunt kijken.', left: 'nog %s min', min: '%s min', back: 'Terug', season: 'Seizoen %s', next: 'Verder met %s', ep: 'Aflevering %s' },
    de: { tab: 'Ansehen', series: 'Serien', movies: 'Filme', none: 'Nichts zum Weiterschauen', off: 'Richte in den Optionen dieser Integration einen Jellyfin-Server ein.', left: 'noch %s Min', min: '%s Min', back: 'Zurück', season: 'Staffel %s', next: 'Weiter mit %s', ep: 'Folge %s' },
    fr: { tab: 'Regarder', series: 'Séries', movies: 'Films', none: 'Rien à reprendre', off: 'Configurez un serveur Jellyfin dans les options de cette intégration.', left: '%s min restantes', min: '%s min', back: 'Retour', season: 'Saison %s', next: 'Reprendre %s', ep: 'Épisode %s' },
    es: { tab: 'Ver', series: 'Series', movies: 'Películas', none: 'Nada que continuar', off: 'Configura un servidor Jellyfin en las opciones de esta integración.', left: 'quedan %s min', min: '%s min', back: 'Atrás', season: 'Temporada %s', next: 'Continuar con %s', ep: 'Episodio %s' },
    it: { tab: 'Guarda', series: 'Serie', movies: 'Film', none: 'Niente da riprendere', off: 'Configura un server Jellyfin nelle opzioni di questa integrazione.', left: '%s min rimasti', min: '%s min', back: 'Indietro', season: 'Stagione %s', next: 'Riprendi %s', ep: 'Episodio %s' },
    pt: { tab: 'Ver', series: 'Séries', movies: 'Filmes', none: 'Nada para continuar', off: 'Configure um servidor Jellyfin nas opções desta integração.', left: 'faltam %s min', min: '%s min', back: 'Voltar', season: 'Temporada %s', next: 'Continuar %s', ep: 'Episódio %s' },
  };
  var W = WORDS[(L.lang || 'en').slice(0, 2)] || WORDS.en;
  var tb = document.getElementById('bwa');
  if (tb) {
    tb.lastChild.textContent = W.tab; /* the page's own tabs are named by CleanYourTV's translations; this one is named here */
    tb.setAttribute('aria-label', W.tab);
  }
  var CSS =
    '#wa{flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:4px 20px 12px}' +
    /* Series | Films */
    '#wa .waseg{display:flex;gap:4px;padding:4px;margin:4px 0 12px;border-radius:12px;background:rgba(255,255,255,.06)}' +
    '#wa .waseg button{flex:1;min-width:0;padding:8px 4px;border:0;border-radius:9px;background:transparent;cursor:pointer;' +
    '-webkit-appearance:none;appearance:none;' +
    'font:600 13px/1 ui-sans-serif,system-ui;color:#9aa0b4;-webkit-tap-highlight-color:transparent}' +
    '#wa .waseg button.on{background:#ff8a5b;color:#16181f}' +
    /* the posters: every tile the same shape, whatever picture the server has */
    '#wa .wagrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}' +
    '#wa .wac{position:relative;display:block;min-width:0;max-width:100%;padding:0;border:0;background:none;overflow:hidden;' +
    '-webkit-appearance:none;appearance:none;text-align:left;cursor:pointer;-webkit-tap-highlight-color:transparent}' +
    '#wa .wap{display:block;position:relative;width:100%;aspect-ratio:2/3;border-radius:10px;overflow:hidden;background:#20222b;' +
    'box-shadow:0 2px 8px rgba(0,0,0,.25);transition:transform .12s ease}' +
    '#wa .wap img{width:100%;height:100%;object-fit:cover;display:block}' +
    '#wa .wac:active .wap{transform:scale(.97)}' +
    '#wa .wab{position:absolute;left:0;right:0;bottom:0;height:4px;background:rgba(0,0,0,.45)}#wa .wab b{display:block;height:100%;background:#ff8a5b}' +
    /* the title may run to two lines and is cut there; the line under it stays on one. Both are blocks of their own, so a long name
       is clipped by the tile instead of running into the one beside it */
    '#wa .wat{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;max-width:100%;margin:5px 0 0;overflow:hidden;' +
    'font:600 12.5px/1.25 ui-sans-serif,system-ui;color:#f4f5f7;min-height:2.5em}' +
    '#wa .was{display:block;max-width:100%;margin:2px 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' +
    'font:500 11px/1.25 ui-sans-serif,system-ui;color:#9aa0b4}' +
    '#wa .wamsg{font:500 13px/1.5 ui-sans-serif,system-ui;color:#9aa0b4;padding:18px 2px;text-align:center}' +
    '#wa .busy{position:relative}#wa .wac.busy .wap{opacity:.45}' +
    '#wa .busy:after{content:"";position:absolute;left:50%;top:50%;width:22px;height:22px;margin:-11px;' +
    'border:2px solid rgba(255,255,255,.3);border-top-color:#ff8a5b;border-radius:50%;animation:waspin .8s linear infinite}' +
    '#wa .wac.busy:after{top:28%}' +
    '@keyframes waspin{to{transform:rotate(360deg)}}' +
    /* one series: back, the seasons, the episodes */
    '#wa .wahead{display:flex;align-items:center;gap:10px;margin:0 0 10px}' +
    '#wa .waback{flex:none;width:34px;height:34px;border:0;border-radius:50%;background:rgba(255,255,255,.08);color:#f4f5f7;' +
    'font:600 17px/1 ui-sans-serif,system-ui;cursor:pointer}' +
    '#wa .wahead h3{flex:1;min-width:0;margin:0;font:700 16px/1.2 ui-sans-serif,system-ui;color:#f4f5f7;overflow:hidden;' +
    'text-overflow:ellipsis;white-space:nowrap}' +
    '#wa .wanext{display:block;width:100%;margin:0 0 12px;padding:11px 14px;border:0;border-radius:12px;background:#ff8a5b;' +
    '-webkit-appearance:none;appearance:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' +
    'color:#16181f;font:700 13px/1.2 ui-sans-serif,system-ui;text-align:left;cursor:pointer}' +
    '#wa .wasea{display:flex;gap:6px;overflow-x:auto;padding:0 0 10px;-webkit-overflow-scrolling:touch}' +
    '#wa .wasea button{flex:none;padding:7px 12px;border:0;border-radius:999px;background:rgba(255,255,255,.08);color:#c9cde0;' +
    'font:600 12px/1 ui-sans-serif,system-ui;cursor:pointer;white-space:nowrap}' +
    '#wa .wasea button.on{background:#f4f5f7;color:#16181f}' +
    '#wa .waep{position:relative;display:block;width:100%;padding:9px 10px;margin:0 0 6px;border:0;overflow:hidden;' +
    '-webkit-appearance:none;appearance:none;' +
    'border-radius:10px;background:rgba(255,255,255,.05);cursor:pointer;text-align:left;-webkit-tap-highlight-color:transparent}' +
    '#wa .waer{display:flex;align-items:center;width:100%}' +
    '#wa .waen{margin-right:10px}#wa .waem{margin-left:10px}' +
    '#wa .waep.seen{opacity:.55}#wa .waep:active{background:rgba(255,255,255,.12)}' +
    '#wa .waen{flex:none;width:26px;font:700 13px/1 ui-sans-serif,system-ui;color:#9aa0b4;text-align:right}' +
    '#wa .waet{flex:1;min-width:0;font:600 13px/1.3 ui-sans-serif,system-ui;color:#f4f5f7;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
    '#wa .waem{flex:none;font:500 11.5px/1 ui-sans-serif,system-ui;color:#9aa0b4}' +
    '#wa .waeb{position:absolute;left:10px;right:10px;bottom:3px;height:3px;border-radius:2px;background:rgba(255,255,255,.12)}' +
    '#wa .waeb b{display:block;height:100%;border-radius:2px;background:#ff8a5b}' +
    '.tabl{display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
    'html.light #wa .wat,html.light #wa .wahead h3,html.light #wa .waet{color:#16181f}' +
    'html.light #wa .wap{background:#e3e5ec}html.light #wa .waback{color:#16181f}';
  /* a button does not cut its own text on every phone (on iOS a long name was clipped at both ends), and the name of a tab is a bare
     text node in a column of flex, which no style can reach: each name goes in a span of its own, which carries the cutting. The
     phone remote does this itself from its next version; a name that is already in a span is left alone. */
  Array.prototype.forEach.call(document.querySelectorAll('.tabbar .tab'), function (b) {
    var last = b.lastChild;
    if (!last || last.nodeType !== 3 || !String(last.textContent).replace(/\s|\u200b/g, '')) return;
    var sp = document.createElement('span');
    sp.className = 'tabl';
    sp.textContent = last.textContent;
    b.replaceChild(sp, last);
  });
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
  function src(id) {
    return esc(L.pic + '/poster/' + encodeURIComponent(id) + '?t=' + encodeURIComponent(L.token));
  }
  function bar(p) {
    return p ? '<i class=wab><b style="width:' + Math.max(2, Math.min(100, p)) + '%"></b></i>' : '';
  }
  function each(box, sel, fn) {
    Array.prototype.forEach.call(box.querySelectorAll(sel), fn);
  }

  var data = null, /* what the server last told us */
    kind = 'series', /* which of the two is in front */
    open = null, /* the series that is open: {id, title, next, season} */
    busy = false;

  function posters(rows) {
    if (!rows.length) return '<p class=wamsg>' + esc(W.none) + '</p>';
    return (
      '<div class=wagrid>' +
      rows
        .map(function (r) {
          var sub = r.progress && r.minutes_left ? W.left.replace('%s', r.minutes_left) : r.sub;
          return (
            '<button class=wac data-item="' + esc(r.id) + '" data-series="' + esc(r.series || '') + '">' +
            '<span class=wap><img loading=lazy alt="" src="' + src(r.poster) + '">' + bar(r.progress) + '</span>' +
            '<span class=wat>' + esc(r.title) + '</span><span class=was>' + esc(sub) + '</span></button>'
          );
        })
        .join('') +
      '</div>'
    );
  }

  function draw() {
    var box = el('wa');
    if (!box) return;
    if (data && data.error) return void (box.innerHTML = '<p class=wamsg>' + esc(data.error) + '</p>');
    if (!data || !data.jellyfin) return void (box.innerHTML = '<p class=wamsg>' + esc(W.off) + '</p>');
    var rows = kind === 'movies' ? data.movies || [] : data.series || [];
    box.innerHTML =
      '<div class=waseg><button data-kind=series class="' + (kind === 'series' ? 'on' : '') + '">' + esc(W.series) + '</button>' +
      '<button data-kind=movies class="' + (kind === 'movies' ? 'on' : '') + '">' + esc(W.movies) + '</button></div>' +
      posters(rows);
    each(box, '.waseg button', function (b) {
      b.onclick = function () {
        kind = b.getAttribute('data-kind');
        draw();
      };
    });
    each(box, '.wac', function (b) {
      b.onclick = function () {
        var series = b.getAttribute('data-series');
        if (series) openSeries(series, b.querySelector('.wat').textContent);
        else play(b, b.getAttribute('data-item'));
      };
    });
  }

  function openSeries(id, title) {
    open = {
      id: id,
      title: title,
      next: (data.series || []).filter(function (r) {
        return r.series === id;
      })[0] || null,
      season: '',
    };
    drawSeries(null);
    loadSeries('');
  }

  function drawSeries(got) {
    var box = el('wa');
    if (!box || !open) return;
    var head =
      '<div class=wahead><button class=waback aria-label="' + esc(W.back) + '">&#8592;</button><h3>' + esc(open.title) + '</h3></div>';
    var next =
      open.next && open.next.sub
        ? '<button class=wanext data-item="' + esc(open.next.id) + '">' + esc(W.next.replace('%s', open.next.sub)) + '</button>'
        : '';
    if (!got) box.innerHTML = head + next + '<p class=wamsg>…</p>';
    else if (got.error) box.innerHTML = head + '<p class=wamsg>' + esc(got.error) + '</p>';
    else
      box.innerHTML =
        head +
        next +
        '<div class=wasea>' +
        (got.seasons || [])
          .map(function (s) {
            var name = typeof s.number === 'number' ? W.season.replace('%s', s.number) : s.name;
            return '<button data-season="' + esc(s.id) + '" class="' + (s.id === got.season ? 'on' : '') + '">' + esc(name) + '</button>';
          })
          .join('') +
        '</div>' +
        (got.episodes || [])
          .map(function (e) {
            return (
              '<button class="waep' + (e.watched ? ' seen' : '') + '" data-item="' + esc(e.id) + '"><span class=waer>' +
              '<span class=waen>' + esc(e.number || '') + '</span>' +
              '<span class=waet>' + esc(e.title || W.ep.replace('%s', e.number || '')) + '</span>' +
              '<span class=waem>' + esc(e.minutes ? W.min.replace('%s', e.minutes) : '') + '</span></span>' +
              (e.progress ? '<i class=waeb><b style="width:' + Math.max(2, Math.min(100, e.progress)) + '%"></b></i>' : '') +
              '</button>'
            );
          })
          .join('');
    box.querySelector('.waback').onclick = function () {
      open = null;
      draw();
    };
    each(box, '.wasea button', function (b) {
      b.onclick = function () {
        open.season = b.getAttribute('data-season');
        drawSeries(null);
        loadSeries(open.season);
      };
    });
    each(box, '.waep,.wanext', function (b) {
      b.onclick = function () {
        play(b, b.getAttribute('data-item'));
      };
    });
  }

  function loadSeries(season) {
    var want = open;
    L.series(open.id, season || '').then(
      function (got) {
        if (open === want) drawSeries(got);
      },
      function (e) {
        if (open === want) drawSeries({ error: String((e && e.message) || e || 'failed') });
      }
    );
  }

  function play(b, id) {
    if (busy || !id) return;
    busy = true;
    b.className += ' busy';
    var done = function () {
      busy = false;
      b.className = b.className.replace(' busy', '');
    };
    L.play(id).then(
      function (r) {
        done();
        if (r && r.ok === false) alert(r.error || 'failed');
        else setTimeout(load, 1200);
      },
      function (e) {
        done();
        alert(String((e && e.message) || e || 'failed'));
      }
    );
  }

  function load() {
    var box = el('wa');
    if (!box) return;
    if (!data) box.innerHTML = '<p class=wamsg>…</p>';
    L.list().then(
      function (j) {
        data = j;
        if (!open) draw();
        else
          open.next =
            (j.series || []).filter(function (r) {
              return r.series === open.id;
            })[0] || null;
      },
      function (e) {
        data = { error: String((e && e.message) || e || 'failed'), jellyfin: true };
        if (!open) draw();
      }
    );
  }

  window.CYTV_WATCH = function () {
    load();
  };
})();
