/* 库存与应付：把资产负债表上「接口在盘」的两格接上真数，并给下钻。 */
function stockRows() {
  var inv = d('invSummary'), ps = d('stock');
  if (!inv || !ps) return null;
  var byId = {};
  (Array.isArray(ps) ? ps : []).forEach(function (p) { byId[p.id] = p; });
  return (Array.isArray(inv) ? inv : []).map(function (r) {
    var p = byId[r.product_id] || {};
    var cost = p.cost_price === null || p.cost_price === undefined ? null : Number(p.cost_price);
    return { id: r.product_id, name: r.product_name, stock: Number(r.stock) || 0, unit: r.unit, low: r.low_stock_alert, category: r.category,
      cost: cost, value: (cost && cost > 0) ? cost * (Number(r.stock) || 0) : null };
  });
}
function stockValue() {
  var rows = stockRows();
  if (!rows) return null;
  var sum = 0, n = 0, miss = 0;
  rows.forEach(function (r) { if (r.value === null) { miss++; } else { sum += r.value; n++; } });
  return { sum: sum, n: n, miss: miss, total: rows.length };
}
function stockValueHTML() {
  var v = stockValue();
  if (!v) return '<span class="dim">正在取……</span>';
  return money(v.sum) + '<i class="tn2">估算</i>';
}
function supList() {
  var s = d('suppliers');
  return Array.isArray(s) ? s : null;
}
function supUnpaid() {
  var s = supList();
  if (!s) return null;
  var sum = 0, open = 0;
  s.forEach(function (x) { sum += Number(x.unpaid_total) || 0; open += Number(x.open_payables) || 0; });
  return { sum: sum, open: open, n: s.length };
}
function supUnpaidHTML() {
  var v = supUnpaid();
  if (!v) return '<span class="dim">正在取……</span>';
  return money(v.sum);
}

/* 库存：结存 × 进货价（估算） */
tnode('p-stock', '库存', function () {
  var rows = stockRows();
  var h = crumb();
  if (!rows) return h + loadingCard();
  var v = stockValue();
  h += kpi('库存金额（估算）', money(v.sum), ints(v.n) + ' 个商品算了价 · ' + ints(v.miss) + ' 个没进货价（没算进去）· 共 ' + ints(v.total) + ' 个有结存的商品', '#00B578');
  h += card('每个商品的结存（点一个看它的进出流水）', '#00B578',
    rows.slice().sort(function (a, b) { return (b.value || 0) - (a.value || 0); }).map(function (r) {
      return nrow(r.name + '（' + esc(r.category || '') + '）',
        (r.value === null ? '<span class="dim">没进货价</span>' : money(r.value)), '', 'p-mov', r.id,
        ints(r.stock) + ' ' + esc(r.unit || '') + ' × ' + (r.cost === null ? '—' : money(r.cost)) + ' · 低于预警线 ' + ints(r.low));
    }).join('') +
    '<div class="kn">金额 = 实时结存 × 商品档案里的进货价，是<b>估算</b>：接口没有期初/期末快照，也没有移动加权平均的库存单价（加权平均只在成本口径里用，没暴露）。要真做存货科目，得先定计价方法。</div>');
  h += rawBlock(['invSummary', 'stock']);
  return h;
});

