/* 五张表的第二层：每一张点进去是什么。依赖 tree.js 里的 tnode/nrow/crumb。 */

/* ===================== 1. 利润表 ===================== */
tnode('t-profit', '利润表', function () {
  var P = d('profit'), T = d('turnover'), V = d('vehicle');
  var h = crumb();
  if (!P) return h + failCard('profit');
  var gm = pctStr(P.gross_profit, P.revenue_covered);
  h += '<div class="kpis">' +
    kpi('这一段营业利润', money(P.operating_profit), '利润率 ' + pctStr(P.operating_profit, P.revenue_total) + '（÷ 这一段营业额 ' + money(P.revenue_total) + '）', num(P.operating_profit) < 0 ? '#E53935' : '#00B578') +
    kpi('商品毛利', money(P.gross_profit), '毛利率 ' + gm + '（÷ 有成本的收入 ' + money(P.revenue_covered) + '）', '#00B3A4') +
    '</div>';
  h += card('利润表（点每一行，看它由哪些东西组成）', '#00B3A4',
    nrow('营业收入（这一段营业额）', money(P.revenue_total), '', 'p-rev', '', '按商品 / 客户 / 天拆') +
    nrow('− 商品成本', '− ' + money(P.cost_total), 'orange', 'p-cost', '', '逐商品看成本与毛利') +
    nrow('＝ 商品毛利', money(P.gross_profit), 'green tot', 'p-cost', '', '毛利率 ' + gm) +
    nrow('− 司机运费（按单应付）', '− ' + money(P.delivery_cost), 'orange', 'p-drv', '', '按司机看谁拉得多、还欠多少') +
    nrow('− 期间费用', '− ' + money(P.operating_expense_total), 'orange', 'p-exp', '', '按类目看钱花在哪') +
    nrow('− 车辆折旧', '− ' + money(P.depreciation_total), 'orange', 'p-dep', '', '按车看折旧算不算得出来') +
    nrow('＝ 营业利润', money(P.operating_profit), 'tot ' + (num(P.operating_profit) < 0 ? 'red' : 'green'), 't-kpi', '', '接口给的等式，页面不重算') +
    nrow('＋ 增值税（价外税，不进利润）', money(P.vat_payable), 'orange', 't-tax', '', '单独一张税表') +
    nrow('− 所得税', '<span class="dim">接口里没有</span>', '', '', '', '要算「净利」就得先有这一项') +
    '<div class="kn">接口自己给的等式：参与毛利的收入 − 商品成本 = 毛利；毛利 − 司机运费 − 期间费用 − 折旧 = 营业利润。这一段有 <b>' + money(P.revenue_uncovered) + '</b> 的收入没有进货价（' + ints(num(P.total_lines) - num(P.covered_lines)) + ' 行），所以毛利只覆盖 ' + ints(P.covered_lines) + ' / ' + ints(P.total_lines) + ' 行。</div>');
  if (V) {
    h += card('按车看同一笔钱（换个切法，不重复扣）', '#546E7A',
      nrow('车上的开销（已含在期间费用里）', money(V.expense_total), 'orange', 'vehicle', '', '油/修/停车…逐车逐笔，别再加一遍') +
      nrow('挂靠司机的配送成本（已含在司机运费里）', money(V.delivery_cost_total), 'orange', 'vehicle', '', '按车归集的同一笔运费') +
      nrow('＝ 这一段车辆总成本', money(V.total_cost), 'tot', 'vehicle', '', ints(V.vehicle_count) + ' 台车 · 折旧算得全的 ' + ints(V.covered_count) + ' 台') +
      '<div class="kn">这一张是<b>换一个角度看同一笔钱</b>：车上的开销已经在「期间费用」里、挂靠司机的运费已经在「司机运费」里，所以利润表里不能再扣一遍。</div>');
  }
  h += notesBlock(['profit'], '口径（后端随接口一起给的说明）');
  h += rawBlock(['profit']);
  return h;
});

