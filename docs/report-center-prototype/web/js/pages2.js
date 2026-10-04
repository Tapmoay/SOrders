/* 页面 2：客户经营 / 资金收支 / 异常与审计 */

var BIZ_NAMES = {
  RECEIPT_CASH: '收现金', RECEIPT_TRANSFER: '客户转账收款', RECEIPT_ARREARS: '收回挂账', RECEIPT_PREPAID: '预收',
  PAYMENT_DRIVER: '付司机运费', PAYMENT_SALARY: '付司机工资', PAYMENT_DRIVER_ADVANCE: '司机借支', PAYMENT_SUPPLIER: '付供应商',
  PAYMENT_TAX: '交税', EXPENSE_FUEL: '加油', EXPENSE_REPAIR: '修车', EXPENSE_TOLL: '过路费', EXPENSE_PARKING: '停车费',
  EXPENSE_FINE: '罚款', EXPENSE_INSURANCE: '保险', EXPENSE_LOSS: '货损', EXPENSE_OTHER: '其它开销',
  REFUND_CUSTOMER: '退客户', REFUND_DRIVER: '退司机', ADJUST: '手工调整'
};
function bizName(k) { return BIZ_NAMES[k] || (k || '未分类'); }
function dirName(x) { return String(x).toLowerCase() === 'in' ? '进' : '出'; }

/* ---------------- 客户经营 ---------------- */
function pageCustomers() {
  var sh = d('shippers'), t = d('turnover'), b = d('balances'), cu = d('customers');
  var h = failCard('shippers') + failCard('balances');
  h += '<div class="pagehead"><h2>客户经营</h2><span>' + esc(DASH.state.win.from) + ' ~ ' + esc(DASH.state.win.to) + '</span></div>';
  var rows = sh ? (sh.shippers || []) : [];
  var okRows = rows.filter(function (r) { return r.shipper_name !== '未填货主'; });
  h += '<div class="kpis">' +
    kpi('这一段买货最多的货主', money(rows.length ? rows[0].total_amount : null),
      rows.length ? (esc(rows[0].shipper_name) + ' · ' + ints(rows[0].order_count) + ' 单') : '这一段没有已送达的单', '#6950F5') +
    kpi('已送达单量合计', ints(sumBy(rows, function (r) { return r.order_count; })) + ' 单',
      ints(rows.length) + ' 个货主名（含未填货主）', '#1E6FFF') +
    '</div>';
  h += card('货主绩效（/stats/shipper-performance 原文）', '#6950F5',
    rows.length ? ('<table class="tb"><tr><th>货主</th><th>已送达单</th><th>金额合计</th></tr>' +
      rows.map(function (r) {
        return '<tr><td>' + esc(r.shipper_name) + (r.shipper_id === null ? ' <span class="dim">（临时货主，没有系统账号）</span>' : '') +
          '</td><td>' + ints(r.order_count) + '</td><td>' + money(r.total_amount) + '</td></tr>';
      }).join('') + '</table>' +
      '<div class="kn">「未填货主」是下单时没选货主也没填临时名的单；它也是接口如实给的一行，不隐藏。</div>')
      : '<div class="dim">这一段没有已送达的单</div>');
  if (t && t.arrears_units && t.arrears_units.length) {
    h += card('这一段挂账未收 · 按单位 TOP5（来自营业纵览）', '#FF6B2C',
      t.arrears_units.map(function (u) { return kv(esc(u.name), money(u.amount)); }).join(''));
  }
  if (b) {
    var top = (b.rows || []).slice(0, 8);
    h += card('还欠着钱的（时点账 · 到 ' + esc(b.as_of) + ' 为止，全库 ' + ints(b.totals.debtor_count) + ' 人）', '#FF6B2C',
      '<table class="tb"><tr><th>谁</th><th>欠款</th><th>最久</th><th>单数</th></tr>' +
      top.map(function (r) {
        return '<tr><td>' + esc(r.name) + ' <span class="dim">' + esc(r.kind === 'unit' ? '挂账单位' : '自然人') + '</span></td><td>' + money(r.balance) +
          '</td><td>' + ints(r.oldest_days) + ' 天</td><td>' + ints(r.order_count) + '</td></tr>';
      }).join('') + '</table>' +
      '<div class="kn">这里只列前 8 行，全部 ' + ints((b.rows || []).length) + ' 行在「客户欠款」页。</div>');
  }
  h += card('客户档案（GET /customers）', '#8A94A6',
    cu ? ('接口返回 ' + ints(cu.length) + ' 条。前 10 条：' + cu.slice(0, 10).map(function (c) {
      return '<div class="kv"><span class="k">' + esc(c.name) + ' <span class="dim">' + esc(c.kind === 'registered' ? '注册' : '临时') + '</span></span><span class="v">' + esc(c.phone || '') + '</span></div>';
    }).join('')) : '<div class="dim">没取到</div>');
  h += notesBlock(['shippers', 'balances']);
  h += rawBlock(['shippers', 'balances', 'customers']);
  return h;
}