/* 某个商品的库存流水（能点回订单） */
tnode('p-mov', '库存流水', function () {
  var id = DASH.state.narg || DASH.narg;
  var h = crumb();
  if (!id) return h + '<div class="dim">没带商品</div>';
  var key = 'mov' + id;
  loadOC(key, '/inventory/movements?product_id=' + enc(id) + '&limit=200');
  var res = DASH.oc[key];
  if (!res || res === 'loading') return h + loadingCard();
  if (!res.ok) return h + '<div class="err">取数失败（HTTP ' + esc(res.status) + '）</div>';
  var arr = res.body;
  var rows = Array.isArray(arr) ? arr : ((arr && (arr.items || arr.rows)) || []);
  var rr = stockRows() || [];
  var me = null;
  rr.forEach(function (r) { if (String(r.id) === String(id)) me = r; });
  if (me) h += kpi('现在结存', ints(me.stock) + ' ' + esc(me.unit || ''), me.value === null ? '没进货价，算不出金额' : '按 ' + money(me.cost) + ' 估算 ' + money(me.value), '#00B578');
  h += card('进出流水（最近 ' + ints(rows.length) + ' 条 · /inventory/movements 原文）', '#1E6FFF',
    (rows.length ? rows.map(function (m) {
      var n = Number(m.change) || 0;
      var lab = (n >= 0 ? '+' : '') + ints(n) + ' ' + esc(me && me.unit || '') + ' · ' + esc(m.note || m.source || '');
      var when = String(m.created_at || '').slice(0, 16).replace('T', ' ');
      if (m.order_id) return orow(lab, '<span class="dimv">看这一单</span>', '', m.order_id, m.order_no, esc(m.order_no || '') + ' · ' + when + ' · ' + esc(m.source));
      return nrow(lab, esc(when), '', 't-doc', 'mov:' + m.id, esc(m.source) + (m.unit_cost ? ' · 单价 ' + money(m.unit_cost) : ''));
    }).join('') : '<div class="dim">这个商品没有流水</div>') +
    '<div class="kn">流水里的 order_id 能点回订单（退货回库、下单出库这类都挂着单号）。接口默认只回 100 条、上限 500，这里要了 200 条。</div>');
  h += rawBlock([key]);
  return h;
});

/* 供应商与应付 */
tnode('p-sup', '供应商与应付', function () {
  var s = supList();
  var h = crumb();
  if (!s) return h + loadingCard();
  var v = supUnpaid();
  h += kpi('还欠供应商', money(v.sum), ints(v.n) + ' 家 · 未结清 ' + ints(v.open) + ' 笔', '#FF6B2C');
  h += card('按供应商（/suppliers 原文）', '#FF6B2C', s.map(function (x) {
    return nrow(x.name, money(x.unpaid_total), Number(x.unpaid_total) > 0 ? 'red' : 'green', '', '',
      '累计应付 ' + money(x.payable_total) + ' · 已付 ' + money(x.paid_total) + ' · 未结 ' + ints(x.open_payables) + ' 笔');
  }).join('') + '<div class="kn">采购单接口（/purchase-orders）在库里是 0 张 —— 采购这条链目前只有应付单和付款流水，没有采购单可以点。这是数据没录，不是页面取不到。</div>'
    + '<div class="kn">这是<b>此刻</b>的余额（接口没有 as_of 参数，回顾不了历史时点）；供应商账期字段系统里没有，实际账期只能用「付款流水日期 − 应付单日期」算。</div>');
  var key = 'payables';
  loadOC(key, '/supplier-payables?limit=200');
  var res = DASH.oc[key];
  if (!res || res === 'loading') h += loadingCard();
  else if (!res.ok) h += '<div class="err">取数失败（HTTP ' + esc(res.status) + '）</div>';
  else {
    var arr = res.body;
    var rows = Array.isArray(arr) ? arr : ((arr && (arr.items || arr.rows)) || []);
    h += card('应付单（逐张 · 点一张就是那张单据）', '#E53935', rows.map(function (p) {
      return rowDoc(esc(p.supplier_name) + ' · ' + esc(p.title || ''), money(p.amount), esc(p.category || '') + ' · 单据日 ' + esc(p.doc_date) + ' · 已付 ' + money(p.paid) + ' · 未付 ' + money(p.unpaid) + ' · ' + ints(p.payment_count) + ' 次付款', 'pay', p.id, Number(p.unpaid) > 0 ? 'red' : '');
    }).join('') || '<div class="dim">没有应付单</div>');
    h += rawBlock([key]);
    if (res.trunc) h += '<div class="kn">接口说结果被截断了（X-Truncated）。</div>';
  }
  return h;
});