/* ---- 营业收入怎么拆 ---- */
tnode('p-rev', '营业收入由什么组成', function () {
  var T = d('turnover'), PR = d('products'), S = shipperRows();
  var h = crumb();
  var topC = topOf(S, function (r) { return r.total_amount; });
  h += card('三个切法（各切各的，不互相加减）', '#1E6FFF',
    nrow('按商品（' + ints(prodItems().length) + ' 种）', money(PR ? PR.total_amount : null), '', 'p-cost', '', '点进去逐商品看金额/成本/毛利') +
    nrow('按客户（' + ints(S.length) + ' 个货主）', money(sumOf(S, function (r) { return r.total_amount; })), '', 'p-cust', '', topC ? '买得最多：' + esc(topC.shipper_name) + ' ' + money(topC.total_amount) : '') +
    nrow('按天（' + ints(T && T.series ? T.series.length : 0) + ' 个点）', money(T ? T.total_amount : null), '', 'p-day', '', '接口 series 原文，一柱一天') +
    '<div class="kn">按客户那一列是 <b>line_total 逐客户相加</b>（接口自己说的口径），与营业额的差是没归到货主名下的部分；页面不替它补。</div>');
  h += rawBlock(['turnover', 'products', 'shippers']);
  return h;
});

tnode('p-day', '按天看营业额', function () {
  var T = d('turnover');
  var h = crumb();
  if (!T) return h + failCard('turnover');
  h += card('走势', '#1E6FFF', chart(T.series) +
    '<div class="kn">各柱之和 = ' + money(sumOf(T.series, function (r) { return r.amount; })) + '（营业额 ' + money(T.total_amount) + '）；运费之和 = ' + money(sumOf(T.series, function (r) { return r.freight; })) + '。</div>');
  h += card('逐天明细（接口 series 原文）', '#8A94A6', flatTable(T.series, ''));
  return h;
});

/* ---- 商品：金额 / 成本 / 毛利 ---- */
tnode('p-cost', '商品：金额、成本、毛利', function () {
  var PR = d('products');
  var h = crumb();
  if (!PR) return h + failCard('products');
  var items = (PR.items || []).slice().sort(function (a, b) { return (num(b.amount) || 0) - (num(a.amount) || 0); });
  h += '<div class="kpis">' +
    kpi('这一段商品金额', money(PR.total_amount), ints(items.length) + ' 种商品 · ' + ints(PR.total_qty) + ' 件', '#1E6FFF') +
    kpi('商品毛利', money(num(PR.cost_covered_amount) - num(PR.cost_total)), '成本 ' + money(PR.cost_total) + ' · 算得出成本的 ' + money(PR.cost_covered_amount), '#00B3A4') +
    '</div>';
  h += card('逐商品（点一个看它的订单）', '#7C4DFF',
    items.map(function (it) {
      var gp = (num(it.covered_amount) || 0) - (num(it.cost) || 0);
      var note = (num(it.covered_amount) ? '毛利 ' + money(gp) + ' · ' : '没有进货价，算不出毛利 · ') + ints(it.order_count) + ' 单';
      return nrow(it.product_name, money(it.amount), '', 'p-prod', it.product_name, note);
    }).join('') +
    '<div class="kn">「没有进货价」的商品，接口不替它猜成本（既不按 0、也不按均价），所以它的毛利率是空的 —— 这一段这类金额一共 ' + money(PR.total_amount - PR.cost_covered_amount) + '。</div>');
  h += rawBlock(['products']);
  return h;
});

