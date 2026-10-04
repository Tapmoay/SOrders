/* 观感重做（最后加载）：时间药丸+下拉、五张表合成一卡（图标在上、数字带颜色语义、配图）、少解释 */
function closeTime() { var e = document.getElementById('tw'); if (e) e.className = 'tp'; }
function toggleTime() { var e = document.getElementById('tw'); if (!e) return; e.className = (e.className.indexOf('open') >= 0) ? 'tp' : 'tp open'; }
function pickWin(k) { closeTime(); setWin(k); }
function pickRange(a, b, label) { closeTime(); setRange(a, b, label); }
function lastWeekWin() {
  var t = new Date(), wd = (t.getDay() + 6) % 7;
  var s = new Date(t.getFullYear(), t.getMonth(), t.getDate() - wd - 7);
  var e = new Date(s.getFullYear(), s.getMonth(), s.getDate() + 6);
  return { from: iso(s), to: iso(e), label: '上周' };
}
var CAL = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" d="M7 3v3M17 3v3M3.8 9.6h16.4M5.6 5.4h12.8c1 0 1.6.7 1.6 1.6v11.4c0 1-.6 1.6-1.6 1.6H5.6c-1 0-1.6-.7-1.6-1.6V7c0-.9.6-1.6 1.6-1.6Z"/><path fill="currentColor" d="M7.4 12h2v2h-2zM11 12h2v2h-2zM14.6 12h2v2h-2zM7.4 15.6h2v2h-2zM11 15.6h2v2h-2z"/></svg>';
function pPills() {
  var w = DASH.state.win, lw = lastWeekWin();
  function item(key, name) { var on = w.key === key; return '<button class="tmi' + (on ? ' on' : '') + '" onclick="pickWin(&apos;' + key + '&apos;)">' + name + (on ? '<i>当前</i>' : '') + '</button>'; }
  function itemR(from, to, name) { var on = (w.from === from && w.to === to); return '<button class="tmi' + (on ? ' on' : '') + '" onclick="pickRange(&apos;' + from + '&apos;,&apos;' + to + '&apos;,&apos;' + name + '&apos;)">' + name + (on ? '<i>当前</i>' : '') + '</button>'; }
  var quick = [['2026-09-25','2026-09-25','9-25'],['2026-09-01','2026-09-30','2026-09'],['2026-08-01','2026-08-31','2026-08'],['2026-07-01','2026-07-31','2026-07'],['2026-06-01','2026-06-30','2026-06']]
    .map(function (r) { return itemR(r[0], r[1], r[2]); }).join('');
  return '<div class="tp" id="tw">' +
    '<button class="tpill" onclick="toggleTime()">' + CAL + '<b>' + esc(w.label) + '</b><i class="car"></i></button>' +
    '<div class="tmenu">' +
      '<div class="tmh">按区间看</div><div class="tmg">' +
      item('today','今天') + item('week','本周') + itemR(lw.from, lw.to, '上周') + item('month','本月') + item('last','上月') + item('quarter','本季') + item('year','本年') + item('all','全部') +
      '</div>' +
      '<div class="tmh">自己选起止</div><div class="tmr"><input id="f_from" type="date" value="' + esc(w.from) + '"><span class="tilde">~</span><input id="f_to" type="date" value="' + esc(w.to) + '"><button class="tgo" onclick="setWin(&apos;custom&apos;)">用这段</button></div>' +
      '<div class="tmh">真库里有数据的窗口</div><div class="tmg">' + quick + '</div>' +
      '<div class="tmn">现在看的是 ' + esc(w.from) + ' ~ ' + esc(w.to) + '（' + esc(w.label) + '）</div>' +
    '</div></div>';
}
/* ---------- 小件 ---------- */
function mb(label, val, max, cls, note) {
  var v = num(val) || 0;
  var pct = max ? Math.max(3, Math.round(Math.abs(v) / max * 100)) : 0;
  return '<div class="mrow" title="' + esc(note || (label + ' ' + money(val))) + '"><span class="ml">' + label + '</span>' +
    '<span class="mb"><i class="' + cls + '" style="width:' + pct + '%"></i></span>' +
    '<span class="mv ' + cls + '">' + money(val) + '</span></div>';
}
function pb(label, text, pct, cls, note) {
  var p = Math.max(2, Math.min(100, Math.round(pct || 0)));
  return '<div class="mrow" title="' + esc(note || label) + '"><span class="ml">' + label + '</span>' +
    '<span class="mb"><i class="' + cls + '" style="width:' + p + '%"></i></span>' +
    '<span class="mv ' + cls + '">' + text + '</span></div>';
}
function chipT(t, cls) { return '<span class="chip ' + (cls || 'b') + '">' + t + '</span>'; }
function tone(v, good, warn) { if (v === null || v === undefined) return 'b'; return (v >= good) ? 'g' : ((v >= warn) ? 'o' : 'r'); }
function toneRev(v, good, warn) { if (v === null || v === undefined) return 'b'; return (v <= good) ? 'g' : ((v <= warn) ? 'o' : 'r'); }
/* ---------- 图标（五张表各一个） ---------- */
var IC = {
  trend: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l5-5 3 3 6-6"/><path d="M15 9h4v4"/></svg>',
  wallet: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5A2.5 2.5 0 0 1 5.5 6H18a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5.5A2.5 2.5 0 0 1 3 16.5z"/><path d="M16.2 12.6h2.6"/></svg>',
  flow: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9h11l-3.2-3.2"/><path d="M20 15H9l3.2 3.2"/></svg>',
  pie: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5v8.5h8.5"/><path d="M20.4 14A8.5 8.5 0 1 1 10 3.6"/></svg>',
  target: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.4"/><circle cx="12" cy="12" r="3.6"/></svg>'
};
function blk(ic, tone, title, sub, numTxt, numCls, inner, node) {
  return '<div class="blk" onclick="goNode(&apos;' + node + '&apos;)">' +
    '<div class="blkh"><span class="icn ' + tone + '">' + ic + '</span><b>' + title + '</b><span class="sub">' + sub + '</span>' +
    '<em class="num ' + numCls + '">' + numTxt + '</em><i class="chev">&#8250;</i></div>' +
    inner + '</div>';
}
/* ---------- 首页 ---------- */
function pageHomeLook() {
  var T = d('turnover'), P = d('profit'), B = d('balances'), V = d('vehicle'), CS = d('cashSummary');
  var ow = owedTotal(), SV = stockValue(), SU = supUnpaid();
  var gross = num(P && P.gross_profit) || 0, deliv = num(P && P.delivery_cost) || 0, opex = num(P && P.operating_expense_total) || 0;
  var op = num(P && P.operating_profit) || 0, rev = num(T && T.total_amount) || 0;
  var grossMax = Math.max(gross, deliv, opex, 1);
  var gRate = pctOf(P && P.gross_profit, P && P.revenue_covered), oRate = pctOf(P && P.operating_profit, T && T.total_amount);
  var collect = pctOf(T && T.collected, T && T.total_amount), cover = pctOf(P && P.covered_lines, P && P.total_lines);
  var owe = num(B && B.totals.balance) || 0, stock = num(SV && SV.sum) || 0, owedDrv = num(ow && ow.owed) || 0, oweSup = num(SU && SU.sum) || 0;
  var balMax = Math.max(owe, stock, owedDrv, oweSup, 1);
  var inc = num(CS && CS.income) || 0, exp = num(CS && CS.expense) || 0, net = num(CS && CS.net) || 0;
  var cashMax = Math.max(inc, exp, 1);
  var costDaily = (num(P && P.cost_total) || 0) / (dashDays() || 1), invDays = costDaily ? stock / costDaily : null;
  var bed = gRate ? (opex + (num(P.depreciation_total) || 0)) / (gRate / 100) : null;
  var mos = (bed && rev) ? Math.round((rev - bed) / rev * 100) : null;
  var empty = !(T && num(T.total_orders));
  function tn(c) { return empty ? 'b' : c; }
  var rows = dashHealth(T, P, B, d('drivers'), CS);
  var vt = (T && num(T.total_orders)) ? dashVerdict(rows, T, P).replace(/（[^）]*项[^）]*）$/, '')
    : ('「' + DASH.state.win.label + '」这一段里没有已送达的单，下面是空数；别人还欠着 ' + money(owe) + '。');
  var b1 = blk(IC.trend, 'blue', '利润表', '赚没赚钱', money(P && P.operating_profit), tn(op < 0 ? 'r' : 'g'),
    mb('商品毛利', gross, grossMax, 'g') + mb('司机运费', deliv, grossMax, 'o') + mb('期间费用', opex, grossMax, 'o') +
    '<div class="chips">' + chipT('毛利率 ' + pctStr(P && P.gross_profit, P && P.revenue_covered), tone(gRate, 30, 20)) +
    chipT('营业利润率 ' + pctStr(P && P.operating_profit, T && T.total_amount), tone(oRate, 8, 0)) + '</div>', 't-profit');
  var b2 = blk(IC.wallet, 'purple', '资产负债表', '欠多少', money(owe), 'o',
    mb('别人欠我', owe, balMax, 'o') + mb('库存', stock, balMax, 'b') + mb('我欠司机', owedDrv, balMax, 'r') +
    '<div class="chips">' + chipT('欠款人 ' + ints(B && B.totals.debtor_count) + ' 人 · ' + ints(B && B.totals.order_count) + ' 张单', 'o') +
    chipT('超额度 ' + ints(B && B.totals.over_limit_count) + ' 家', (num(B && B.totals.over_limit_count) ? 'r' : 'b')) +
    chipT('欠供应商 ' + money(SU && SU.sum), (oweSup > 0 ? 'o' : 'b')) + '</div>', 't-balance');
  var b3 = blk(IC.flow, 'green', '现金流量表', '进出多少', money(CS && CS.net), tn(net < 0 ? 'r' : 'g'),
    mb('进来', inc, cashMax, 'g') + mb('出去', exp, cashMax, 'o') +
    '<div class="chips">' + chipT((net < 0 ? '净流出 ' : '净流入 ') + money(Math.abs(net)), (net < 0 ? 'r' : 'g')) +
    chipT(ints(CS && CS.count) + ' 笔流水', 'b') + '</div>', 't-cash');
  var b4 = blk(IC.pie, 'orange', '运营分析表', '哪赚哪亏', money(P && P.gross_profit), tn('g'),
    pb('成本算得出来', (cover === null ? '—' : cover + '%'), cover || 0, tone(cover, 95, 85), '有进货价的行 ÷ 全部行') +
    '<div class="chips">' + chipT('商品 ' + ints(prodItems().length) + ' 种', 'b') + chipT('客户 ' + ints(shipperRows().length) + ' 个', 'b') +
    chipT('车 ' + ints(V && V.vehicle_count) + ' 台', 'b') + chipT('司机 ' + ints(driverRows().length) + ' 人', 'b') + '</div>', 't-ops');
  var b5 = blk(IC.target, 'teal', '关键指标表', '几个比例', (gRate === null ? '—' : gRate + '%'), tn(tone(gRate, 30, 20)),
    pb('毛利率', (gRate === null ? '—' : gRate + '%'), gRate || 0, tone(gRate, 30, 20)) +
    pb('收款率', (collect === null ? '—' : collect + '%'), collect || 0, tone(collect, 85, 60)) +
    pb('成本覆盖', (cover === null ? '—' : cover + '%'), cover || 0, tone(cover, 95, 85)) +
    '<div class="chips">' + chipT('库存周转 ' + (invDays === null ? '—' : Math.round(invDays) + ' 天'), toneRev(invDays, 30, 90)) +
    chipT('保本营业额 ' + (bed ? money(bed) : '—'), 'b') +
    chipT('安全边际 ' + (mos === null ? '—' : mos + '%'), (mos === null ? 'b' : (mos >= 0 ? 'g' : 'r'))) + '</div>', 't-kpi');
  var h = '';
  h += card('经营总览', '#1E6FFF',
    '<div class="vline">' + esc(vt) + '</div>' + b1 + b2 + b3 + b4 + b5 +
    '<details class="more"><summary>看这 6 项的明细</summary>' +
    rows.map(function (r) { return '<div class="hl ' + (r.lv || '') + '"><div class="hlh"><i></i><b>' + esc(r.k) + '</b><em>' + esc(r.v) + '</em></div><div class="hld">' + esc(r.d) + '</div></div>'; }).join('') +
    '</details>');
  var adv = dashAdvice(T, P, B, d('drivers'));
  if (adv.length) {
    h += card('建议', '#FF9F0A', adv.map(function (a, i) {
      return '<div class="adv"><div class="advh"><span class="n">' + (i + 1) + '</span>' + esc(a.t) + '</div>' +
        '<div class="advd">' + esc(a.d) + ' <a href="#" onclick="go(&apos;' + a.go + '&apos;);return false;">去看 &#8250;</a></div></div>';
    }).join(''));
  }
  h += card('走势', '#34C759', chart(T ? T.series : []));
  var top3 = (B && B.rows ? B.rows.slice().sort(function (a, b) { return (num(b.balance) || 0) - (num(a.balance) || 0); }).slice(0, 3) : []);
  h += card('要盯的事', '#FF3B30',
    nrow('该付司机的钱', money(ow && ow.owed) + ' · ' + ints(ow && ow.n) + ' 人', 'orange', 'drivers', '', '') +
    nrow('超信用额度的客户', ints(B && B.totals.over_limit_count) + ' 家', (num(B && B.totals.over_limit_count) ? 'red' : ''), 't-balance', '', '') +
    nrow('欠得最多的三个人', (top3.length ? esc(top3[0].name) + ' ' + money(top3[0].balance) + ' 等 ' + top3.length + ' 人' : '—'), 'orange', 'p-cust', '', '') +
    nrow('异常单', ints(d('exceptions') ? d('exceptions').length : 0) + ' 单', (d('exceptions') && d('exceptions').length ? 'red' : ''), 'audit', '', ''));
  function tile(e) { return '<div class="tile" onclick="go(&apos;' + e[0] + '&apos;)"><b>' + esc(e[1]) + '</b><span>' + esc(e[2]) + '</span></div>'; }
  h += '<section class="card fold"><details><summary>其它入口（按老页面看，11 个）</summary>' +
    '<div class="tg">常用</div><div class="tiles">' + ENTRIES.filter(function (e) { return e[3] === 'often'; }).map(tile).join('') + '</div>' +
    '<div class="tg">偶尔才查</div><div class="tiles">' + ENTRIES.filter(function (e) { return e[3] === 'rarely'; }).map(tile).join('') + '</div></details></section>';
  h += notesBlock(['turnover', 'profit', 'balances', 'tax'], '口径');
  h += rawBlock(['turnover', 'profit', 'balances', 'tax', 'cashSummary']);
  return h;
}
DASH.pages['dash'] = pageHomeLook;
DASH.pnode['dash'] = '报表中心';
/* 口径说明一律收起来：页面要清爽，较真的时候再点开 */
var _notesBlock = notesBlock;
notesBlock = function (names, title) {
  var one = _notesBlock(names, title);
  if (!one) return '';
  return '<section class="card fold"><details><summary>口径说明（点开看）</summary>' + one + '</details></section>';
};