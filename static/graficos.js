// Gráficos da aba "Gráficos": SVG desenhado aqui, sem biblioteca externa.
// Texto vindo dos dados (nome de campanha, motivo) entra sempre como textContent.
(function () {
  var source = document.getElementById('chart-data');
  if (!source) return;
  var data = JSON.parse(source.textContent);
  var NS = 'http://www.w3.org/2000/svg';
  var css = getComputedStyle(document.documentElement);
  function v(name) { return css.getPropertyValue(name).trim(); }

  function el(tag, attrs, parent, text) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  }
  function svg(box, w, h) {
    box.textContent = '';
    return el('svg', {viewBox: '0 0 ' + w + ' ' + h, width: w, height: h, role: 'img'}, box);
  }
  function pct(x) { return x == null ? '—' : (Math.round(x * 10) / 10).toString().replace('.', ',') + '%'; }
  function ci(c) { return Math.round(c[0]) + '–' + Math.round(c[1]) + '%'; }
  // Barra com a ponta de dados arredondada (4px) e a base reta.
  function hbar(g, x, y, w, h, color) {
    if (w <= 0) return el('rect', {x: x, y: y, width: 0, height: h}, g);
    var r = Math.min(4, h / 2, w);
    return el('path', {d: 'M' + x + ',' + y + 'h' + (w - r) + 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + r +
      'v' + (h - 2 * r) + 'a' + r + ',' + r + ' 0 0 1 ' + (-r) + ',' + r + 'h' + (r - w) + 'z', style: 'fill:' + color}, g);
  }
  function vbar(g, x, base, w, h, color, opacity) {
    if (h <= 0) return null;
    var r = Math.min(4, w / 2, h);
    return el('path', {d: 'M' + x + ',' + base + 'v' + (r - h) + 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + (-r) +
      'h' + (w - 2 * r) + 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + r + 'v' + (h - r) + 'z',
      style: 'fill:' + color + (opacity ? ';opacity:' + opacity : '')}, g);
  }
  function fit(text, px) {  // Corta com reticências para caber em px (estimativa de ~7px por letra).
    var max = Math.max(4, Math.floor(px / 7));
    return text.length > max ? text.slice(0, max - 1) + '…' : text;
  }
  function wrap(text, px, maxLines) {  // Quebra por palavras em até maxLines linhas.
    var max = Math.max(4, Math.floor(px / 7)), lines = [], line = '';
    text.split(' ').forEach(function (word) {
      if ((line + ' ' + word).trim().length > max && line) { lines.push(line); line = word; }
      else line = (line + ' ' + word).trim();
    });
    lines.push(line);
    if (lines.length > maxLines) {
      lines = lines.slice(0, maxLines);
      lines[maxLines - 1] = fit(lines[maxLines - 1] + ' …', px);
    }
    return lines;
  }
  function tip(node, title, lines) {
    node.setAttribute('data-tip', title);
    node.setAttribute('data-tip-lines', JSON.stringify(lines));
  }
  function niceMax(m) {
    var steps = [5, 10, 20, 25, 40, 50, 60, 80, 100];
    for (var i = 0; i < steps.length; i++) if (m <= steps[i]) return steps[i];
    return 100;
  }
  function gridY(g, x0, x1, y, max) {
    var ticks = max % 4 === 0 && max >= 20 ? 4 : 5;  // Marcas sempre em números redondos.
    for (var t = 0; t <= ticks; t++) {
      var val = max * t / ticks, yy = y(val);
      el('line', {x1: x0, x2: x1, y1: yy, y2: yy, style: 'stroke:' + (t ? 'var(--grid)' : 'var(--axis)'), 'stroke-width': 1}, g);
      el('text', {x: x0 - 6, y: yy + 4, 'text-anchor': 'end'}, g, Math.round(val) + '%');
    }
  }

  // 1. Funil etapa a etapa: ponto = taxa da etapa, traço = IC 95% (small multiples por etapa).
  function drawFunnel(box) {
    var rows = data.compare, labels = data.step_labels, S = labels.length, W = box.clientWidth;
    var cols = W < 560 ? 1 : S, gap = 18, rowH = 26, head = 22, foot = 22;
    var labelW = cols === 1 ? Math.min(140, W * 0.34) : Math.min(200, Math.max(110, W * 0.18));
    var panelW = (W - labelW - 12 - (cols - 1) * gap) / cols;
    var blockH = head + rows.length * rowH + foot, H = (cols === 1 ? S : 1) * blockH + (cols === 1 ? (S - 1) * 12 : 0);
    var s = svg(box, W, H), g = el('g', {}, s), color = v('--series-1');
    labels.forEach(function (label, j) {
      var px = labelW + 12 + (cols === 1 ? 0 : j * (panelW + gap)), py = cols === 1 ? j * (blockH + 12) : 0;
      var x = function (p) { return px + panelW * p / 100; };
      var title = label + ' · ' + data.step_desc[j];
      el('text', {x: px, y: py + 13, class: 'lbl', 'font-weight': 600}, g, title.length * 7 < panelW ? title : fit(label, panelW));
      [0, 50, 100].forEach(function (t) {
        el('line', {x1: x(t), x2: x(t), y1: py + head - 4, y2: py + blockH - foot + 2, style: 'stroke:' + (t ? 'var(--grid)' : 'var(--axis)'), 'stroke-width': 1}, g);
        el('text', {x: x(t), y: py + blockH - 6, 'text-anchor': t === 0 ? 'start' : t === 100 ? 'end' : 'middle'}, g, t + '%');
      });
      rows.forEach(function (c, i) {
        var cy = py + head + i * rowH + rowH / 2, st = c.steps[j];
        if (cols === 1 || j === 0) el('text', {x: labelW, y: cy + 4, 'text-anchor': 'end', class: 'lbl'}, g, fit(c.name, labelW));
        if (!st.n) { el('text', {x: px + 4, y: cy + 4}, g, 'sem base'); return; }
        el('line', {x1: x(st.ci[0]), x2: x(st.ci[1]), y1: cy, y2: cy, style: 'stroke:' + color + ';opacity:.45', 'stroke-width': 2, 'stroke-linecap': 'round'}, g);
        el('circle', {cx: x(st.rate), cy: cy, r: 5, style: st.small ? 'fill:var(--surface);stroke:' + color + ';stroke-width:2' : 'fill:' + color + ';stroke:var(--surface);stroke-width:2'}, g);
        var hit = el('rect', {x: px - 4, y: cy - rowH / 2, width: panelW + 8, height: rowH, style: 'fill:transparent'}, g);
        tip(hit, c.name + ' · ' + label, [
          [color, 'Taxa: ' + pct(st.rate) + ' (' + st.k + ' de ' + st.n + ')'],
          ['', 'IC 95%: ' + ci(st.ci)]
        ].concat(st.small ? [['', 'Base pequena: taxa pouco confiável']] : []));
      });
    });
  }

  // 2. Curva acumulada: % dos enviados que já respondeu / teve leitura confirmada até t (escala log).
  function drawCurve(box) {
    var W = box.clientWidth, H = 250, left = 40, right = 54, top = 10, base = H - 30;
    var mins = data.curve_minutes, lo = Math.log(mins[0]), hi = Math.log(mins[mins.length - 1]);
    var max = niceMax(Math.max(Math.max.apply(null, data.reply_curve), Math.max.apply(null, data.read_curve), 1) * 1.1);
    var x = function (m) { return left + (W - left - right) * (Math.log(m) - lo) / (hi - lo); };
    var y = function (p) { return base - (base - top) * p / max; };
    var s = svg(box, W, H), g = el('g', {}, s);
    gridY(g, left, W - right, y, max);
    var ticks = W < 480 ? [[1, '1 min'], [60, '1 h'], [1440, '1 dia'], [10080, '7 dias']]
      : [[1, '1 min'], [5, '5 min'], [15, '15 min'], [60, '1 h'], [360, '6 h'], [1440, '1 dia'], [4320, '3 dias'], [10080, '7 dias']];
    ticks.forEach(function (t) { el('text', {x: x(t[0]), y: H - 8, 'text-anchor': 'middle'}, g, t[1]); });
    var series = [[data.read_curve, v('--series-1'), 'Leitura confirmada'], [data.reply_curve, v('--series-2'), 'Responderam']];
    series.forEach(function (sr) {
      var d = sr[0].map(function (p, i) { return (i ? 'L' : 'M') + x(mins[i]) + ',' + y(p); }).join('');
      el('path', {d: d, style: 'fill:none;stroke:' + sr[1], 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}, g);
      var last = sr[0][sr[0].length - 1];
      el('circle', {cx: x(mins[mins.length - 1]), cy: y(last), r: 4, style: 'fill:' + sr[1] + ';stroke:var(--surface);stroke-width:2'}, g);
      el('text', {x: x(mins[mins.length - 1]) + 8, y: y(last) + 4, class: 'val'}, g, pct(last));
    });
    // Linha-guia com os valores do ponto mais próximo do mouse.
    var guide = el('line', {x1: 0, x2: 0, y1: top, y2: base, style: 'stroke:var(--axis);visibility:hidden', 'stroke-width': 1}, g);
    var dots = series.map(function (sr) { return el('circle', {r: 4, style: 'visibility:hidden;fill:' + sr[1] + ';stroke:var(--surface);stroke-width:2'}, g); });
    var hit = el('rect', {x: left, y: top, width: W - left - right, height: base - top, style: 'fill:transparent'}, g);
    tip(hit, '', []);
    hit.addEventListener('pointermove', function (e) {
      var r = s.getBoundingClientRect(), mx = (e.clientX - r.left) * W / r.width, best = 0;
      mins.forEach(function (m, i) { if (Math.abs(x(m) - mx) < Math.abs(x(mins[best]) - mx)) best = i; });
      var m = mins[best], label = m < 60 ? m + ' min' : m < 1440 ? (m / 60).toString().replace('.', ',') + ' h' : (m / 1440).toString().replace('.', ',') + ' dia' + (m >= 2880 ? 's' : '');
      guide.setAttribute('x1', x(m)); guide.setAttribute('x2', x(m)); guide.style.visibility = 'visible';
      series.forEach(function (sr, k) { dots[k].setAttribute('cx', x(m)); dots[k].setAttribute('cy', y(sr[0][best])); dots[k].style.visibility = 'visible'; });
      tip(hit, 'Até ' + label + ' depois do disparo', series.slice().reverse().map(function (sr) { return [sr[1], sr[2] + ': ' + pct(sr[0][best]) + ' dos enviados']; }));
    });
    hit.addEventListener('pointerleave', function () {
      guide.style.visibility = 'hidden';
      dots.forEach(function (d) { d.style.visibility = 'hidden'; });
    });
  }

  // 3. Taxa de resposta por horário do disparo, com IC 95%. Horários com pouca base ficam apagados.
  function drawHours(box) {
    var W = box.clientWidth, H = 220, left = 40, right = 6, top = 10, base = H - 26;
    var hours = data.hours, band = (W - left - right) / 24, bw = Math.max(4, Math.min(20, band - 4));
    var solid = hours.filter(function (h) { return h.n >= 10; });
    var max = niceMax(Math.max.apply(null, (solid.length ? solid.map(function (h) { return h.ci[1]; }) : hours.map(function (h) { return h.rate || 0; })).concat([1])));
    var y = function (p) { return base - (base - top) * Math.min(p, max) / max; };
    var s = svg(box, W, H), g = el('g', {}, s), color = v('--series-1');
    gridY(g, left, W - right, y, max);
    hours.forEach(function (h, i) {
      var cx = left + band * i + band / 2;
      if (i % 3 === 0) el('text', {x: cx, y: H - 8, 'text-anchor': 'middle'}, g, i + 'h');
      if (!h.n) return;
      var weak = h.n < 10;
      vbar(g, cx - bw / 2, base, bw, base - y(h.rate || 0), color, weak ? 0.3 : 0);
      if (!weak) {
        el('line', {x1: cx, x2: cx, y1: y(h.ci[0]), y2: y(h.ci[1]), style: 'stroke:var(--text);opacity:.55', 'stroke-width': 1.5}, g);
        el('line', {x1: cx - 3, x2: cx + 3, y1: y(h.ci[1]), y2: y(h.ci[1]), style: 'stroke:var(--text);opacity:.55', 'stroke-width': 1.5}, g);
        el('line', {x1: cx - 3, x2: cx + 3, y1: y(h.ci[0]), y2: y(h.ci[0]), style: 'stroke:var(--text);opacity:.55', 'stroke-width': 1.5}, g);
      }
      var hit = el('rect', {x: left + band * i, y: top, width: band, height: base - top, style: 'fill:transparent'}, g);
      tip(hit, 'Disparos às ' + i + 'h', [[color, 'Responderam: ' + pct(h.rate) + ' (' + h.k + ' de ' + h.n + ')'], ['', 'IC 95%: ' + ci(h.ci)]]
        .concat(weak ? [['', 'Menos de 10 envios: não dá para comparar']] : []));
    });
  }

  // 4. Motivos das falhas: motivo em cima, barra com total e % dos envios na ponta.
  function drawFailures(box) {
    var rows = data.failures, W = box.clientWidth, thick = 14, lineH = 16;
    var max = Math.max.apply(null, rows.map(function (r) { return r.n; })), barMax = W - 110;
    var texts = rows.map(function (r) { return wrap(r.reason, W, 2); });
    var H = texts.reduce(function (sum, t) { return sum + t.length * lineH + 4 + thick + 14; }, 0);
    var s = svg(box, W, H), g = el('g', {}, s), y = 0;
    rows.forEach(function (r, i) {
      var top = y, textH = texts[i].length * lineH;
      texts[i].forEach(function (line, k) { el('text', {x: 0, y: y + 13 + k * lineH, class: 'lbl'}, g, line); });
      var w = Math.max(3, barMax * r.n / max);
      hbar(g, 0, y + textH + 4, w, thick, v('--critical'));
      el('text', {x: w + 8, y: y + textH + 4 + thick - 2, class: 'val'}, g, r.n + ' · ' + pct(r.pct));
      y += textH + 4 + thick + 14;
      var hit = el('rect', {x: 0, y: top, width: W, height: y - top - 6, style: 'fill:transparent'}, g);
      tip(hit, r.reason, [['', r.n + ' falhas · ' + pct(r.pct) + ' dos envios do período']]);
    });
  }

  var drawers = {funnel: drawFunnel, curve: drawCurve, hours: drawHours, failures: drawFailures};
  function drawAll() {
    document.querySelectorAll('[data-chart]').forEach(function (box) { drawers[box.dataset.chart](box); });
  }
  drawAll();
  var pending;
  window.addEventListener('resize', function () { clearTimeout(pending); pending = setTimeout(drawAll, 120); });

  // Dica ao passar o mouse (ou tocar) em uma marca.
  var box = document.createElement('div');
  box.className = 'chart-tip';
  box.hidden = true;
  document.body.appendChild(box);
  function show(target, x, y) {
    if (!target.getAttribute('data-tip')) { box.hidden = true; return; }
    box.textContent = '';
    var b = document.createElement('b');
    b.textContent = target.getAttribute('data-tip');
    box.appendChild(b);
    JSON.parse(target.getAttribute('data-tip-lines')).forEach(function (line) {
      var row = document.createElement('div');
      if (line[0]) {
        var sw = document.createElement('span');
        sw.className = 'sw';
        sw.style.background = line[0];
        row.appendChild(sw);
      }
      row.appendChild(document.createTextNode(line[1]));
      box.appendChild(row);
    });
    box.hidden = false;
    var w = box.offsetWidth, h = box.offsetHeight;
    box.style.left = Math.min(x + 14, window.innerWidth - w - 8) + 'px';
    box.style.top = (y + h + 20 > window.innerHeight ? y - h - 12 : y + 14) + 'px';
  }
  document.addEventListener('pointermove', function (e) {
    var t = e.target.closest && e.target.closest('.chart [data-tip]');
    if (t) show(t, e.clientX, e.clientY); else box.hidden = true;
  });
  window.addEventListener('scroll', function () { box.hidden = true; }, true);
})();