tnode('p-prod', '商品', function () {
  var name = DASH.narg || '';
  var h = crumb();
  var it = null;
  prodItems().forEach(function (x) { if (x.product_name === name) it = x; });
  var w = DASH.state.win;
  var key = 'pd|' + name + '|' + w.from + '|' + w.to;
  if (!DASH.cache[key]) loadInto(key, '/stats/product-drilldown?product_name=' + enc(name) + '&date_from=' + w.from + '&date_to=' + w.to);
  var c = DASH.cache[key];
  if (it) {
    var gp = (num(it.covered_amount) || 0) - (num(it.cost) || 0);
    h += card('这个商品：' + name, '#7C4DFF',
      kv('金额', money(it.amount)) +
      kv('成本', money(it.cost), 'orange') +
      kv('毛利', num(it.covered_amount) ? money(gp) + '（' + pctStr(gp, it.covered_amount) + '）' : '<span class="dim">这个商品没记进货价，算不出</span>') +
      kv('件数 / 单数', ints(it.qty) + ' 件 · ' + ints(it.order_count) + ' 单') +
      (it.damage_amount ? kv('货损', '− ' + money(it.damage_amount), 'red') : '') +
      (it.covered_lines ? kv('算得出成本的行', ints(it.covered_lines) + ' 行', '') : ''));
  }
  var rows = (c && c !== 'loading' && c.ok && Array.isArray(c.body)) ? c.body : null;
  var listHTML;
  if (!c || c === 'loading') listHTML = '<div class="kn">正在取这个商品的订单……</div>';
  else if (!c.ok) listHTML = '<div class="err">接口没取到（' + ints(c.status) + '）</div>';
  else if (!rows || !rows.length) listHTML = '<div class="dim">这一段这个商品没有已送达的单</div>';
  else listHTML = rows.map(function (o) {
    return orow(o.shipper_name + ' · ' + String(o.order_date).slice(0, 10), money(o.line_total), '', o.id, o.order_no,
      esc(o.order_no) + ' · ' + esc(o.status) + ' · ' + esc(String(o.quantity)) + ' 件');
  }).join('') + '<div class="kn">逐单相加 = ' + money(sumOf(rows, function (o) { return o.line_total; })) + '（这一页的金额就是这个数）；点一张进去就是「一张订单」（下钻终点）。</div>';
  h += card('它的订单（逐单 · 接口 /stats/product-drilldown 原文）', '#1E6FFF', listHTML);
  return h;
});

/* ---- 客户 ---- */
tnode('p-cust', '客户：谁买得多、谁欠得多', function () {
  var S = shipperRows(), B = d('balances');
  var h = crumb();
  var sorted = S.slice().sort(function (a, b) { return (num(b.total_amount) || 0) - (num(a.total_amount) || 0); });
  h += card('按买货金额（' + ints(S.length) + ' 个，接口 /stats/shipper-performance）', '#1E6FFF',
    sorted.map(function (r) {
      return nrow(r.shipper_name, money(r.total_amount), '', r.shipper_id ? 'p-cust1' : '', r.shipper_id || '', ints(r.order_count) + ' 单' + (r.shipper_id ? '' : ' · 临时货主（没有账号），点不进去'));
    }).join('') +
    '<div class="kn">逐客户相加 = ' + money(sumOf(S, function (r) { return r.total_amount; })) + '，与营业额不是一回事：接口按货主归集明细金额，没归到货主名下的不在里面。</div>');
  if (B && B.totals) {
    h += card('还欠着的（时点账 · 到 ' + esc(B.as_of) + '）', '#FF6B2C',
      nrow('欠款合计', money(B.totals.balance), 'orange tot', 'arrears', '', ints(B.totals.debtor_count) + ' 人 · ' + ints(B.totals.order_count) + ' 张单') +
      nrow('0-30 天', money(B.totals.buckets['0_30']), '', 'arrears', '') +
      nrow('31-60 天', money(B.totals.buckets['31_60']), '', 'arrears', '') +
      nrow('61-90 天', money(B.totals.buckets['61_90']), '', 'arrears', '') +
      nrow('90 天以上', money(B.totals.buckets['over_90']), 'red', 'arrears', '') + topOwed(B));
  }
  h += rawBlock(['shippers', 'balances']);
  return h;
});

tnode('p-cust1', '客户', function () {
  var id = DASH.narg || '';
  var w = DASH.state.win;
  var key = 'sa|' + id + '|' + w.from + '|' + w.to;
  if (!DASH.cache[key]) loadInto(key, '/stats/shipper-activity?shipper_id=' + enc(id) + '&date_from=' + w.from + '&date_to=' + w.to);
  var c = DASH.cache[key];
  var h = crumb();
  if (c && c !== 'loading' && c.ok && c.body) {
    var b = c.body;
    h += '<div class="kpis">' +
      kpi('这一段买了', money(b.total_spent), ints(b.delivered_count) + ' 单送达 / 共 ' + ints(b.order_count) + ' 单', '#1E6FFF') +
      kpi('每单平均', money(b.avg_order_value), '大约每周 ' + esc(String(b.orders_per_week)) + ' 单', '#00B3A4') +
      '</div>';
    h += card('他常买的东西（接口 /stats/shipper-activity 原文）', '#7C4DFF',
      (b.top_products || []).length ? (b.top_products || []).map(function (t) {
        return nrow(t.product_name, money(t.amount), '', 'p-prod', t.product_name, ints(t.count) + ' 行 · 点进去看这个商品在这一段的订单');
      }).join('') + '<div class="kn">行数、金额都是接口给的原文；点一个商品就是它的订单清单（再点一张到订单详情）。</div>' : '<div class="dim">这一段没有明细</div>');
  } else {
    h += loadingCard();
  }
  h += card('还欠多少', '#FF6B2C', nrow('这个客户的欠款（时点账，逐人）', '去客户欠款页看', '', 'arrears', '', '点进去按人列订单'));
  return h;
});

