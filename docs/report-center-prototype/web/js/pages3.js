/* 页面 3：经营利润 / 车辆成本 / 成本覆盖 / 税账 / 客户欠款 */

function flatTable(rows, title) {
  if (!rows || !rows.length) return '<div class="dim">没有明细行</div>';
  var keys = Object.keys(rows[0]);
  return (title ? '<div class="tg">' + esc(title) + '</div>' : '') +
    '<table class="tb"><tr>' + keys.map(function (k) { return '<th>' + esc(k) + '</th>'; }).join('') + '</tr>' +
    rows.map(function (r) {
      return '<tr>' + keys.map(function (k) {
        var v = r[k];
        if (v === null || v === undefined) return '<td class="dim">—</td>';
        if (Array.isArray(v)) return '<td>' + esc(v.join(' / ')) + '</td>';
        if (typeof v === 'object') return '<td>' + esc(JSON.stringify(v)) + '</td>';
        return '<td>' + esc(v) + '</td>';
      }).join('') + '</tr>';
    }).join('') + '</table>';
}

/* ---------------- 经营利润 ---------------- */
function pageProfit() {
  var p = d('profit');
  var h = failCard('profit');
  h += '<div class="pagehead"><h2>经营利润</h2><span>' + esc(DASH.state.win.from) + ' ~ ' + esc(DASH.state.win.to) + '</span></div>';
  if (!p) return h + '<div class="err">没取到数据</div>';
  var pct = pctOf(p.operating_profit, p.revenue_total);
  h += '<div class="kpis">' +
    kpi('这一段营业利润', money(p.operating_profit), '利润率 ' + (pct === null ? '—' : pct + '%') + '（营业利润 ÷ 营业额）', num(p.operating_profit) < 0 ? '#E53935' : '#00B3A4') +
    kpi('商品毛利', money(p.gross_profit), '毛利 ÷ 参与毛利的收入 = ' + (pctOf(p.gross_profit, p.revenue_covered) === null ? '—' : pctOf(p.gross_profit, p.revenue_covered) + '%'), '#1E6FFF') +
    '</div>';
  h += card('利润表（全部是接口给的数）', '#00B3A4',
    kv('参与毛利的收入（有成本的那部分）', money(p.revenue_covered)) +
    kv('− 商品成本', '− ' + money(p.cost_total), 'orange') +
    kv('＝ 商品毛利', money(p.gross_profit), 'green tot') +
    kv('− 司机运费（按单应付）', '− ' + money(p.delivery_cost), 'orange') +
    kv('− 期间费用', '− ' + money(p.operating_expense_total), 'orange') +
    kv('− 车辆折旧', '− ' + money(p.depreciation_total), 'orange') +
    kv('＝ 营业利润', money(p.operating_profit), 'tot ' + (num(p.operating_profit) < 0 ? 'red' : 'green')) +
    '<div class="kn">接口自己给的等式（页面不重算）：参与毛利的收入 − 商品成本 = 毛利；毛利 − 司机运费 − 期间费用 − 折旧 = 营业利润。' +
    '本页把每一项都印出来，你可以照着减一遍。</div>');
  h += card('不进毛利、但营业额里仍然有的那一部分', '#FF9F0A',
    kv('这一段营业额（全部）', money(p.revenue_total)) +
    kv('− 参与毛利的收入', '− ' + money(p.revenue_covered)) +
    kv('＝ 没有进货价的收入', money(p.revenue_uncovered), 'orange tot') +
    kv('行数', ints(p.total_lines - p.covered_lines) + ' / ' + ints(p.total_lines) + ' 行算不出成本') +
    kv('成本覆盖率', (pctOf(p.covered_lines, p.total_lines) === null ? '—' : pctOf(p.covered_lines, p.total_lines) + '%') +
      '（其中 ' + ints(p.cost_avg_lines) + ' 行用均价 · ' + ints(p.cost_snapshot_lines) + ' 行退回下单快照）') +
    '<div class="kn">算不出成本的行既不按 0 成本、也不按平均成本替它猜 —— 所以毛利不会被高估。</div>');
  h += card('折旧与未覆盖的车', '#546E7A',
    kv('这一段折旧合计', money(p.depreciation_total)) +
    kv('按整月计算的折旧', money(p.depreciation_monthly_total)) +
    kv('能算折旧的车', ints(p.depreciation_vehicle_count) + ' 台') +
    kv('算不出折旧的车', ints(p.depreciation_uncovered_count) + ' 台', num(p.depreciation_uncovered_count) ? 'red' : '') +
    ((p.depreciation_uncovered || []).length ? flatTable(p.depreciation_uncovered.slice(0, 10)) : ''));
  h += card('期间费用明细与税', '#C08A4E',
    flatTable(p.operating_expenses, '期间费用 operating_expenses') +
    kv('税金及附加（开销里分类名带「税」的）', money(p.tax_total)) +
    kv('销项税', money(p.vat_output)) +
    kv('进项税', money(p.vat_input)) +
    kv('应交增值税（价外税，不进营业利润）', money(p.vat_payable), 'orange') +
    flatTable(p.tax_expenses, 'tax_expenses'));
  h += card('不该漏掉的两项', '#E53935',
    kv('货损', money(p.damage_amount) + '（' + ints(p.damage_qty) + ' 件）', 'red') +
    kv('这一段已收 / 挂账未收', money(p.collected) + ' / ' + money(p.arrears_total)) +
    kv('撤销单', ints(p.cancelled_orders) + ' 单（不进营业额）'));
  h += notesBlock(['profit']);
  h += rawBlock(['profit']);
  return h;
}

