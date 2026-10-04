/* 原始单据：一层层点到底的最后一站（单据 → 订单 → 商品行） */
function argOf() { return decodeURIComponentSafe(DASH.state.narg || DASH.narg || ''); }
function arrOf(key) { var b = d(key); return Array.isArray(b) ? b : ((b && (b.items || b.rows)) || []); }
function findIn(rows, id) { for (var i = 0; i < rows.length; i++) { if (String(rows[i].id) === String(id)) return rows[i]; } return null; }
function findDoc(kind, id) {
  if (kind === 'exp') return findIn(arrOf('expenses'), id);
  if (kind === 'cash') return findIn(arrOf('cashFlows'), id);
  if (kind === 'inv') return findIn(arrOf('invoices'), id);
  if (kind === 'pay') return findIn(arrOf('payables'), id);
  if (kind === 'log') return findIn(arrOf('logs'), id);
  if (kind === 'veh') return findIn(arrOf('vehicles'), id);
  if (kind === 'mov') {
    var ks = Object.keys(DASH.oc);
    for (var i = 0; i < ks.length; i++) {
      var r = DASH.oc[ks[i]];
      if (r && r.body) { var m = findIn(Array.isArray(r.body) ? r.body : [], id); if (m) return m; }
    }
  }
  return null;
}
var DOC_NAME = { exp: '费用单', cash: '现金流水', inv: '发票', mov: '库存流水', pay: '应付单', log: '操作日志', veh: '车辆台账' };
var DOC_PREF = {
  exp: [['exp_date', '日期'], ['category', '类目'], ['amount', '金额', '$'], ['vehicle_name', '车'], ['driver_name', '司机'], ['order_no', '挂着的单'], ['link_kind', '挂在哪'], ['note', '说明'], ['operator_id', '经手人'], ['created_at', '记于']],
  cash: [['flow_date', '日期'], ['direction', '方向', 'dir'], ['amount', '金额', '$'], ['party_name', '对方'], ['channel', '收付方式'], ['biz_type', '业务类型', 'biz'], ['order_no', '挂着的单'], ['doc_id', '对应单据'], ['note', '备注'], ['operator_id', '经手人'], ['created_at', '记于']],
  inv: [['invoice_no', '发票号'], ['direction', '方向', 'dir'], ['amount', '金额', '$'], ['tax_amount', '税额', '$'], ['status', '状态'], ['invoice_date', '开票日期'], ['customer_name', '客户'], ['supplier_name', '供应商'], ['purchase_order_ids', '关联采购单', 'join'], ['ledger_ids', '账本行', 'join']],
  mov: [['created_at', '时间'], ['change', '变动'], ['source', '来源'], ['note', '说明'], ['order_no', '挂着的单'], ['unit_cost', '单价', '$'], ['status', '状态']],
  pay: [['doc_date', '单据日期'], ['supplier_name', '供应商'], ['title', '摘要'], ['category', '类目'], ['amount', '金额', '$'], ['paid', '已付', '$'], ['unpaid', '未付', '$'], ['payment_count', '付款次数']],
  log: [['created_at', '时间'], ['operator_name', '操作人'], ['action', '动作'], ['order_no', '订单'], ['change_content', '改了什么']],
  veh: [['plate_no', '车牌'], ['driver_name', '司机'], ['vehicle_type', '类型'], ['purchase_price', '购置价', '$'], ['purchase_date', '购置日期'], ['useful_life_years', '年限'], ['residual_rate', '残值率'], ['depreciation_covered', '折旧算得出', 'bool'], ['is_active', '在用', 'bool']]
};
function docVal(v, t) {
  if (t === '$') return money(v);
  if (t === 'dir') return (v === 'IN' || v === 'income' || v === '收入') ? '收入' : ((v === 'OUT' || v === 'expense' || v === '支出') ? '支出' : esc(String(v)));
  if (t === 'biz') return esc(bizName(v));
  if (t === 'join') return Array.isArray(v) ? (v.length ? esc(v.join('、')) : '—') : esc(String(v));
  if (t === 'bool') return v ? '是' : '没填';
  return esc(String(v));
}
function docKV(r, pref) {
  var seen = {}, out = '';
  pref.forEach(function (f) {
    var k = f[0];
    if (!(k in r)) return;
    seen[k] = 1;
    var v = r[k];
    if (v === null || v === undefined || v === '') return;
    out += kv(f[1], docVal(v, f[2]), (f[2] === '$' && num(v) < 0) ? 'red' : '');
  });
  Object.keys(r).forEach(function (k) {
    if (seen[k]) return;
    var v = r[k];
    if (v === null || v === undefined || v === '' || typeof v === 'object') return;
    out += kv(k, esc(String(v)), 'dimv');
  });
  return out;
}
/* 一行「单据」：点进去就是那张原始单据 */
function rowDoc(label, value, note, kind, id, cls) { return nrow(label, value, cls || '', 't-doc', kind + ':' + id, note || ''); }
DASH.pnoarg = { 't-doc': 1, 'p-car': 1 };
tnode('t-doc', '原始单据', function () {
  var a = argOf();
  var p = a.indexOf(':');
  var kind = p > 0 ? a.slice(0, p) : '', id = p > 0 ? a.slice(p + 1) : '';
  var h = crumb();
  var r = findDoc(kind, id);
  if (!r) return h + '<div class="err">没找到这张单据（' + esc(a) + '）</div>';
  var big = (num(r.amount) !== null) ? money(r.amount) : ((num(r.change) !== null) ? ints(r.change) : (r.plate_no || r.title || r.action || r.status || '单据'));
  var sub = (r.note || r.title || r.action || r.category || r.source || '');
  h += kpi(DOC_NAME[kind] || '单据', big, (DOC_NAME[kind] || '') + (sub ? ' · ' + esc(String(sub)) : ''), '#1E6FFF');
  h += card('这张单据（接口给什么就是什么）', '#1E6FFF', docKV(r, DOC_PREF[kind] || []));
  if (r.order_id) {
    h += card('挂在的订单', '#00B578',
      nrow('看这一单' + (r.order_no ? ' ' + esc(r.order_no) : ''), '去看', '', 'o-one', r.order_id, '订单就是最底层：里面有商品行、货损、退货、收款') +
      '<div class="kn">再往下就是这一单的商品行，那已经是最细的一格了。</div>');
  } else if (r.order_no) {
    h += card('挂着的单', '#00B578', kv('单号', esc(r.order_no)) + '<div class="kn">接口只给了单号、没给订单 id，所以点不进去。</div>');
  }
  var extra = '';
  if (kind === 'exp' && r.vehicle_id) extra += nrow('这辆车', '去看', '', 't-veh', '', '按车看这一段的成本');
  if (kind === 'cash' && r.party_type === 'DRIVER' && r.party_id) extra += nrow('这个司机', '去看', '', 'p-drv', '', '他的运费与待结');
  if (kind === 'cash' && r.party_type === 'CUSTOMER' && r.party_id) extra += nrow('这个客户', '去看', '', 'p-cust', '', '买了多少、欠了多少');
  if (kind === 'pay') {
    var pays = (d('cashFlows') || []).filter(function (x) { return String(x.doc_id) === String(r.id) && x.biz_type === 'PAYMENT_SUPPLIER'; });
    if (pays.length) h += card('这一张的付款（' + ints(pays.length) + ' 次 · 点一笔就是那张流水）', '#00B578', pays.map(function (x) {
      return rowDoc(esc(x.flow_date || '') + ' · ' + esc(x.party_name || ''), money(x.amount), esc(x.note || ''), 'cash', x.id, '');
    }).join('') + '<div class="kn">付出去的钱在这里逐笔对得上；接口的 payment_count 说的就是这几笔。</div>');
  }
  if (extra) h += card('从这张单据还能去哪', '#8A94A6', extra);
  h += '<div class="kn" style="padding:0 4px">链条：报表上的数 → 单据 → 订单 → 商品行。每一层都能看到接口给的原始字段。</div>';
  return h;
});
/* ---- 车辆成本：每台车 → 这台车的每一笔开销 ---- */
tnode('t-veh', '车辆成本', function () {
  var V = d('vehicle');
  var h = crumb();
  if (!V) return h + failCard('vehicle');
  h += kpi('这一段车辆成本', money(V.total_cost), ints(V.vehicle_count) + ' 台 · 其中折旧 ' + money(V.depreciation_total), '#546E7A');
  h += card('逐台车（点一台看它的每一笔）', '#546E7A', (V.per_vehicle || []).map(function (p) {
    return nrow((p.plate_no || '—') + (p.driver_name ? ' · ' + p.driver_name : ''), money(p.total_cost), '', 'p-car', p.plate_no, '开销 ' + money(p.expense_total) + ' · 配送 ' + money(p.delivery_cost) + ' · 折旧 ' + money(p.depreciation));
  }).join('') + '<div class="kn">点一台车进去，能看到这台车这一段的每一笔开销，再点一笔就是那张单据。</div>');
  h += card('买车的钱与票据', '#8A94A6',
    ((V.per_vehicle || []).length ? (V.per_vehicle || []).map(function (r) {
      var full = r.purchase_price ? money(r.purchase_price) : '';
      return nrow(esc(r.plate_no || '') + ' 购置价', full || '台账没填', full ? '' : 'dimv', '', '', full ? ('购置日 ' + esc(r.purchase_date || '—')) : '');
    }).join('') : '<div class="dim">接口没回车辆清单</div>') +
    '<div class="kn">上面每一行的「台账没填」= 接口的 purchase_price 是空的 ⇒ 算不出月折旧（这就是折旧 0 的原因），也没有购车票据可查。这台车这一段的<b>开销票据</b>在下面逐笔能点开。</div>');
  h += card('这三笔钱各是什么', '#8A94A6',
    kv('这台车的开销', money(sumOf(V.per_vehicle || [], function (r) { return r.expense_total; })), 'orange') +
    kv('挂靠司机配送成本', money(sumOf(V.per_vehicle || [], function (r) { return r.delivery_cost; })), 'orange') +
    kv('折旧', money(V.depreciation_total), V.depreciation_total ? '' : 'dimv') +
    kv('＝ 合计', money(V.total_cost), 'tot') +
    '<div class="kn">车上的开销和司机运费<b>已经在利润表里扣过了</b>，这里只是换个切法看，不重复扣。</div>');
  return h;
});
tnode('p-car', '一辆车', function () {
  var plate = argOf();
  var V = d('vehicle'), h = crumb();
  var p = null;
  ((V && V.per_vehicle) || []).forEach(function (x) { if (x.plate_no === plate) p = x; });
  var mine = arrOf('expenses').filter(function (r) { return (r.vehicle_name || '') === plate; });
  h += kpi(plate, money(p && p.total_cost), '这一段：这台车的开销 + 挂靠司机的配送成本 + 折旧', '#546E7A');
  h += card('这台车的开销（每一笔点开就是单据）', '#FF9F0A', mine.length ? mine.map(function (r) {
    return rowDoc((r.exp_date || '') + ' · ' + (r.category || '没分类'), money(r.amount), (r.note || '') + (r.order_no ? ' · 挂着单 ' + r.order_no : ''), 'exp', r.id, 'orange');
  }).join('') : '<div class="dim">这一段这台车没有开销单据</div>');
  if (mine.length) h += '<div class="kn" style="padding:0 4px">逐笔相加 ' + money(sumOf(mine, function (r) { return r.amount; })) + '，和上面「这台车的开销 ' + money(p && p.expense_total) + '」对得上。</div>';
  h += card('这台车的三笔成本', '#546E7A',
    kv('开销', money(p && p.expense_total), 'orange') +
    kv('挂靠司机配送成本', money(p && p.delivery_cost), 'orange') +
    kv('折旧', money(p && p.depreciation), num(p && p.depreciation) ? '' : 'dimv') +
    kv('＝ 合计', money(p && p.total_cost), 'tot'));
  var vrec = null;
  arrOf('vehicles').forEach(function (x) { if (x.plate_no === plate) vrec = x; });
  if (vrec) h += card('这台车本身（台账）', '#8A94A6', docKV(vrec, DOC_PREF.veh));
  else h += card('这台车本身（台账）', '#8A94A6', kv('台账', '没找到这台车', 'dimv'));
  return h;
});