/* ---- 司机 ---- */
tnode('p-drv', '司机：运费与待结', function () {
  var P = d('profit');
  var DR = driverRows(), ow = owedTotal();
  var h = crumb();
  h += '<div class="kpis">' +
    kpi('这一段司机运费', money(P && P.delivery_cost), '按单应付（driver_pay 算的），不是订单上的运费字段', '#00A2C7') +
    kpi('还没结给司机的', money(ow.owed), ints(ow.n) + ' 个司机有待结', '#FF9F0A') +
    '</div>';
  h += card('逐司机（点进去看这个人这一段拉了多少）', '#00A2C7',
    DR.slice().sort(function (a, b) { return (num(b.freight_owed) || 0) - (num(a.freight_owed) || 0); }).map(function (r) {
      var note = (r.completed_count === null || r.completed_count === undefined ? '这一段没有他的送达单' : ints(r.completed_count) + ' 单送达') + (r.billing_mode === 'SALARY' ? ' · 工资制，不按单结' : '');
      return nrow(r.driver_name, r.freight_owed === null || r.freight_owed === undefined ? '<span class="dim">不按单结</span>' : money(r.freight_owed), '', '', '', note);
    }).join('') +
    '<div class="kn">这一列是<b>还没结的</b>运费（接口 freight_owed）。逐司机的「这一段应得多少」接口还没接（司机账单/结算那几个端点在盘），所以点不进下一层。</div>');
  h += rawBlock(['drivers']);
  return h;
});

/* ---- 期间费用 ---- */
tnode('p-exp', '期间费用：钱花在哪', function () {
  var EZ = d('expenses');
  var rows = Array.isArray(EZ) ? EZ : ((EZ && (EZ.items || EZ.rows)) || []);
  var h = crumb();
  var by = {}, cnt = {};
  rows.forEach(function (r) { var k = r.category || '没分类'; by[k] = (by[k] || 0) + (num(r.amount) || 0); cnt[k] = (cnt[k] || 0) + 1; });
  var tot = 0; Object.keys(by).forEach(function (k) { tot += by[k]; });
  h += kpi('这一段期间费用', money(tot), rows.length + ' 笔 · 按类目合并', '#FF9F0A');
  h += card('按类目（点一类看每一笔）', '#FF9F0A',
    Object.keys(by).sort(function (a, b) { return by[b] - by[a]; }).map(function (k) {
      return nrow(k, money(by[k]), '', 'p-expc', k, ints(cnt[k]) + ' 笔');
    }).join('') +
    '<div class="kn">费用里有多少挂在车上、多少挂着单：车上的开销也会进「车辆成本」，但<b>不重复扣</b>（已经在这张表里了）。</div>');
  h += card('每一笔（接口 /expenses 原文）', '#8A94A6', flatTable(rows));
  return h;
});

tnode('p-expc', '费用', function () {
  var cat = DASH.narg || '';
  var EZ = d('expenses');
  var rows = (Array.isArray(EZ) ? EZ : ((EZ && (EZ.items || EZ.rows)) || [])).filter(function (r) { return (r.category || '没分类') === cat; });
  var h = crumb();
  h += kpi(cat, money(sumOf(rows, function (r) { return r.amount; })), rows.length + ' 笔', '#FF9F0A');
  h += card('每一笔（点一笔就是那张单据）', '#FF9F0A', (rows.length ? rows.map(function (r) {
    return rowDoc((r.exp_date || '') + ' · ' + (r.category || '没分类'), money(r.amount), (r.note || '') + (r.order_no ? ' · 挂着单 ' + r.order_no : (r.vehicle_name ? ' · ' + r.vehicle_name : '')), 'exp', r.id, 'orange');
  }).join('') : '<div class="dim">这一类没有单据</div>') +
    '<div class="kn">点进去看到的是接口给的原始字段：日期、金额、经手人、挂在哪张单/哪台车。</div>');
  return h;
});