/* ---------------- 车辆成本 ---------------- */
function pageVehicle() {
  var v = d('vehicle'), vl = d('vehicles');
  var h = failCard('vehicle');
  h += '<div class="pagehead"><h2>车辆成本</h2><span>' + esc(DASH.state.win.from) + ' ~ ' + esc(DASH.state.win.to) + '</span></div>';
  if (!v) return h + '<div class="err">没取到数据</div>';
  h += '<div class="kpis">' +
    kpi('这一段车辆总成本', money(v.total_cost), ints(v.vehicle_count) + ' 台车 · 算得全的 ' + ints(v.covered_count) + ' 台', '#546E7A') +
    kpi('其中折旧', money(v.depreciation_total), '按整月算是 ' + money(v.depreciation_monthly_total), '#8A94A6') +
    '</div>' +
    card('成本的另外两笔', '#FF9F0A',
      kv('这台车的开销', money(v.expense_total), 'orange') +
      kv('挂靠司机配送成本', money(v.delivery_cost_total), 'orange') +
      kv('合计（接口给的 total_cost）', money(v.total_cost), 'tot'));
  var rows = (v.per_vehicle || []).slice().sort(function (a, b) { return (num(b.total_cost) || 0) - (num(a.total_cost) || 0); });
  h += card('逐车（/reports/vehicle-cost 原文）', '#546E7A',
    '<table class="tb"><tr><th>车牌</th><th>司机</th><th>折旧</th><th>开销</th><th>配送成本</th><th>合计</th><th>折旧是否算得全</th><th>缺什么</th></tr>' +
    rows.map(function (r) {
      return '<tr><td>' + esc(r.plate_no) + (r.is_active ? '' : ' <span class="dim">停用</span>') + '</td><td>' + esc(r.driver_name || '—') +
        '</td><td>' + money(r.depreciation) + '</td><td>' + money(r.expense_total) + '</td><td>' + money(r.delivery_cost) +
        '</td><td><b>' + money(r.total_cost) + '</b></td><td>' + (r.depreciation_covered ? '算得全' : '<span class="red">算不全</span>') +
        '</td><td>' + esc((r.depreciation_uncovered_reasons || []).join(' / ')) + '</td></tr>';
    }).join('') + '</table>' +
    '<div class="kn">这张表<b>只算成本、不算收入</b>：订单上只有司机、没有「哪台车拉的」这个事实，按比例摊出来的收入会被拿去决定这车留不留。</div>');
  h += card('车辆台账（GET /vehicles）', '#8A94A6',
    vl && vl.length ? ('<table class="tb"><tr><th>车牌</th><th>类型</th><th>司机</th><th>购入价</th><th>购入日</th><th>年限</th><th>残值率</th><th>状态</th></tr>' +
      vl.map(function (r) {
        return '<tr><td>' + esc(r.plate_no) + '</td><td>' + esc(r.vehicle_type) + '</td><td>' + esc(r.driver_name || '—') + '</td><td>' + money(r.purchase_price) +
          '</td><td>' + esc(r.purchase_date || '—') + '</td><td>' + esc(r.useful_life_years === null ? '—' : r.useful_life_years) + '</td><td>' + esc(r.residual_rate === null ? '—' : r.residual_rate) +
          '</td><td>' + (r.is_active ? '在用' : '停用') + '</td></tr>';
      }).join('') + '</table>') : '<div class="dim">没取到</div>');
  h += notesBlock(['vehicle']);
  h += rawBlock(['vehicle', 'vehicles']);
  return h;
}

