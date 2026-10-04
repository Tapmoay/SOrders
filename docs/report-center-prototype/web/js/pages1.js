/* 页面 1：仪表盘 / 营业纵览 / 商品经营 / 司机绩效 */

function failCard(key) {
  var r = DASH.state.data[key];
  if (!r || r.ok) return '';
  return card('接口没通：' + key, '#E53935',
    '<div class="err">HTTP ' + r.status + '<br>' + esc(JSON.stringify(r.body).slice(0, 400)) + '</div>');
}
function dimIfZero(v, cls) { return num(v) ? '' : ' dimv'; }
function sumBy(rows, fn) { var s = 0; rows.forEach(function (r) { var v = num(fn(r)); if (v !== null) s += v; }); return s; }
function daysSince(dateStr) {
  if (!dateStr) return null;
  var a = parseISO(String(dateStr).slice(0, 10));
  var b = new Date();
  return Math.max(0, Math.round((b - a) / 86400000));
}
function excCat(reason) {
  var s = String(reason || '异常');
  var i = s.indexOf('（');
  return i > 0 ? s.slice(0, i) : s;
}

/* ---------------- 仪表盘 ---------------- */
function pageDash() {
  var t = d('turnover'), p = d('profit'), b = d('balances'), tx = d('tax');
  var dr = d('drivers'), ex = d('exceptions'), cs = d('cashSummary');
  var w = DASH.state.win;
  var h = failCard('turnover') + failCard('profit') + failCard('balances');

  h += '<div class="pagehead"><h2>仪表盘</h2><span>' + esc(w.from) + ' ~ ' + esc(w.to) +
    (t && t.period_label ? '（接口给的区间标签：' + esc(t.period_label) + '）' : '') + '</span></div>';

  /* ① 营业额 / 毛利 */
  if (t) {
    var gp = p ? p.gross_profit : null;
    var gpPct = p ? pctOf(p.gross_profit, p.revenue_covered) : null;
    h += '<div class="kpis">' +
      kpi('这一段营业额', money(t.total_amount), ints(t.total_orders) + ' 单送达 · 单均价 ' + money(t.avg_order) +
        ' · 撤销 ' + ints(t.cancelled_orders) + ' 单', '#1E6FFF') +
      kpi('其中赚到的（毛利）', money(gp), p ? ('毛利率 ' + (gpPct === null ? '—' : gpPct + '%') +
        '（毛利 ÷ 参与毛利的收入 ' + money(p.revenue_covered) + '）') : '没取到利润接口', '#00B3A4') +
      '</div>';
  }

  /* ② 还没收回来的钱（时点账） */
  if (b && b.totals) {
    var tt = b.totals, bk = tt.buckets || {};
    var order = ['0_30', '31_60', '61_90', 'over_90'];
    var names = { '0_30': '0-30 天', '31_60': '31-60 天', '61_90': '61-90 天', 'over_90': '90 天以上' };
    var colors = { '0_30': '#00B578', '31_60': '#1E6FFF', '61_90': '#FF9F0A', 'over_90': '#E53935' };
    var tot = num(tt.balance) || 0;
    var segs = order.map(function (k) {
      var v = num(bk[k]) || 0;
      var p2 = tot > 0 ? (v / tot * 100) : 0;
      return '<i style="width:' + p2 + '%;background:' + colors[k] + '" title="' + names[k] + ' ' + money(v) + '"></i>';
    }).join('');
    h += card('还没收回来的钱（时点账 · 到 ' + esc(b.as_of) + ' 为止）', '#FF6B2C',
      '<div class="big">' + money(tt.balance) + '</div>' +
      '<div class="sub">' + ints(tt.debtor_count) + ' 人 · ' + ints(tt.order_count) + ' 张单 —— 这是<b>累计</b>还欠着的钱（时点），不是这一段新欠的。</div>' +
      '<div class="stack">' + segs + '</div>' +
      order.map(function (k) { return kv('<i class="dot" style="background:' + colors[k] + '"></i>' + names[k], money(bk[k])); }).join('') +
      kv('＝ 该收的钱', money(tt.balance), 'tot') +
      kv('预收（客户先给的钱，单列）', money(tt.prepaid)) +
      kv('没挂到名册单位上的', ints(tt.no_unit_count) + ' 人 · ' + money(tt.no_unit_balance)) +
      kv('超信用额度的', ints(tt.over_limit_count) + ' 家', num(tt.over_limit_count) ? 'red' : '') +
      '<div class="kn">四桶之和 = 该收的钱（接口里逐桶给的数，页面不加总）。这一格是<b>到今天为止</b>的账，跟上面「这一段」的营业额不是一回事。</div>');
  }

  /* ③ 要处理的事 */
  var exRows = ex || [];
  var catMap = {};
  exRows.forEach(function (r) {
    var c = excCat(r.exception_reason);
    catMap[c] = (catMap[c] || 0) + 1;
  });
  var owed = 0, owedN = 0;
  (dr && dr.drivers ? dr.drivers : []).forEach(function (r) {
    var v = num(r.freight_owed);
    if (v) { owed += v; owedN++; }
  });
  var past = exRows.filter(function (r) { return String(r.exception_reason).indexOf('逾期') >= 0 || r.delivered_at; });
  var cats = Object.keys(catMap).map(function (k) { return [k, catMap[k]]; }).sort(function (a, c) { return c[1] - a[1]; });
  var top = exRows.slice().sort(function (a, c) { return (daysSince(c.order_date) || 0) - (daysSince(a.order_date) || 0); }).slice(0, 3);
  h += card('要处理的事（异常单按 ' + esc(w.from) + ' ~ ' + esc(w.to) + ' 的下单日筛选）', '#E53935',
    cats.map(function (c) {
      return '<div class="todo" onclick="go(&apos;audit&apos;)"><i class="dot" style="background:#E53935"></i>' +
        esc(c[0]) + '<b>' + c[1] + ' 单</b><em>›</em></div>';
    }).join('') +
    '<div class="todo" onclick="go(&apos;drivers&apos;)"><i class="dot" style="background:#00A2C7"></i>该付司机的钱（还没结的运费）' +
    '<b>' + money(owed) + ' · ' + owedN + ' 人</b><em>›</em></div>' +
    (top.length ? '<div class="kn">拖得最久的三单：</div>' + top.map(function (r) {
      var dd = daysSince(r.order_date);
      return '<div class="todo sm" onclick="go(&apos;audit&apos;)"><span class="tagr">' + esc(excCat(r.exception_reason)) + '</span>' +
        esc(r.order_no) + '<b>' + (dd === null ? '' : '已 ' + dd + ' 天') + '</b><em>›</em></div>';
    }).join('') : '') +
    (past.length ? '<div class="past">已送到但迟到 / 已处理的：' + past.length + ' 单（在「异常与审计」里单列）</div>' : '') +
    '<div class="kn">异常单总数 ' + exRows.length + ' 单（接口 /stats/exception-orders 返回的原文长度）。它只按<b>下单日</b>落在窗口里筛，不是送达日。</div>');

  /* ④ 钱 · 这一段 */
  if (t) {
    var col = num(t.collected) || 0, arr = num(t.arrears_total) || 0;
    var back = col + arr;
    h += card('钱 · 这一段', '#00B578',
      kv('这一段营业额（应收）', money(t.total_amount)) +
      kv('这一段收回来', money(t.collected), 'green') +
      kv('这一段新增挂账', money(t.arrears_total), 'orange') +
      '<div class="kn">接口的两个数相加 = <b>' + money(back) + '</b>，与营业额 ' + money(t.total_amount) +
      (Math.abs(back - (num(t.total_amount) || 0)) < 0.005 ? ' 对得上' : ' <b class="red">对不上</b>') + '（后端的口径：已收 + 挂账 = 营业额，未收款不让营业额变小）。</div>' +
      (cs ? '<div class="kn">现金流水（另一个口径，含非订单的收付）：进 ' + money(cs.income) + ' / 出 ' + money(cs.expense) +
        ' / 净 ' + money(cs.net) + '，共 ' + ints(cs.count) + ' 笔。</div>' : ''));
  }

  /* ⑤ 赚了多少 */
  if (p) {
    h += card('赚了多少 · 这一段', '#00B3A4',
      kv('参与毛利的收入（有成本的那部分）', money(p.revenue_covered)) +
      kv('− 商品成本', '− ' + money(p.cost_total), 'orange') +
      kv('＝ 商品毛利', money(p.gross_profit), 'green tot') +
      kv('− 司机运费（按单应付）', '− ' + money(p.delivery_cost), 'orange') +
      kv('− 期间费用', '− ' + money(p.operating_expense_total), 'orange') +
      kv('− 车辆折旧', '− ' + money(p.depreciation_total), 'orange') +
      kv('＝ 营业利润', money(p.operating_profit), 'tot ' + (num(p.operating_profit) < 0 ? 'red' : 'green')) +
      '<div class="kn">不进毛利、但营业额里仍然有的那一部分：<b>' + money(p.revenue_uncovered) + '</b>' +
      '（' + ints(p.total_lines - p.covered_lines) + ' 行没有进货价）。成本覆盖率 ' +
      ints(p.covered_lines) + ' / ' + ints(p.total_lines) + ' 行。</div>' +
      (p.tax_total ? '<div class="kn">税金及附加（开销里分类名带「税」的）：' + money(p.tax_total) + '</div>' : ''));
  }

  /* ⑥ 税 */
  if (tx) {
    h += card('税 · 这一段（按开票日期）', '#C08A4E',
      kv('销项税（开出去的票）', money(tx.output ? tx.output.tax_amount : null)) +
      kv('进项税（收到的票）', money(tx.input ? tx.input.tax_amount : null), 'green') +
      kv('＝ 本期应交增值税', money(tx.vat_payable), 'tot orange') +
      kv('发票张数', ints(tx.invoices ? tx.invoices.length : 0) + ' 张 · 作废 ' + ints(tx.voided_count) + ' 张') +
      '<div class="kn">增值税是价外税，<b>不进营业利润</b>；' + (tx.output && num(tx.output.untaxed_amount) ?
        '有 ' + money(tx.output.untaxed_amount) + ' 的销项票没填税率，单列在 untaxed 里，没有按默认税率替它猜。' : '这一段没有缺税率的票。') + '</div>');
  }

  /* ⑦ 走势 */
  if (t && t.series && t.series.length) {
    h += card('走势（接口 series 原文）', '#1E6FFF', chart(t.series) +
      '<div class="kn">窗口两端同一天时接口按<b>小时</b>给桶（只给有单的那些小时，不是硬凑 24 个），跨天按<b>天</b>给。各柱之和 = ' + money(sumBy(t.series, function (r) { return r.amount; })) +
      '（营业额 ' + money(t.total_amount) + '）；运费之和 = ' + money(sumBy(t.series, function (r) { return r.freight; })) + '。</div>');
  }

  /* ⑧ 详细报表入口 */
  function tile(e) {
    return '<div class="tile" onclick="go(&apos;' + e[0] + '&apos;)"><b>' + esc(e[1]) + '</b><span>' + esc(e[2]) + '</span></div>';
  }
  h += card('详细报表（点开看细节）', '#8A94A6',
    '<div class="tg">常用（每天都可能点）</div><div class="tiles">' +
    ENTRIES.filter(function (e) { return e[3] === 'often'; }).map(tile).join('') + '</div>' +
    '<div class="tg">偶尔才查（有具体问题时再点）</div><div class="tiles">' +
    ENTRIES.filter(function (e) { return e[3] === 'rarely'; }).map(tile).join('') + '</div>');

  h += notesBlock(['turnover', 'profit', 'balances', 'tax'], '口径（后端随接口一起给的说明）');
  h += rawBlock(['turnover', 'profit', 'balances', 'tax', 'drivers', 'exceptions', 'cashSummary']);
  return h;
}