tnode('p-dep', '车辆折旧', function () {
  var P = d('profit'), V = d('vehicle');
  var h = crumb();
  h += card('这一段折旧', '#546E7A',
    kv('折旧合计', money(P && P.depreciation_total)) +
    kv('按整月算的折旧', money(P && P.depreciation_monthly_total)) +
    kv('算得出的车', ints(P && P.depreciation_vehicle_count) + ' 台') +
    kv('算不出的车', ints(P && P.depreciation_uncovered_count) + ' 台', num(P && P.depreciation_uncovered_count) ? 'red' : '') +
    ((P && (P.depreciation_uncovered || []).length) ? flatTable(P.depreciation_uncovered.slice(0, 10)) : '') +
    '<div class="kn">折旧算不出来 = 车辆台账里没填购置价/购置日期/年限/残值率。填了之后利润表里的折旧才是真的。</div>');
  h += card('逐车（点开车辆成本页看全表）', '#546E7A', nrow('15 台车的台账', '去看', '', 'vehicle', '', '购置价、年限、月折旧、有没有填'));
  return h;
});

/* ---- 税 ---- */
tnode('t-tax', '税账', function () {
  var TX = d('tax');
  var h = crumb();
  if (!TX) return h + failCard('tax');
  var o = TX.output || {}, i = TX.input || {};
  h += kpi('这一段应交增值税', money(TX.vat_payable), '销项税 ' + money(o.tax_amount) + ' − 进项税 ' + money(i.tax_amount), '#C08A4E');
  h += card('税表', '#C08A4E',
    kv('销项税（开出去的票）', money(o.tax_amount)) +
    kv('进项税（收到的票）', money(i.tax_amount), 'green') +
    kv('＝ 应交增值税', money(TX.vat_payable), 'tot orange') +
    kv('发票张数', ints((TX.invoices || []).length) + ' 张 · 作废 ' + ints(TX.voided_count) + ' 张') +
    (num(TX.output && TX.output.untaxed_amount) ? kv('没填税率的销项票', money(TX.output.untaxed_amount), 'orange') : '') +
    '<div class="kn">增值税是价外税，<b>不进营业利润</b>；这张表只回答「这一段开了多少票、要交多少税」。</div>');
  h += card('按税率的构成（接口 by_rate）', '#8A94A6', flatTable(TX.by_rate));
  var IV = arrOf('invoices') || [];
  h += card('发票（逐张 · 点一张就是那张票）', '#1E6FFF', (IV.length ? IV.map(function (r) {
    var dir = r.direction === 'OUTPUT' ? '开出去' : '收进来';
    return rowDoc(esc(r.invoice_no || r.title || dir) + ' · ' + dir, money(r.total_amount || r.amount || r.net_amount), esc(r.invoice_date || r.issue_date || '') + (r.status ? ' · ' + esc(r.status) : ''), 'inv', r.id, '');
  }).join('') + '<div class="kn">发票上没有 order_id（接口只给 purchase_order_ids / ledger_ids）—— 想从票回到某一张单，得先经账本行，这一步接口还没打通，页面如实标出来。</div>'
  : '<div class="dim">这一段（按开票日期）没有票</div>'));
  h += notesBlock(['tax'], '口径');
  h += rawBlock(['tax']);
  return h;
});