/* ---------------- 资金收支 ---------------- */
function pageFinance() {
  var cs = d('cashSummary'), cb = d('cashBreakdown'), fl = d('cashFlows'), ex = d('expenses');
  var h = failCard('cashSummary') + failCard('cashFlows');
  h += '<div class="pagehead"><h2>资金收支</h2><span>' + esc(DASH.state.win.from) + ' ~ ' + esc(DASH.state.win.to) + '</span></div>';
  if (cs) {
    h += '<div class="kpis">' +
      kpi('这一段进来的钱', money(cs.income), ints(cs.count) + ' 笔流水（含非订单的收付）', '#00B578') +
      kpi('花出去的钱', money(cs.expense), '', '#FF9F0A') +
      kpi(num(cs.net) < 0 ? '净流出' : '净流入', money(cs.net), '进 − 出', num(cs.net) < 0 ? '#E53935' : '#00B578') +
      '</div>';
    h += card('构成（服务端 SQL 侧汇总，不是页面上加法）', '#00B578',
      '<div class="tg">进项</div>' + ((cb && cb.income) || []).map(function (r) {
        return kv(bizName(r.biz_type) + ' <span class="dim">' + esc(r.biz_type) + ' × ' + ints(r.count) + '</span>', money(r.amount), 'green');
      }).join('') +
      kv('＝ 进项合计', money(cb ? cb.income_total : cs.income), 'tot') +
      '<div class="tg">出项</div>' + ((cb && cb.expense) || []).map(function (r) {
        return kv(bizName(r.biz_type) + ' <span class="dim">' + esc(r.biz_type) + ' × ' + ints(r.count) + '</span>', money(r.amount), 'orange');
      }).join('') +
      kv('＝ 出项合计', money(cb ? cb.expense_total : cs.expense), 'tot'));
  }
  h += card('流水明细（最多 100 条，按日期倒序）', '#8A94A6',
    fl && fl.length ? ('<table class="tb"><tr><th>日期</th><th>方向</th><th>类型</th><th>对象</th><th>金额</th><th>备注</th></tr>' +
      fl.map(function (r) {
        var inn = String(r.direction).toLowerCase() === 'in';
        return '<tr><td>' + esc(r.flow_date) + '</td><td class="' + (inn ? 'green' : 'orange') + '">' + dirName(r.direction) +
          '</td><td>' + esc(bizName(r.biz_type)) + '</td><td>' + esc(r.party_name || (r.party_type + '#' + (r.party_id === null ? '' : r.party_id))) +
          '</td><td class="' + (inn ? 'green' : 'orange') + '">' + money(r.amount) + '</td><td>' + esc(r.note || '') + '</td></tr>';
      }).join('') + '</table>' +
      '<div class="kn">列表有 limit，页面上的合计一律取上面的 <b>/cash-flows/summary</b>（在数据库里算完再给），⛔ 不拿这一页自己求和。</div>')
      : '<div class="dim">这一段没有流水</div>');
  h += card('开销明细（GET /expenses）', '#FF9F0A',
    ex && ex.length ? ('<table class="tb"><tr><th>日期</th><th>分类</th><th>金额</th><th>谁</th><th>挂哪</th><th>备注</th></tr>' +
      ex.slice(0, 60).map(function (r) {
        return '<tr><td>' + esc(r.exp_date) + '</td><td>' + esc(r.category) + '</td><td>' + money(r.amount) + '</td><td>' + esc(r.driver_name || r.vehicle_name || '') +
          '</td><td>' + esc(r.order_no || r.link_kind || '') + '</td><td>' + esc(r.note || '') + '</td></tr>';
      }).join('') + '</table>' + '<div class="kn">共 ' + ints(ex.length) + ' 条（接口没有分页参数，一次全给）。</div>')
      : '<div class="dim">这一段没有开销</div>');
  h += notesBlock(['cashSummary']);
  h += rawBlock(['cashSummary', 'cashBreakdown', 'cashFlows', 'expenses']);
  return h;
}