/* ---------------- 营业纵览 ---------------- */
function pageTurnover() {
  var t = d('turnover');
  var h = failCard('turnover');
  h += '<div class="pagehead"><h2>营业纵览</h2><span>' + esc(DASH.state.win.from) + ' ~ ' + esc(DASH.state.win.to) + '</span></div>';
  if (!t) return h + '<div class="err">没取到数据</div>';
  h += '<div class="kpis">' +
    kpi('营业额（应收）', money(t.total_amount), ints(t.total_orders) + ' 单 · 单均价 ' + money(t.avg_order), '#1E6FFF') +
    kpi('已收', money(t.collected), '收回来 / 应收 = ' + (pctOf(t.collected, t.total_amount) === null ? '—' : pctOf(t.collected, t.total_amount) + '%'), '#00B578') +
    kpi('挂账未收', money(t.arrears_total), '与「已收」相加 = 营业额', '#FF6B2C') +
    kpi('撤销', ints(t.cancelled_orders) + ' 单', '不放进营业额', '#E53935') +
    '</div>';
  h += card('成本与货损', '#00B3A4',
    kv('参与毛利的收入', money(t.cost_covered_amount)) +
    kv('成本合计', money(t.cost_total), 'orange') +
    kv('＝ 毛利（参与毛利的收入 − 成本）', money(num(t.cost_covered_amount) - num(t.cost_total)), 'green tot') +
    kv('算得出成本的行', ints(t.cost_covered_lines) + ' / ' + ints(t.total_lines) + ' 行（' +
      (pctOf(t.cost_covered_lines, t.total_lines) === null ? '—' : pctOf(t.cost_covered_lines, t.total_lines) + '%') + '）') +
    kv('其中用均价的行', ints(t.cost_avg_lines) + ' 行') +
    kv('退回下单快照的行', ints(t.cost_snapshot_lines) + ' 行') +
    kv('司机运费（按单应付）', money(t.total_freight)) +
    kv('货损', ints(t.damage_qty) + ' 件 · ' + money(t.damage_amount), 'red'));
  h += card('挂账未收 · 按单位 TOP5', '#FF6B2C',
    (t.arrears_units && t.arrears_units.length ? t.arrears_units.map(function (u) {
      return kv(esc(u.name), money(u.amount));
    }).join('') : '<div class="dim">这一段没有按单位挂账的单</div>') +
    '<div class="kn">单位是「挂账单位名册」里的那一档；没挂单位的单会落到真人名下（客户欠款页能看到）。</div>');
  h += card('走势', '#1E6FFF', chart(t.series));
  h += card('逐段明细（接口 series 原文）', '#8A94A6',
    '<table class="tb"><tr><th>段</th><th>营业额</th><th>单量</th><th>运费</th></tr>' +
    (t.series || []).map(function (s) {
      return '<tr><td>' + esc(s.label) + '</td><td>' + money(s.amount) + '</td><td>' + ints(s.orders) + '</td><td>' + money(s.freight) + '</td></tr>';
    }).join('') + '</table>');
  h += notesBlock(['turnover']);
  h += rawBlock(['turnover']);
  return h;
}

