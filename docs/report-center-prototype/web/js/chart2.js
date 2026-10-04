/* 走势图与空窗口提示：覆盖 shell.js 里的 chart() / render()，只改这两件，数据层不动。 */
var __monthlyNote = '';
function chart(series) {
  __monthlyNote = '';
  var ms = DASH.state.monthlySeries;
  if (ms && ms.items && ms.items.length && DASH.state.win && ms.key === monthlyKeyOf(DASH.state.win)) {
    series = ms.items;
    __monthlyNote = '这个区间跨了好几年，接口的逐日曲线是拿「月-日」当键的（跨年会把同一年的数字重复铺满每一年），所以走势图改成逐月取数：一共 ' + ms.items.length + ' 个月，只画真有单的那些月。';
  }
  if (!series || !series.length) return '<div class="dim">这一段没有数据</div>';
  var per = 1, merged = false, rawLen = series.length, trimmed = '';
  if (series.length > 62) {
    per = Math.ceil(series.length / 40);
    var acc = [];
    for (var i0 = 0; i0 < series.length; i0 += per) {
      var chunk = series.slice(i0, i0 + per), a0 = 0, f0 = 0;
      chunk.forEach(function (x) { a0 += num(x.amount) || 0; f0 += num(x.freight) || 0; });
      acc.push({ label: chunk[0].label, amount: a0, freight: f0, n: chunk.length });
    }
    series = acc; merged = true;
  }
  /* 首尾连着没有单的那些根先掐掉，不然长窗口（比如全部）前面几年全是一排空柱子 */
  var firstNZ = -1, lastNZ = -1;
  for (var j = 0; j < series.length; j++) {
    if ((num(series[j].amount) || 0) > 0 || (num(series[j].freight) || 0) > 0) { if (firstNZ < 0) firstNZ = j; lastNZ = j; }
  }
  if (firstNZ < 0) return '<div class="dim">这一段没有数据</div>';
  /* 只在长窗口（合并过的）里掐空档：短窗口那几根空柱子本来就该留着，让横轴和区间对得上 */
  if (merged && (firstNZ > 0 || lastNZ < series.length - 1)) {
    var headC = series.slice(0, firstNZ), tailC = series.slice(lastNZ + 1);
    if (headC.length) trimmed += '前面 ' + headC.length + ' 根（' + esc(headC[0].label) + ' ~ ' + esc(headC[headC.length - 1].label) + '）没有单；';
    if (tailC.length) trimmed += '后面 ' + tailC.length + ' 根（' + esc(tailC[0].label) + ' ~ ' + esc(tailC[tailC.length - 1].label) + '）没有单；';
    trimmed += '图上把这两段空档省掉了 —— 数字一个没少，只是不画空格子。';
    series = series.slice(firstNZ, lastNZ + 1);
  }
  var max = 0;
  series.forEach(function (s) { max = Math.max(max, num(s.amount) || 0, num(s.freight) || 0); });
  if (max <= 0) return '<div class="dim">这一段没有数据</div>';
  var step = series.length > 12 ? Math.ceil(series.length / 6) : 1;
  var bars = series.map(function (s, i) {
    var a = (num(s.amount) || 0) / max * 100;
    var f = (num(s.freight) || 0) / max * 100;
    var show = (i % step === 0) || i === series.length - 1;
    return '<div class="col" title="' + (merged ? ('合并 ' + s.n + ' 天（从 ' + esc(s.label) + ' 起）：') : (esc(s.label) + '：')) +
      '营业额 ' + money(s.amount) + ' / 运费 ' + money(s.freight) + '">' +
      '<div class="cb"><i class="b1" style="height:' + a + '%"></i><i class="b2" style="height:' + f + '%"></i></div>' +
      '<span>' + (show ? esc(s.label) : '') + '</span></div>';
  }).join('');
  return '<div class="chart' + (series.length > 12 ? ' thin' : '') + '">' + bars + '</div>' +
    '<div class="legend"><span><i class="sw b1"></i>营业额</span><span><i class="sw b2"></i>司机运费</span>' +
    '<span class="dim">同一把尺子（最高柱 = ' + money0(max) + '）· 一共 ' + series.length + ' 根柱子</span></div>' +
    (series.length > 12 ? '<div class="axlab">横轴 ' + esc(series[0].label) + ' &#8594; ' + esc(series[series.length - 1].label) +
      '（柱子上悬停/长按能看到每一根的准确数）</div>' : '') +
    (merged ? '<div class="axlab">接口给的是逐日 ' + rawLen + ' 天，手机上画不下这么多根，页面把每 ' + per + ' 天并成一根（只是画面上的合并，数字是相加的，各柱之和仍然等于总额；逐日原文在下面「原始 JSON」里）。</div>' : '') +
    (__monthlyNote ? '<div class="axlab">' + __monthlyNote + '</div>' : '') +
    (trimmed ? '<div class="axlab">' + trimmed + '</div>' : '');
}
/* 空窗口：这个区间真的没有已送达的单时，给一句人话 + 一键换到有数据的区间 */
function emptyHint() {
  if (DASH.state.busy || !DASH.state.data) return '';
  var t = d('turnover');
  if (!t || Number(t.total_orders) !== 0) return '';
  var w = DASH.state.win;
  return '<div class="notice eh"><b>这个区间里没有已送达的单</b>（' + esc(w.from) + ' ~ ' + esc(w.to) + '）。' +
    '<div class="ehb">' +
    '<button class="pill" onclick="setWin(&apos;last&apos;)">看上月</button>' +
    '<button class="pill" onclick="setRange(&apos;2026-09-01&apos;,&apos;2026-09-30&apos;,&apos;2026-09&apos;)">2026-09</button>' +
    '<button class="pill" onclick="setRange(&apos;2026-09-25&apos;,&apos;2026-09-25&apos;,&apos;9-25&apos;)">9-25</button>' +
    '<button class="pill" onclick="setWin(&apos;all&apos;)">全部</button></div>' +
    '下面每张卡把 0 照接口原文显示出来 —— 数字没错，是这个区间真的没有单。</div>';
}
function render() {
  if (!DASH.state.token) { document.getElementById('root').innerHTML = loginHTML(); return; }
  if (!DASH.state.win) DASH.state.win = windowFor('month');
  var page = DASH.pages[DASH.state.page] || DASH.pages.dash;
  var notice = DASH.state.notice ? '<div class="notice"><a href="#" onclick="DASH.state.notice=&apos;&apos;;render();return false;">&#215;</a>' + esc(DASH.state.notice) + '</div>' : '';
  document.getElementById('root').innerHTML =
    '<div class="stage"><div class="phone">' + statusbarHTML() + '<div class="ph">' +
    headHTML() + notice + emptyHint() +
    '<div class="screen">' + (DASH.state.busy ? '<div class="loading">正在取数…</div>' : page()) + '</div>' +
    footHTML() + '</div></div></div>';
  maybeFixSeries();
}
/* ---------- 跨年区间：接口的逐日曲线用「月-日」当键，跨年会把同一年的数据重复铺满每一年。
   所以跨度 > 366 天时，走势图改成**逐月取数**：先按年探（只探真有数据的年），再对那年逐月取。 ---------- */