/* ---------------- 异常与审计 ---------------- */
function pageAudit() {
  var ex = d('exceptions'), lg = d('logs'), t = d('turnover');
  var h = failCard('exceptions') + failCard('logs');
  h += '<div class="pagehead"><h2>异常与审计</h2><span>' + esc(DASH.state.win.from) + ' ~ ' + esc(DASH.state.win.to) + '</span></div>';
  var rows = ex || [];
  var byCat = {};
  rows.forEach(function (r) { var c = excCat(r.exception_reason); byCat[c] = (byCat[c] || 0) + 1; });
  var cats = Object.keys(byCat).sort(function (a, b) { return byCat[b] - byCat[a]; });
  h += '<div class="kpis">' +
    kpi('异常单', ints(rows.length) + ' 单', cats.map(function (c) { return esc(c) + ' ' + byCat[c]; }).join(' · ') || '这一段没有异常单', '#E53935') +
    kpi('撤销单', ints(t ? t.cancelled_orders : null), '撤销不进营业额', '#8A94A6') +
    kpi('操作日志（最近 60 条）', ints(lg ? lg.length : null) + ' 条', '按 id 倒序，没有日期筛选参数', '#6950F5') +
    '</div>';
  h += card('异常单清单（/stats/exception-orders）', '#E53935',
    rows.length ? ('<table class="tb"><tr><th>单号</th><th>下单日</th><th>状态</th><th>原因</th><th>货主</th><th>司机</th><th>已拖</th><th>处理</th></tr>' +
      rows.slice(0, 80).map(function (r) {
        var dd = daysSince(r.order_date);
        return '<tr><td>' + esc(r.order_no) + '</td><td>' + esc(r.order_date) + '</td><td>' + esc(r.status) + '</td><td>' + esc(r.exception_reason) +
          '</td><td>' + esc(r.shipper_name || '') + '</td><td>' + esc(r.driver_name || '') + '</td><td>' + (dd === null ? '' : dd + ' 天') +
          '</td><td>' + esc(r.exception_resolution || (r.exception_resolved_at ? '已处理' : '')) + '</td></tr>';
      }).join('') + '</table>' + (rows.length > 80 ? '<div class="kn">只画了前 80 行，接口返回 ' + rows.length + ' 行。</div>' : ''))
      : '<div class="dim">这一段（按下单日）没有异常单</div>');
  h += card('操作日志（GET /operation-logs，全局最近 60 条）', '#6950F5',
    lg && lg.length ? lg.map(function (r) {
      var cc = r.change_content || '';
      var pretty = cc;
      try { pretty = JSON.stringify(JSON.parse(cc), null, 1); } catch (e) { pretty = cc; }
      return '<div class="logrow"><div class="lh"><b>' + esc(r.action) + '</b><span>' + esc(r.created_at) + ' · ' + esc(r.operator_name || ('用户#' + r.operator_id)) +
        (r.order_no ? ' · ' + esc(r.order_no) : '') + '</span></div><pre class="lc">' + esc(pretty) + '</pre></div>';
    }).join('') + '<div class="kn">这条接口<b>没有日期参数</b>（只有 order_id / operator_id / skip / limit），所以它永远是最新的 60 条，跟窗口无关 —— 这也是它和别的页不同的地方。</div>'
      : '<div class="dim">没有日志</div>');
  h += notesBlock(['exceptions']);
  h += rawBlock(['exceptions', 'logs']);
  return h;
}

DASH.pages.customers = pageCustomers;
DASH.pages.finance = pageFinance;
DASH.pages.audit = pageAudit;