/* ---------------- 商品经营 ---------------- */
async function drill(name) {
  var w = DASH.state.win;
  var r = await apiGet('/stats/product-drilldown?product_name=' + encodeURIComponent(name) + '&date_from=' + w.from + '&date_to=' + w.to);
  DASH.state.drill = { name: name, ok: r.ok, status: r.status, body: r.body };
  render();
}
function pageProducts() {
  var pr = d('products');
  var h = failCard('products');
  h += '<div class="pagehead"><h2>商品经营</h2><span>' + esc(DASH.state.win.from) + ' ~ ' + esc(DASH.state.win.to) + '</span></div>';
  if (!pr) return h + '<div class="err">没取到数据</div>';
  h += '<div class="kpis">' +
    kpi('商品总金额', money(pr.total_amount), '出库 ' + ints(pr.total_qty) + ' 件 · ' + ints((pr.items || []).length) + ' 个商品', '#8455E6') +
    kpi('商品毛利（参与毛利的行）', money(num(pr.cost_covered_amount) - num(pr.cost_total)),
      '成本 ' + money(pr.cost_total) + ' · 覆盖率 ' + ints(pr.cost_covered_lines) + '/' + ints(pr.total_lines) + ' 行', '#00B3A4') +
    kpi('货损', money(pr.damage_amount), ints(pr.damage_qty) + ' 件', '#E53935') +
    '</div>';
  var items = (pr.items || []).slice().sort(function (a, b) { return (num(b.amount) || 0) - (num(a.amount) || 0); });
  h += card('逐商品（按金额从大到小）', '#8455E6',
    '<table class="tb"><tr><th>商品</th><th>数量</th><th>金额</th><th>成本</th><th>毛利</th><th>单数</th><th></th></tr>' +
    items.map(function (it) {
      var gp = num(it.covered_amount) - num(it.cost);
      return '<tr><td>' + esc(it.product_name) + '</td><td>' + ints(it.qty) + '</td><td>' + money(it.amount) + '</td><td>' + money(it.cost) +
        '</td><td class="' + (gp < 0 ? 'red' : 'green') + '">' + money(gp) + '</td><td>' + ints(it.order_count) +
        '</td><td><a href="#" onclick="drill(&apos;' + esc(it.product_name) + '&apos;);return false;">下钻</a></td></tr>';
    }).join('') + '</table>' +
    '<div class="kn">毛利 = 该商品「参与毛利的收入」− 成本；某个商品算不出成本的行不进它的毛利（covered_lines 逐商品给了）。</div>');
  if (DASH.state.drill) {
    var dd = DASH.state.drill;
    h += card('下钻：' + esc(dd.name) + '（/stats/product-drilldown）', '#6950F5',
      dd.ok ? ('<table class="tb"><tr><th>单号</th><th>日期</th><th>状态</th><th>货主</th><th>数量</th><th>金额</th></tr>' +
        dd.body.map(function (r) {
          return '<tr><td>' + esc(r.order_no) + '</td><td>' + esc(r.order_date) + '</td><td>' + esc(r.status) + '</td><td>' + esc(r.shipper_name || '') +
            '</td><td>' + ints(r.quantity) + '</td><td>' + money(r.line_total) + '</td></tr>';
        }).join('') + '</table>') : ('<div class="err">HTTP ' + dd.status + '</div>'));
  }
  h += notesBlock(['products']);
  h += rawBlock(['products']);
  return h;
}

