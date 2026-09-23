// Gráficos da aba "Gráficos": SVG desenhado aqui, sem biblioteca externa.
// Texto vindo dos dados (nome de campanha, motivo) entra sempre como textContent.
(function () {
  var source = document.getElementById('chart-data');
  if (!source) return;
  var data = JSON.parse(source.textContent);
  var NS = 'http://www.w3.org/2000/svg';
  var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
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
  function pct(x) { return (Math.round(x * 10) / 10).toString().replace('.', ',') + '%'; }
  // Barra com a ponta de dados arredondada (4px) e a base reta.
  function hbar(g, x, y, w, h, color) {
    if (w <= 0) return el('rect', {x: x, y: y, width: 0, height: h}, g);
    var r = Math.min(4, h / 2, w);
    return el('path', {d: 'M' + x + ',' + y + 'h' + (w - r) + 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + r +
      'v' + (h - 2 * r) + 'a' + r + ',' + r + ' 0 0 1 ' + (-r) + ',' + r + 'h' + (r - w) + 'z', style: 'fill:' + color}, g);
  }
  function vbar(g, x, base, w, h, color) {
    if (h <= 0) return null;
    var r = Math.min(4, w / 2, h);
    return el('path', {d: 'M' + x + ',' + base + 'v' + (r - h) + 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + (-r) +
      'h' + (w - 2 * r) + 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + r + 'v' + (h - r) + 'z', style: 'fill:' + color}, g);
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

  // 1. Comparativo entre campanhas: barras horizontais agrupadas, % dos enviados.
  function drawCompare(box) {
    var rows = data.compare, W = box.clientWidth;
    var series = [['delivered', 'Entregues', v('--stage-1')], ['read', 'Lidas', v('--stage-2')],
                  ['replied', 'Responderam', v('--stage-3')]];
    if (data.show_accepted) series.push(['accepted', 'Aceitaram', v('--stage-4')]);
    var thick = 8, gap = 2, bars = series.length * thick + (series.length - 1) * gap, rowGap = 20;
    // Tela estreita: nome da campanha em cima das barras, na largura toda.
    var stacked = W < 480, head = stacked ? 20 : 0, groupH = head + bars;
    var labelW = stacked ? 0 : Math.min(220, Math.max(110, W * 0.26)), x0 = stacked ? 0 : labelW + 12, x1 = W - 44, top = 6;
    var H = top + rows.length * (groupH + rowGap) + 16;
    var s = svg(box, W, H), g = el('g', {}, s);
    [0, 25, 50, 75, 100].forEach(function (t) {
      var x = x0 + (x1 - x0) * t / 100;
      el('line', {x1: x, x2: x, y1: top - 4, y2: H - 20, style: 'stroke:var(--grid)', 'stroke-width': 1}, g);
      el('text', {x: x, y: H - 4, 'text-anchor': 'middle'}, g, t + '%');
    });
    rows.forEach(function (c, i) {
      var y = top + i * (groupH + rowGap);
      var name = stacked
        ? el('text', {x: 0, y: y + 13, class: 'lbl'}, g, fit(c.name, W))
        : el('text', {x: labelW, y: y + groupH / 2 + 4, 'text-anchor': 'end', class: 'lbl'}, g, fit(c.name, labelW));
      el('title', {}, name, c.name + ' · ' + c.sent + ' enviados');
      series.forEach(function (sr, j) {
        var yy = y + head + j * (thick + gap), value = c[sr[0] + '_pct'];
        hbar(g, x0, yy, (x1 - x0) * value / 100, thick, sr[2]);
        if (sr[0] === 'replied') el('text', {x: x0 + (x1 - x0) * value / 100 + 6, y: yy + thick - 0.5, class: 'val'}, g, pct(value));
      });
      var hit = el('rect', {x: 0, y: y - rowGap / 2, width: W, height: groupH + rowGap, style: 'fill:transparent'}, g);
      tip(hit, c.name, [['', c.sent + ' enviados']].concat(series.map(function (sr) {
        return [sr[2], sr[1] + ': ' + c[sr[0]] + ' (' + pct(c[sr[0] + '_pct']) + ')'];
      })));
    });
  }

  // 2. Tempo até ler/responder: colunas agrupadas por faixa de tempo.
  function niceMax(m) {
    var steps = [10, 20, 25, 40, 50, 60, 80, 100];
    for (var i = 0; i < steps.length; i++) if (m <= steps[i]) return steps[i];
    return 100;
  }
  function drawDelays(box) {
    var W = box.clientWidth, H = 250, left = 38, right = 8, top = 10, base = H - 42;
    var labels = data.buckets, n = labels.length, band = (W - left - right) / n;
    var bw = Math.max(4, Math.min(24, (band - 14) / 2)), max = niceMax(Math.max.apply(null, data.read_pct.concat(data.reply_pct, [1])));
    var s = svg(box, W, H), g = el('g', {}, s), y = function (p) { return base - (base - top) * p / max; };
    for (var t = 0; t <= max; t += max / 4) {
      el('line', {x1: left, x2: W - right, y1: y(t), y2: y(t), style: 'stroke:' + (t ? 'var(--grid)' : 'var(--axis)'), 'stroke-width': 1}, g);
      el('text', {x: left - 6, y: y(t) + 4, 'text-anchor': 'end'}, g, Math.round(t) + '%');
    }
    labels.forEach(function (label, i) {
      var cx = left + band * i + band / 2;
      vbar(g, cx - bw - 1, base, bw, base - y(data.read_pct[i]), v('--series-1'));
      vbar(g, cx + 1, base, bw, base - y(data.reply_pct[i]), v('--series-2'));
      var parts = band < 70 && label.lastIndexOf(' ') > 0 ? [label.slice(0, label.lastIndexOf(' ')), label.slice(label.lastIndexOf(' ') + 1)] : [label];
      parts.forEach(function (p, k) { el('text', {x: cx, y: base + 16 + k * 13, 'text-anchor': 'middle'}, g, p); });
      var hit = el('rect', {x: left + band * i, y: top, width: band, height: base - top, style: 'fill:transparent'}, g);
      tip(hit, label + ' depois do disparo', [
        [v('--series-1'), 'Leituras: ' + data.read_n[i] + ' (' + pct(data.read_pct[i]) + ')'],
        [v('--series-2'), 'Respostas: ' + data.reply_n[i] + ' (' + pct(data.reply_pct[i]) + ')']]);
    });
  }

  // 3. Mapa de calor: dia da semana × hora das respostas.
  var RAMP = dark ? ['#184f95', '#1c5cab', '#2a78d6', '#5598e7', '#86b6ef', '#b7d3f6', '#cde2fb']
                  : ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
  function drawHeat(box) {
    var W = box.clientWidth, left = 34, gap = 2;
    var cell = Math.max(6, (W - left) / 24 - gap), ch = Math.min(22, Math.max(12, cell)), H = 7 * (ch + gap) + 22;
    var s = svg(box, W, H), g = el('g', {}, s);
    var max = Math.max.apply(null, [].concat.apply([1], data.heat));
    data.weekdays.forEach(function (d, r) {
      var y = r * (ch + gap);
      el('text', {x: 0, y: y + ch / 2 + 4}, g, d);
      for (var h = 0; h < 24; h++) {
        var n = data.heat[r][h], x = left + h * (cell + gap);
        var color = n ? RAMP[Math.min(RAMP.length - 1, Math.ceil(n / max * RAMP.length) - 1)] : 'var(--surface-2)';
        var rect = el('rect', {x: x, y: y, width: cell, height: ch, rx: 3, style: 'fill:' + color}, g);
        tip(rect, d + ', ' + h + 'h–' + (h + 1) + 'h', [['', n + ' resposta' + (n === 1 ? '' : 's')]]);
      }
    });
    for (var hr = 0; hr < 24; hr += 3) {
      el('text', {x: left + hr * (cell + gap) + cell / 2, y: H - 4, 'text-anchor': 'middle'}, g, hr + 'h');
    }
  }

  // 4. Motivos das falhas: barras horizontais com o motivo em cima e o total na ponta.
  function drawFailures(box) {
    var rows = data.failures, W = box.clientWidth, thick = 14, lineH = 16;
    var max = Math.max.apply(null, rows.map(function (r) { return r.n; })), barMax = W - 48;
    var texts = rows.map(function (r) { return wrap(r.reason, W, 2); });
    var H = texts.reduce(function (sum, t) { return sum + t.length * lineH + 4 + thick + 14; }, 0);
    var s = svg(box, W, H), g = el('g', {}, s), y = 0;
    rows.forEach(function (r, i) {
      var top = y, textH = texts[i].length * lineH;
      texts[i].forEach(function (line, k) { el('text', {x: 0, y: y + 13 + k * lineH, class: 'lbl'}, g, line); });
      var w = Math.max(3, barMax * r.n / max);
      hbar(g, 0, y + textH + 4, w, thick, v('--critical'));
      el('text', {x: w + 8, y: y + textH + 4 + thick - 2, class: 'val'}, g, String(r.n));
      y += textH + 4 + thick + 14;
      var hit = el('rect', {x: 0, y: top, width: W, height: y - top - 6, style: 'fill:transparent'}, g);
      tip(hit, r.reason, [['', r.n + ' de ' + data.failed + ' falhas (' + pct(r.n * 100 / data.failed) + ')']]);
    });
  }

  var drawers = {compare: drawCompare, delays: drawDelays, heat: drawHeat, failures: drawFailures};
  function drawAll() {
    document.querySelectorAll('[data-chart]').forEach(function (box) { drawers[box.dataset.chart](box); });
  }
  drawAll();
  var pending;
  window.addEventListener('resize', function () { clearTimeout(pending); pending = setTimeout(drawAll, 120); });

  // Dica ao passar o mouse (ou tocar) em uma barra/célula.
  var box = document.createElement('div');
  box.className = 'chart-tip';
  box.hidden = true;
  document.body.appendChild(box);
  function show(target, x, y) {
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
