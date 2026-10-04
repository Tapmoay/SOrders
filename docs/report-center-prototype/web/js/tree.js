/* 五张表（利润表 / 资产负债表 / 现金流量表 / 运营分析表 / 关键指标表）+ 树状下钻。
   第一页按 5 个标准组织，点进去一层层细到订单。只加页面，不动 core.js 的取数，也不动 App。 */
DASH.pnode = DASH.pnode || {};
DASH.narg = null;
if (!DASH.state.trail) DASH.state.trail = [{ id: 'dash', arg: null }];
function tnode(id, label, build) { DASH.pages[id] = build; DASH.pnode[id] = label; }
function enc(x) { return encodeURIComponent(String(x === null || x === undefined ? '' : x)).replace(/'/g, '%27'); }
function goNode(id, arg) {
  if (DASH.state.busy) return;
  var top = DASH.state.trail[DASH.state.trail.length - 1];
  if (!top || top.id !== DASH.state.page) DASH.state.trail.push({ id: DASH.state.page, arg: DASH.narg });
  DASH.narg = (arg === undefined ? null : arg);
  DASH.state.narg = DASH.narg;
  go(id);
}
function goBack() {
  var t = DASH.state.trail;
  if (t.length > 1) t.pop();
  var cur = t[t.length - 1] || { id: 'dash', arg: null };
  DASH.narg = cur.arg; DASH.state.narg = cur.arg;
  go(cur.id);
}
function goCrumb(i) {
  var t = DASH.state.trail;
  if (i < 0 || i >= t.length) return;
  t.length = i + 1;
  DASH.narg = t[i].arg; DASH.state.narg = t[i].arg;
  go(t[i].id);
}
function crumb() {
  var all = DASH.state.trail, start = Math.max(0, all.length - 4);
  var t = all.slice(start), out = [];
  out.push('<a href="#" onclick="goCrumb(' + start + ');return false;">五张表</a>');
  for (var i = 1; i < t.length; i++) {
    var id = t[i].id;
    if (id === 'dash') continue;
    out.push('<span class="cs">&#8250;</span><a href="#" onclick="goCrumb(' + (start + i) + ');return false;">' + esc(DASH.pnode[id] || DASH.pname[id] || id) + '</a>');
  }
  return '<div class="crumb">' + out.join('') + '</div>';
}
/* 可点的一行：标签 / 值 / 备注 / 去哪 */
function nrow(label, value, cls, node, arg, note) {
  var click = node ? ' onclick="goNode(&apos;' + node + '&apos;,&apos;' + enc(arg === undefined ? '' : arg) + '&apos;)"' : '';
  return '<div class="trow' + (node ? ' go' : '') + '"' + click + '>' +
    '<span class="tl">' + esc(label) + (note ? '<i class="tn">' + note + '</i>' : '') + '</span>' +
    '<span class="tv ' + (cls || '') + '">' + value + (node ? '<i class="ta">&#8250;</i>' : '') + '</span></div>';
}
/* 五张表的一行（大卡） */
function st5(n, name, q, main, sub, node) {
  return '<div class="st5" onclick="goNode(&apos;' + node + '&apos;)">' +
    '<div class="s5h"><span class="s5n">' + n + '</span><b>' + esc(name) + '</b><span class="s5q">' + esc(q) + '</span><em class="ta">&#8250;</em></div>' +
    '<div class="s5m">' + main + '</div>' +
    '<div class="s5s">' + sub + '</div></div>';
}
/* 异步取一条结果（用 DASH.cache 缓存，回来后重画） */
DASH.cache = DASH.cache || {};
function loadInto(key, path) {
  if (DASH.cache[key]) return;
  DASH.cache[key] = 'loading';
  apiGet(path).then(function (r) { DASH.cache[key] = r; render(); }, function () { DASH.cache[key] = { ok: false, status: 0, body: null }; render(); });
}
function loadingCard() { return card('载入中', '#8A94A6', '<div class="kn">正在向接口取这一层的数……</div>'); }
function sumOf(arr, f) { var s = 0; (arr || []).forEach(function (x) { s += num(f(x)) || 0; }); return s; }
function topOf(arr, f) { var b = null, bv = -1e18; (arr || []).forEach(function (x) { var v = num(f(x)) || 0; if (v > bv) { bv = v; b = x; } }); return b; }
function driverRows() { var b = d('drivers'); return (b && b.drivers) || []; }
function shipperRows() { var b = d('shippers'); return (b && (b.shippers || b.rows)) || []; }
function owedTotal() { var o = 0, n = 0; driverRows().forEach(function (r) { if (r.freight_owed !== null && r.freight_owed !== undefined) { o += num(r.freight_owed) || 0; n++; } }); return { owed: o, n: n }; }
function prodItems() { var b = d('products'); return (b && b.items) || []; }
function pctStr(a, b) { var p = pctOf(a, b); return p === null ? '—' : p + '%'; }
DASH.pname = {};
ENTRIES.forEach(function (e) { DASH.pname[e[0]] = e[1]; });
/* ---------------- 第一页：五张表 ---------------- */
function pageHome5() {
  var T = d('turnover'), P = d('profit'), B = d('balances'), V = d('vehicle'), CS = d('cashSummary');
  var ow = owedTotal();
  var h = '';
  h += card('五张表（这一段按会计的五个标准看）', '#1E6FFF',
    st5(1, '利润表', '赚了多少钱', P ? money(P.operating_profit) : '—',
      '商品毛利 ' + money(P && P.gross_profit) + '；净利要减所得税 —— 这一项接口里还没有', 't-profit') +
    st5(2, '资产负债表', '家底多少、欠多少', B ? money(B.totals.balance) : '—',
      '别人欠我 ' + money(B && B.totals.balance) + '（' + ints(B && B.totals.debtor_count) + ' 人）；我欠司机 ' + money(ow.owed) + '（' + ints(ow.n) + ' 人）；库存 ' + stockSumHome() + '（估算）；欠供应商 ' + supSumHome(), 't-balance') +
    st5(3, '现金流量表', '钱从哪来、花到哪去', CS ? money(CS.net) : '—',
      '进来 ' + money(CS && CS.income) + ' / 出去 ' + money(CS && CS.expense) + ' · ' + ints(CS && CS.count) + ' 笔', 't-cash') +
    st5(4, '运营分析表', '分产品/客户/车辆/司机，哪里赚哪里亏', P ? money(P.gross_profit) : '—',
      '商品 ' + ints(prodItems().length) + ' 种 · 客户 ' + ints(shipperRows().length) + ' 个 · 车 ' + ints(V && V.vehicle_count) + ' 台 · 司机 ' + ints(driverRows().length) + ' 人', 't-ops') +
    st5(5, '关键指标表', '毛利率、成本率、周转、保本点', P ? pctStr(P.gross_profit, P.revenue_covered) : '—',
      '毛利率（÷ 有成本的收入）· 收款率 ' + (T ? pctStr(T.collected, T.total_amount) : '—') + ' · 司机运费率 ' + (T && P ? pctStr(P.delivery_cost, T.total_amount) : '—'), 't-kpi'));
  var rows = dashHealth(T, P, B, d('drivers'), CS);
  h += card('经营状态（这一段怎么样）', '#7C4DFF',
    '<div class="verdict">' + esc(dashVerdict(rows, T, P)) + '</div>' +
    rows.map(function (r) { return '<div class="hl ' + (r.lv || '') + '"><div class="hlh"><i></i><b>' + esc(r.k) + '</b><em>' + esc(r.v) + '</em></div><div class="hld">' + esc(r.d) + '</div></div>'; }).join(''));
  var adv = dashAdvice(T, P, B, d('drivers'));
  if (adv.length) {
    h += card('建议（按这一段的数据说的）', '#FF9F0A',
      adv.map(function (a, i) {
        return '<div class="adv"><div class="advh"><span class="n">' + (i + 1) + '</span>' + esc(a.t) + '</div>' +
          '<div class="advd">' + esc(a.d) + '</div>' +
          '<div class="advb">' + esc(a.b) + ' · <a href="#" onclick="go(&apos;' + a.go + '&apos;);return false;">去看' + esc(a.goName) + ' &#8250;</a></div></div>';
      }).join('') + '<div class="kn">建议只是把数据里最该先看的地方指出来，怎么处理还是你定。</div>');
  }
  function tile(e) { return '<div class="tile" onclick="go(&apos;' + e[0] + '&apos;)"><b>' + esc(e[1]) + '</b><span>' + esc(e[2]) + '</span></div>'; }
  h += card('详细报表（老页面也留着，点开看细节）', '#8A94A6',
    '<div class="tg">常用（每天都可能点）</div><div class="tiles">' + ENTRIES.filter(function (e) { return e[3] === 'often'; }).map(tile).join('') + '</div>' +
    '<div class="tg">偶尔才查（有具体问题时再点）</div><div class="tiles">' + ENTRIES.filter(function (e) { return e[3] === 'rarely'; }).map(tile).join('') + '</div>');
  h += notesBlock(['turnover', 'profit', 'balances', 'tax'], '口径（后端随接口一起给的说明）');
  h += rawBlock(['turnover', 'profit', 'balances', 'tax', 'cashSummary']);
  return h;
}
tnode('dash', '报表中心', pageHome5);

/* 覆盖壳的标题栏：树节点也用返回（回上一层，不丢面包屑），标题用节点名 */
function decodeURIComponentSafe(s) { try { return decodeURIComponent(String(s)); } catch (e) { return String(s); } }
function headHTML() {
  var page = DASH.state.page;
  var isDash = page === 'dash';
  var left = isDash ? '<span class="ib ghost"></span>'
    : '<button class="ib" onclick="goBack()">&#8249; 返回</button>';
  var right = EXPORT_KIND[page]
    ? '<button class="ib" onclick="doExport()">导出</button>'
    : '<button class="ib" onclick="loadAll(DASH.state.win)">刷新</button>';
  var w = DASH.state.win;
  var name = DASH.pnode[page] || DASH.pname[page] || page;
  var tr = DASH.state.trail, last = tr[tr.length - 1];
  var curArg = (last && last.id === page) ? last.arg : (DASH.state.narg || DASH.narg);
  if (curArg && isNaN(Number(curArg)) && !(DASH.pnoarg && DASH.pnoarg[page])) { name = name + ' · ' + decodeURIComponentSafe(curArg); }
  return '<div class="pstick"><div class="pbar">' + left +
    '<div class="ptitle">' + esc(name) +
    '<span class="psub">' + esc(w.label) + ' · ' + esc(w.from) + ' ~ ' + esc(w.to) + '</span></div>' + right + '</div>' + pPills() + '</div>';
}

/* 首页那行摘要用的小件（数据在 stock.js 里算） */
function stockSumHome() { var v = (typeof stockValue === 'function') ? stockValue() : null; return v ? money(v.sum) : '—'; }
function supSumHome() { var u = (typeof supUnpaid === 'function') ? supUnpaid() : null; return u ? money(u.sum) : '—'; }
