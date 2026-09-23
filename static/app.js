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
        (filter.indexOf('r:') === 0 && tr.dataset.result === filter.slice(2)) ||
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

  // Balão com o motivo da falha. Fica no <body> para não ser cortado pela rolagem da tabela,
  // e usa delegação para continuar funcionando depois da atualização automática.
  var tipbox = null, tipFor = null;
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }
  function showTip(target) {
    if (tipFor === target) return;
    hideTip();
    tipFor = target;
    tipbox = el('div', 'tipbox');
    tipbox.setAttribute('role', 'tooltip');
    var title = el('div', 'tip-title');
    title.innerHTML = '<svg viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="7.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M9 4.8v5M9 12.4v.1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
    title.appendChild(el('span', '', target.dataset.tipTitle));
    tipbox.appendChild(title);
    if (target.dataset.tipBody) {
      tipbox.appendChild(el('div', 'tip-label', 'O que fazer'));
      tipbox.appendChild(el('p', '', target.dataset.tipBody));
    }
    if (target.dataset.tipTech) tipbox.appendChild(el('div', 'tip-tech', target.dataset.tipTech));
    document.body.appendChild(tipbox);
    var r = target.getBoundingClientRect(), w = tipbox.offsetWidth, h = tipbox.offsetHeight;
    var left = Math.min(Math.max(12, r.left), window.innerWidth - w - 12);
    var top = r.bottom + 8;
    if (top + h > window.innerHeight - 12) top = r.top - h - 8;  // Sem espaço embaixo: abre em cima.
    tipbox.style.left = left + 'px';
    tipbox.style.top = Math.max(12, top) + 'px';
    requestAnimationFrame(function () { if (tipbox) tipbox.classList.add('show'); });
  }
  function hideTip() {
    if (tipbox) tipbox.remove();
    tipbox = tipFor = null;
  }
  function tipTarget(e) { return e.target.closest && e.target.closest('.has-tip'); }
  document.addEventListener('mouseover', function (e) { var t = tipTarget(e); if (t) showTip(t); });
  document.addEventListener('mouseout', function (e) {
    var t = tipTarget(e);
    if (t && !t.contains(e.relatedTarget)) hideTip();
  });
  document.addEventListener('focusin', function (e) { var t = tipTarget(e); if (t) showTip(t); });
  document.addEventListener('focusout', function (e) { if (tipTarget(e)) hideTip(); });
  // Toque no celular: abre e fecha no mesmo lugar.
  document.addEventListener('click', function (e) {
    var t = tipTarget(e);
    if (t) { if (tipFor === t && e.pointerType === 'touch') hideTip(); else showTip(t); }
    else hideTip();
  });
  window.addEventListener('scroll', hideTip, true);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hideTip(); });

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
        hideTip();
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