/* ===================== 2. 资产负债表 ===================== */
tnode('t-balance', '资产负债表', function () {
  var B = d('balances'), P = d('profit'), CS = d('cashSummary'), VS = d('vehicles');
  var ow = owedTotal();
  var h = crumb();
  var cars = Array.isArray(VS) ? VS : ((VS && (VS.items || VS.rows)) || []);
  var noPrice = cars.filter(function (v) { return !v.purchase_price; }).length;
  h += kpi('别人欠我的（应收账款）', B ? money(B.totals.balance) : '—', B ? ints(B.totals.debtor_count) + ' 人 · ' + ints(B.totals.order_count) + ' 张单 · 到 ' + B.as_of + ' 为止' : '', '#FF6B2C');
  if (B && B.totals) {
    h += card('资产（系统里能算的）', '#00B578',
      nrow('应收账款（客户挂账）', money(B.totals.balance), 'orange', 'arrears', '', '四桶账龄 + 逐人名单') +
      nrow('预收（客户先给的钱）', money(B.totals.prepaid), '', 'customers', '', '单列，不冲减欠款') +
      nrow('库存（存货 · 按进货价估算）', stockValueHTML(), '', 'p-stock', '', '结存是实时数（inventory 流水 + 商品档案进货价），没有期初期末快照') +
      nrow('固定资产（车）', '<span class="dim">' + ints(cars.length) + ' 台车里 ' + ints(noPrice) + ' 台没填购置价</span>', '', 'vehicle', '', '填了价才能算原值、折旧、净值') +
      nrow('货币资金（现金+银行）', '<span class="dim">没有账户余额表</span>', '', 'finance', '', '这一段现金净 ' + money(CS && CS.net) + '，但没有期初余额'));
  }
  h += card('负债与权益（系统里能算的）', '#E53935',
    nrow('应付司机（还没结的运费）', money(ow.owed), 'orange', 'drivers', '', ints(ow.n) + ' 个司机') +
    nrow('应交税费（增值税）', money(P && P.vat_payable), '', 't-tax', '', '这一段按开票日期算的') +
    nrow('应付账款（欠供应商）', supUnpaidHTML(), 'orange', 'p-sup', '', '供应商维度的时点余额（/suppliers 的 unpaid_total），没有 as_of') +
    nrow('借款 / 实收资本 / 未分配利润', '<span class="dim">系统里没有这几个概念</span>') +
    '<div class="kn">这张表只能给「现在欠多少」这类<b>时点数</b>：系统记流水、不记期初余额，所以做不出标准的「期初 + 本期变动 = 期末」。要真做资产负债表，得先定「期初从哪天算起」。</div>');
  h += rawBlock(['balances', 'vehicles']);
  return h;
});

/* ===================== 3. 现金流量表 ===================== */
tnode('t-cash', '现金流量表', function () {
  var CS = d('cashSummary'), CB = d('cashBreakdown'), T = d('turnover');
  var h = crumb();
  if (!CS) return h + failCard('cashSummary');
  h += kpi('这一段现金净额', money(CS.net), '进来 ' + money(CS.income) + ' / 出去 ' + money(CS.expense) + ' · ' + ints(CS.count) + ' 笔', num(CS.net) < 0 ? '#E53935' : '#00B578');
  if (CB) {
    h += card('经营 · 进来的钱（点一行看流水）', '#00B578',
      (CB.income || []).map(function (r) { return nrow(bizName(r.biz_type), money(r.amount), 'green', 'c-flow', r.biz_type, ints(r.count) + ' 笔'); }).join('') +
      nrow('＝ 进来合计', money(CB.income_total), 'tot green'));
    h += card('经营 · 出去的钱', '#E53935',
      (CB.expense || []).map(function (r) { return nrow(bizName(r.biz_type), money(r.amount), 'orange', 'c-flow', r.biz_type, ints(r.count) + ' 笔'); }).join('') +
      nrow('＝ 出去合计', money(CB.expense_total), 'tot orange') +
      nrow('＝ 净额', money(CB.net), 'tot ' + (num(CB.net) < 0 ? 'red' : 'green')));
  }
  h += card('投资 / 筹资', '#8A94A6',
    '<div class="kn">系统里没有这两个分类：买车、借款、股东投钱都记在别的名目上（或者根本没记）。所以这一版只给<b>经营现金流</b>，要分类得先在记账那里定规则。</div>');
  h += card('两个口径别混', '#FF9F0A',
    kv('这一段「已收」（订单口径，profit.collected）', money(T && T.collected)) +
    kv('这一段「收到的现金」（流水口径，cash-flows）', money(CS.income)) +
    '<div class="kn">订单口径看的是「这一段的单收回来多少」，流水口径看的是「账上实际进出多少」，两个数不相等是正常的，页面不替它们凑。</div>');
  h += notesBlock(['cashSummary'], '口径');
  h += rawBlock(['cashSummary', 'cashBreakdown', 'cashFlows']);
  return h;
});