/* ---------------- 成本覆盖 ---------------- */
function pageCoverage() {
  var c = d('coverage');
  var h = failCard('coverage');
  h += '<div class="pagehead"><h2>成本覆盖</h2><span>' + esc(DASH.state.win.from) + ' ~ ' + esc(DASH.state.win.to) + '</span></div>';
  if (!c) return h + '<div class="err">没取到数据</div>';
  var cov = pctOf(c.covered_lines, c.total_lines);
  h += '<div class="kpis">' +
    kpi('成本算得出来的行', (cov === null ? '—' : cov + '%'), ints(c.covered_lines) + ' / ' + ints(c.total_lines) + ' 行', '#4CAF50') +
    kpi('算不出成本的收入', money(c.revenue_uncovered), '营业额 ' + money(c.revenue_total) + ' 里的这一块不进毛利', '#FF9F0A') +
    kpi('名册里没记进货价的商品', ints(c.missing_purchase_price_count) + ' 个', '这是商品名册上的口径，不是这一段的收入', '#8455E6') +
    '</div>';
  h += card('这一段的收入与覆盖', '#4CAF50',
    kv('营业额（全部）', money(c.revenue_total)) +
    kv('参与毛利的收入', money(c.revenue_covered), 'green') +
    kv('算不出成本的收入', money(c.revenue_uncovered), 'orange') +
    kv('行数', ints(c.covered_lines) + ' / ' + ints(c.total_lines)) +
    kv('其中用均价 / 退回快照', ints(c.cost_avg_lines) + ' 行 / ' + ints(c.cost_snapshot_lines) + ' 行') +
    '<div class="kn">「算不出成本的收入」只有一条判据：这一行的成本大于 0（入库流水的加权平均进货价；没记过进货价时退回下单那一刻的成本快照）。</div>');
  h += card('名册里没有进货价的商品（去补进货价）', '#8455E6',
    (c.missing_purchase_price || []).length ? ('<table class="tb"><tr><th>商品</th><th>单位</th><th>库存</th><th>成本价</th><th>在售</th></tr>' +
      c.missing_purchase_price.slice(0, 60).map(function (r) {
        return '<tr><td>' + esc(r.name) + '</td><td>' + esc(r.unit) + '</td><td>' + esc(r.stock) + '</td><td>' + esc(r.cost_price) + '</td><td>' + (r.is_active ? '是' : '否') + '</td></tr>';
      }).join('') + '</table>' + '<div class="kn">共 ' + ints(c.missing_purchase_price_count) + ' 个，只画前 60 个。</div>')
      : '<div class="dim">名册里每个商品都有进货价</div>');
  h += notesBlock(['coverage']);
  h += rawBlock(['coverage']);
  return h;
}