/* ---------------- 司机绩效 ---------------- */
function pageDrivers() {
  var dr = d('drivers');
  var h = failCard('drivers');
  h += '<div class="pagehead"><h2>司机绩效</h2><span>' + esc(DASH.state.win.from) + ' ~ ' + esc(DASH.state.win.to) + '</span></div>';
  if (!dr) return h + '<div class="err">没取到数据</div>';
  var rows = dr.drivers || [];
  var owed = sumBy(rows, function (r) { return r.freight_owed; });
  var owedN = rows.filter(function (r) { return num(r.freight_owed); }).length;
  h += '<div class="kpis">' +
    kpi('还该付司机的运费（总额）', money(owed), owedN + ' 个司机有未结运费 · 这是「已结以外」的全部', '#00A2C7') +
    kpi('这一段跑了的司机', ints(rows.length) + ' 人', '完成单量合计 ' + ints(sumBy(rows, function (r) { return r.completed_count; })) + ' 单', '#1E6FFF') +
    '</div>';
  h += card('逐司机（接口原文）', '#00A2C7',
    '<table class="tb"><tr><th>司机</th><th>完成单</th><th>准时率</th><th>平均送达</th><th>拍照率</th><th>计费方式</th><th>待结运费</th></tr>' +
    rows.map(function (r) {
      var ot = r.on_time_rate === null || r.on_time_rate === undefined ? '<span class="dim">样本还太少</span>' : (Math.round(r.on_time_rate * 1000) / 10) + '%';
      var av = r.avg_delivery_seconds === null || r.avg_delivery_seconds === undefined ? '<span class="dim">—</span>' : (mins(r.avg_delivery_seconds) + ' 分钟');
      return '<tr><td>' + esc(r.driver_name) + '</td><td>' + ints(r.completed_count) + '</td><td>' + ot + '</td><td>' + av +
        '</td><td>' + (r.photo_upload_rate === null || r.photo_upload_rate === undefined ? '—' : (Math.round(r.photo_upload_rate * 1000) / 10) + '%') +
        '</td><td>' + esc(r.billing_mode || '—') + '</td><td>' + (r.freight_owed === null || r.freight_owed === undefined ? '<span class="dim">工资制不按单结</span>' : money(r.freight_owed)) + '</td></tr>';
    }).join('') + '</table>' +
    '<div class="kn">准时率接口没样本时给 <b>null</b>，⛔ 不是 0 —— 页面也不许把「没数据」画成 0%。</div>');
  h += notesBlock(['drivers']);
  h += rawBlock(['drivers']);
  return h;
}

DASH.pages.dash = pageDash;  /* 已被 js/dash2.js 里的 pageDash2 覆盖（钱 + 经营状态 + 建议的 v2 版） */
DASH.pages.turnover = pageTurnover;
DASH.pages.products = pageProducts;
DASH.pages.drivers = pageDrivers;