tnode('c-flow', '流水明细', function () {
  var biz = DASH.narg || '';
  var CF = d('cashFlows');
  var rows = (Array.isArray(CF) ? CF : ((CF && (CF.items || CF.rows)) || [])).filter(function (r) { return r.biz_type === biz; });
  var h = crumb();
  h += kpi(bizName(biz), money(sumOf(rows, function (r) { return r.amount; })), rows.length + ' 笔（这一段最多看 100 条）', '#1E6FFF');
  h += card('每一笔（点一笔就是那张单据）', '#1E6FFF', (rows.length ? rows.map(function (r) {
    return rowDoc((r.flow_date || '') + ' · ' + (r.party_name || ''), (r.direction === 'IN' ? '+' : '−') + money(r.amount), (r.note || r.channel || ''), 'cash', r.id, (r.direction === 'IN' ? 'green' : ''));
  }).join('') : '<div class="dim">这一类没有流水</div>') +
    '<div class="kn">钱进钱出都能点回那张单据；单据上挂着单的，还能再点进订单。</div>');
  return h;
});

/* ===================== 4. 运营分析表 ===================== */
tnode('t-ops', '运营分析表', function () {
  var PR = d('products'), V = d('vehicle'), DR = driverRows(), S = shipperRows(), P = d('profit');
  var h = crumb();
  var topP = topOf(PR && PR.items, function (r) { return r.amount; });
  var topC = topOf(S, function (r) { return r.total_amount; });
  var topD = topOf(DR, function (r) { return r.freight_owed; });
  var topV = topOf(V && V.per_vehicle, function (r) { return r.total_cost; });
  h += card('四个维度（各切各的，点进去）', '#7C4DFF',
    nrow('按商品（' + ints(prodItems().length) + ' 种）', money(PR && PR.total_amount), '', 'p-cost', '', topP ? '金额最大：' + esc(topP.product_name) + ' ' + money(topP.amount) : '') +
    nrow('按客户（' + ints(S.length) + ' 个）', money(sumOf(S, function (r) { return r.total_amount; })), '', 'p-cust', '', topC ? '买得最多：' + esc(topC.shipper_name) + ' ' + money(topC.total_amount) : '') +
    nrow('按车辆（' + ints(V && V.vehicle_count) + ' 台）', money(V && V.total_cost), '', 't-veh', '', topV ? '花钱最多：' + esc(topV.plate_no || topV.driver_name || '') + ' ' + money(topV.total_cost) : '') +
    nrow('按司机（' + ints(DR.length) + ' 人）', money(P && P.delivery_cost), '', 'p-drv', '', topD ? '待结最多：' + esc(topD.driver_name) + ' ' + money(topD.freight_owed) : ''));
  h += card('哪里赚、哪里亏（这一段的实话）', '#FF9F0A',
    kv('这一段毛利', money(P && P.gross_profit)) +
    kv('减去司机运费、期间费用、折旧', '− ' + money((num(P && P.delivery_cost) || 0) + (num(P && P.operating_expense_total) || 0) + (num(P && P.depreciation_total) || 0)), 'orange') +
    kv('＝ 营业利润', money(P && P.operating_profit), 'tot ' + (num(P && P.operating_profit) < 0 ? 'red' : 'green')) +
    '<div class="kn">「哪里亏」这一层再往下就要按线路、按单公里成本算，接口里还没有这些字段（车辆只到台/单），所以先到「按商品 / 按客户 / 按车 / 按司机」为止。</div>');
  h += rawBlock(['products', 'shippers', 'vehicle', 'drivers']);
  return h;
});