/* ---------------- 税账 ---------------- */
function pageTax() {
  var tx = d('tax'), iv = d('invoices');
  var h = failCard('tax') + failCard('invoices');
  h += '<div class="pagehead"><h2>税账</h2><span>' + esc(DASH.state.win.from) + ' ~ ' + esc(DASH.state.win.to) + '（按开票日期，不是创建时间）</span></div>';
  if (!tx) return h + '<div class="err">没取到数据</div>';
  var o = tx.output || {}, i = tx.input || {};
  h += '<div class="kpis">' +
    kpi('本期应交增值税', money(tx.vat_payable), '销项税 ' + money(o.tax_amount) + ' − 进项税 ' + money(i.tax_amount), '#C08A4E') +
    kpi('开出去的票（销项）', ints(o.count) + ' 张', '价税合计 ' + money(o.amount) + ' · 不含税 ' + money(o.net_amount), '#1E6FFF') +
    kpi('收到的票（进项）', ints(i.count) + ' 张', '价税合计 ' + money(i.amount) + ' · 不含税 ' + money(i.net_amount), '#00B578') +
    '</div>';
  h += card('税汇', '#C08A4E',
    kv('销项税额', money(o.tax_amount)) +
    kv('进项税额', money(i.tax_amount), 'green') +
    kv('＝ 应交增值税', money(tx.vat_payable), 'tot orange') +
    kv('缺税率的销项票（没按默认税率补）', ints(o.untaxed_count) + ' 张 · ' + money(o.untaxed_amount)) +
    kv('缺税率的进项票', ints(i.untaxed_count) + ' 张 · ' + money(i.untaxed_amount)) +
    kv('默认税率（新票用）', esc(tx.default_tax_rate) + '%') +
    kv('作废票', ints(tx.voided_count) + ' 张') +
    '<div class="kn">增值税是价外税（代收代付），<b>不进营业利润</b>；经营利润表把它单列一行，和「税金及附加」分开摆。</div>');
  h += card('按税率分组（接口 by_rate）', '#8A94A6', flatTable(tx.by_rate));
  h += card('本窗口内的发票（接口 tax-summary.invoices）', '#1E6FFF',
    (tx.invoices || []).length ? flatTable(tx.invoices) : '<div class="dim">这一段没有票</div>');
  h += card('发票台账（GET /invoices，独立接口）', '#8A94A6',
    iv && iv.length ? ('<div class="kn">接口返回 ' + ints(iv.length) + ' 张</div>' + flatTable(iv.slice(0, 40))) : '<div class="dim">这一段（按开票日期）没有票</div>');
  h += notesBlock(['tax']);
  h += rawBlock(['tax', 'invoices']);
  return h;
}

