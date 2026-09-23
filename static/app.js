// Filtros da tabela, troca de campanha e atualização automática do painel.
(function () {
  var filter = 'all';
  var query = '';

  function applyFilter() {
    var rows = document.querySelectorAll('#contacts tbody tr[data-status]');
    var shown = 0;
    rows.forEach(function (tr) {
      var st = tr.dataset.status, replied = tr.dataset.replied === '1';
      var ok = filter === 'all' ||
        (filter === 'replied' && replied) ||
        (filter === 'pending' && (st === 'sent' || st === 'none')) ||
        (filter === 'delivered' && (st === 'delivered' || st === 'read')) ||
        (filter === st);
      if (ok && query) ok = tr.dataset.search.indexOf(query) !== -1;
      tr.classList.toggle('hidden', !ok);
      if (ok) shown++;
    });
    var none = document.getElementById('no-match');
    if (none) none.classList.toggle('hidden', shown > 0 || rows.length === 0);
    document.querySelectorAll('[data-filter]').forEach(function (b) {
      b.classList.toggle('on', b.dataset.filter === filter);
    });
  }

  function bind() {
    document.querySelectorAll('[data-filter]').forEach(function (b) {
      b.addEventListener('click', function () {
        filter = b.dataset.filter;
        applyFilter();
        if (b.classList.contains('stat')) document.getElementById('contacts').scrollIntoView({behavior: 'smooth'});
      });
    });
    var search = document.getElementById('search');
    if (search) {
      search.value = query;
      search.addEventListener('input', function () {
        query = search.value.trim().toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
        applyFilter();
      });
    }
    applyFilter();
  }

  var all = document.getElementById('check-all');
  if (all) all.addEventListener('change', function () {
    document.querySelectorAll('input[name="envio"]').forEach(function (c) { c.checked = all.checked; });
  });

  var pick = document.getElementById('campaign-pick');
  if (pick) pick.addEventListener('change', function () { pick.form.submit(); });

  bind();

  // Atualiza só a área de dados, sem recarregar a página nem perder filtro/busca.
  var live = document.getElementById('live');
  if (!live) return;
  var stamp = document.getElementById('updated');
  var last = Date.now();
  function tick() {
    if (!stamp) return;
    var s = Math.round((Date.now() - last) / 1000);
    stamp.textContent = s < 10 ? 'Atualizado agora' : 'Atualizado há ' + (s < 60 ? s + 's' : Math.floor(s / 60) + ' min');
  }
  function refresh() {
    if (document.hidden) return;
    // Não substitui a área enquanto a pessoa digita na busca.
    if (document.activeElement && document.activeElement.id === 'search') return;
    fetch(location.href, {credentials: 'same-origin'})
      .then(function (r) { if (!r.ok || r.redirected) throw 0; return r.text(); })
      .then(function (html) {
        var next = new DOMParser().parseFromString(html, 'text/html').getElementById('live');
        if (!next) return;
        live.innerHTML = next.innerHTML;
        last = Date.now();
        tick();
        bind();
      })
      .catch(function () {});
  }
  setInterval(refresh, 30000);
  setInterval(tick, 5000);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh(); });
})();