/* ===================== 5. 关键指标表 ===================== */
tnode('t-kpi', '关键指标表', function () {
  var T = d('turnover'), P = d('profit'), B = d('balances'), C = d('coverage'), DR = driverRows();
  var h = crumb();
  var gm = num(P && P.revenue_covered) ? (num(P.gross_profit) / num(P.revenue_covered)) : null;
  var fixed = (num(P && P.operating_expense_total) || 0) + (num(P && P.depreciation_total) || 0);
  var be = gm ? fixed / gm : null;
  var actual = num(T && T.total_amount) || 0;
  var mos = (be && actual) ? (actual - be) / actual : null;
  var days = 0;
  if (T && T.series) days = Math.max(1, T.series.length);
  var dailyAvg = actual / (days || 1);
  var arDays = (B && dailyAvg) ? (num(B.totals.balance) / dailyAvg) : null;
  var sv = stockValue();
  var stockSum = sv ? sv.sum : 0;
  var costDaily = (num(P && P.cost_total) || 0) / (days || 1);
  var invDays = (sv && costDaily) ? (stockSum / costDaily) : null;
  var su = supUnpaid();
  var apSum = su ? su.sum : 0;
  var apDays = (su && costDaily) ? (apSum / costDaily) : null;
  h += card('赚不赚钱', '#00B3A4',
    nrow('毛利率', P ? pctStr(P.gross_profit, P.revenue_covered) : '—', '', 'p-cost', '', '毛利 ÷ 有成本的收入 ' + money(P && P.revenue_covered)) +
    nrow('营业利润率', P ? pctStr(P.operating_profit, P.revenue_total) : '—', '', 't-profit', '', '营业利润 ÷ 营业额') +
    nrow('净利率', '<span class="dim">缺所得税</span>', '', '', '', '净利润 = 营业利润 − 所得税，接口里没有所得税') +
    nrow('保本营业额（粗算）', be ? money(be) : '—', '', 'p-exp', '', '（期间费用 + 折旧）÷ 毛利率；这一段实际 ' + money(actual)) +
    nrow('安全边际率', mos === null ? '—' : (mos * 100).toFixed(1) + '%', mos !== null && mos < 0 ? 'red' : 'green', 't-profit', '', '（实际 − 保本）÷ 实际；负数是没到保本点'));
  h += card('成本和费用', '#FF9F0A',
    nrow('司机运费率', T && P ? pctStr(P.delivery_cost, T.total_amount) : '—', '', 'p-drv', '', '司机运费 ÷ 营业额') +
    nrow('期间费用率', T && P ? pctStr(P.operating_expense_total, T.total_amount) : '—', '', 'p-exp', '', '期间费用 ÷ 营业额') +
    nrow('成本覆盖率', C ? pctStr(C.covered_lines, C.total_lines) : '—', '', 'coverage', '', '有进货价的行 ÷ 全部行；这一段算不出成本的收入 ' + money(P && P.revenue_uncovered)));
  h += card('钱转得快不快', '#1E6FFF',
    nrow('收款率', T ? pctStr(T.collected, T.total_amount) : '—', '', 't-profit', '', '这一段收回来 ÷ 这一段应收') +
    nrow('应收账款周转（天）', arDays === null ? '—' : arDays.toFixed(1) + ' 天', '', 'arrears', '', '时点欠款 ' + money(B && B.totals.balance) + ' ÷ 这一段日均营业额 ' + money(dailyAvg)) +
    nrow('库存周转（天 · 估算）', invDays === null ? '<span class="dim">缺库存</span>' : invDays.toFixed(1) + ' 天', '', 'p-stock', '', '库存估算 ' + money(stockSum) + ' ÷ 这一段日均商品成本 ' + money(costDaily)) +
    nrow('应付周转（天 · 估算）', apDays === null ? '<span class="dim">缺应付</span>' : apDays.toFixed(1) + ' 天', '', 'p-sup', '', '此刻应付 ' + money(apSum) + ' ÷ 这一段日均商品成本 ' + money(costDaily) + '（口径粗：应付只有时点数，采购也不是按这一段算的）'));
  h += card('人和车', '#546E7A',
    nrow('单车这一段成本', money((num(P && P.delivery_cost) || 0) / 15), '', 'vehicle', '', '司机运费 ÷ 15 台（接口没有「按车分摊」的算法，这是页面粗算）') +
    nrow('单均金额', money(T && T.avg_order), '', 'turnover', '', '接口给的 avg_order') +
    nrow('这一段送达单量', ints(T && T.total_orders) + ' 单', '', 'turnover', '') +
    nrow('司机人数 / 有待结的', ints(DR.length) + ' 人 / ' + ints(owedTotal().n) + ' 人', '', 'p-drv', ''));
  h += notesBlock(['turnover', 'profit', 'coverage'], '口径');
  h += rawBlock(['turnover', 'profit', 'coverage', 'balances']);
  return h;
});