/* ---------------- 客户欠款 ---------------- */
function pageArrears() {
  var b = d('balances'), au = d('arrearsUnits');
  var h = failCard('balances') + failCard('arrearsUnits');
  h += '<div class="pagehead"><h2>客户欠款</h2><span>时点账 · 到 ' + esc(b ? b.as_of : '') + ' 为止（窗口只用来定这个上界）</span></div>';
  if (!b) return h + '<div class="err">没取到数据</div>';
  var tt = b.totals, bk = tt.buckets || {};
  var order = b.bucket_keys || ['0_30', '31_60', '61_90', 'over_90'];
  var names = { '0_30': '0-30 天', '31_60': '31-60 天', '61_90': '61-90 天', 'over_90': '90 天以上' };
  h += '<div class="kpis">' +
    kpi('该收的钱', money(tt.balance), ints(tt.debtor_count) + ' 人 · ' + ints(tt.order_count) + ' 张单', '#FF6B2C') +
    kpi('其中 90 天以上', money(bk.over_90), '最老的一笔看下面逐行', '#E53935') +
    kpi('超信用额度', ints(tt.over_limit_count) + ' 家', '额度只提示、不拦操作', num(tt.over_limit_count) ? '#E53935' : '#8A94A6') +
    '</div>';
  h += card('账龄四桶', '#FF6B2C',
    order.map(function (k) { return kv(names[k] || k, money(bk[k])); }).join('') +
    kv('＝ 该收的钱（四桶之和）', money(tt.balance), 'tot') +
    kv('预收（客户先给的钱，单列不进桶）', money(tt.prepaid)) +
    kv('没挂到名册单位上的', ints(tt.no_unit_count) + ' 人 · ' + money(tt.no_unit_balance)) +
    '<div class="kn">页面一个加减法都不做：四桶、合计、额度全是接口给的数。</div>');
  var rows = (b.rows || []).slice().sort(function (x, y) { return (num(y.balance) || 0) - (num(x.balance) || 0); });
  h += card('欠款人（共 ' + ints(rows.length) + ' 行，按欠款从多到少）', '#E53935',
    '<table class="tb"><tr><th>谁</th><th>类型</th><th>电话</th><th>欠款</th><th>最久</th><th>单数</th><th>0-30</th><th>31-60</th><th>61-90</th><th>90+</th><th>额度</th><th>剩余</th></tr>' +
    rows.map(function (r) {
      var bb = r.buckets || {};
      return '<tr' + (num(r.over_limit) ? ' class="over"' : '') + '><td>' + esc(r.name) + '</td><td>' + esc(r.kind === 'unit' ? '挂账单位' : '自然人') +
        '</td><td>' + esc(r.phone || '') + '</td><td><b>' + money(r.balance) + '</b></td><td>' + ints(r.oldest_days) + ' 天</td><td>' + ints(r.order_count) +
        '</td><td>' + money(bb['0_30']) + '</td><td>' + money(bb['31_60']) + '</td><td>' + money(bb['61_90']) + '</td><td>' + money(bb['over_90']) +
        '</td><td>' + (r.limit === null ? '<span class="dim">不限额</span>' : money(r.limit)) + '</td><td>' + (r.credit_available === null ? '<span class="dim">—</span>' : money(r.credit_available)) + '</td></tr>';
    }).join('') + '</table>');
  var withOrders = rows.filter(function (r) { return r.orders && r.orders.length; }).slice(0, 2);
  if (withOrders.length) {
    h += card('逐单明细（接口 include_orders=true，这里只展开前 2 个债务人）', '#8A94A6',
      withOrders.map(function (r) {
        return '<div class="tg">' + esc(r.name) + '（' + r.orders.length + ' 张单）</div>' + flatTable(r.orders.slice(0, 12));
      }).join(''));
  }
  h += card('挂账单位名册（GET /arrears-units）', '#6950F5',
    au && au.length ? ('<table class="tb"><tr><th>单位</th><th>电话</th><th>备注</th><th>信用额度</th></tr>' +
      au.map(function (u) {
        return '<tr><td>' + esc(u.name) + '</td><td>' + esc(u.phone || '') + '</td><td>' + esc(u.remark || '') + '</td><td>' +
          (u.credit_limit === null ? '<span class="dim">不限额（null）</span>' : money(u.credit_limit)) + '</td></tr>';
      }).join('') + '</table>' +
      '<div class="kn">额度三态：null = 不限额 / 0 = 一分都不许欠 / 有数 = 上限。这一页只看，改额度在 App 的挂账单位页。</div>')
      : '<div class="dim">名册是空的</div>');
  h += notesBlock(['balances']);
  h += rawBlock(['balances', 'arrearsUnits']);
  return h;
}

DASH.pages.profit = pageProfit;
DASH.pages.vehicle = pageVehicle;
DASH.pages.coverage = pageCoverage;
DASH.pages.tax = pageTax;
DASH.pages.arrears = pageArrears;