function daysBetween(a, b) { var d1 = parseISO(a), d2 = parseISO(b); return Math.round((d2 - d1) / 86400000) + 1; }
function monthlyKeyOf(w) { return w.from + '~' + w.to; }
function maybeFixSeries() {
  if (DASH.state.busy) return;
  var w = DASH.state.win; if (!w) return;
  var t = d('turnover'); if (!t) return;
  var key = monthlyKeyOf(w);
  if (DASH.state.seriesFix === key) return;
  DASH.state.seriesFix = key;
  if (daysBetween(w.from, w.to) <= 366 || Number(t.total_orders) === 0) { DASH.state.monthlySeries = null; return; }
  DASH.state.monthlySeries = { key: key, items: [], building: true };
  buildMonthly(key, w).catch(function (e) { DASH.state.monthlySeries = { key: key, items: [], error: String(e) }; render(); });
}
async function buildMonthly(key, w) {
  var y0 = Number(w.from.slice(0, 4)), y1 = Number(w.to.slice(0, 4));
  var items = [];
  for (var y = y0; y <= y1; y++) {
    var yf = y + '-01-01', yt = y + '-12-31';
    if (yf < w.from) yf = w.from;
    if (yt > w.to) yt = w.to;
    var yr = await apiGet('/reports/turnover?mode=day&date=' + yt + '&date_from=' + yf + '&date_to=' + yt);
    if (!yr.ok || !yr.body || Number(yr.body.total_orders) === 0) continue;
    for (var m = 1; m <= 12; m++) {
      var mm = (m < 10 ? '0' : '') + m;
      var mf = y + '-' + mm + '-01';
      var lastDay = new Date(Date.UTC(y, m, 0)).getUTCDate();
      var mt = y + '-' + mm + '-' + (lastDay < 10 ? '0' : '') + lastDay;
      if (mf < w.from) mf = w.from;
      if (mt > w.to) mt = w.to;
      if (mf > mt) continue;
      var mr = await apiGet('/reports/turnover?mode=day&date=' + mt + '&date_from=' + mf + '&date_to=' + mt);
      if (!mr.ok || !mr.body) continue;
      items.push({ label: y + '-' + mm, amount: mr.body.total_amount, freight: mr.body.total_freight, orders: mr.body.total_orders });
    }
  }
  DASH.state.monthlySeries = { key: key, items: items };
  if (DASH.state.win && monthlyKeyOf(DASH.state.win) === key) render();
}
