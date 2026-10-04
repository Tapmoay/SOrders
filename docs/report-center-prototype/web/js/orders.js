/* 订单层（下钻终点）：订单清单 → 单张订单。数据来自 GET /orders 与 GET /orders/{id} */
DASH.olist = null;
DASH.oid = 0;
DASH.ono = '';
DASH.oc = {};
DASH.owed = null;
async function apiGetH(path) {
  var t0 = Date.now();
  var res = await fetch(API_BASE + path, { headers: { Authorization: 'Bearer ' + DASH.state.token } });
  var txt = await res.text();
  var body = null;
  try { body = JSON.parse(txt); } catch (e) { body = txt.slice(0, 200); }
  return { ok: res.ok, status: res.status, body: body, ms: Date.now() - t0, trunc: res.headers.get('X-Truncated'), limit: res.headers.get('X-Result-Limit') };
}
function loadOC(key, path) {
  if (DASH.oc[key]) return;
  DASH.oc[key] = 'loading';
  apiGetH(path).then(function (r) { DASH.oc[key] = r; render(); },
    function () { DASH.oc[key] = { ok: false, status: 0, body: null, trunc: null, limit: null }; render(); });
}
function goOrderList(cfg) { DASH.olist = cfg || {}; goNode('o-list'); }
function goOrder(id, no) { DASH.oid = id; DASH.ono = no || ''; goNode('o-one'); }
function oq(params) {
  var p = [];
  Object.keys(params).forEach(function (k) {
    var v = params[k];
    if (v === null || v === undefined || v === '') return;
    p.push(k + '=' + enc(String(v)));
  });
  return p.length ? ('?' + p.join('&')) : '';
}
function buildOrderPath(cfg) {
  var w = DASH.state.win, params = {};
  Object.keys((cfg && cfg.params) || {}).forEach(function (k) { params[k] = cfg.params[k]; });
  if (cfg && cfg.win === 'delivered') { params.delivered_from = w.from; params.delivered_to = w.to; }
  else if (cfg && cfg.win === 'created') { params.date_from = w.from; params.date_to = w.to; }
  params.limit = (cfg && cfg.limit) || 300;
  return '/orders' + oq(params);
}
function okey(prefix, cfg) { var w = DASH.state.win; return prefix + '|' + JSON.stringify((cfg && cfg.params) || {}) + '|' + ((cfg && cfg.win) || '') + '|' + w.from + '|' + w.to + '|' + ((cfg && cfg.limit) || 300); }
function orow(label, value, cls, id, no, note) {
  return '<div class="trow go" onclick="goOrder(' + ints(id) + ',&apos;' + esc(no || '') + '&apos;)">' +
    '<span class="tl">' + esc(label) + (note ? '<i class="tn">' + note + '</i>' : '') + '</span>' +
    '<span class="tv ' + (cls || '') + '">' + value + '<i class="ta">&#8250;</i></span></div>';
}
function olrow(label, note, cfg) {
  var j = JSON.stringify(cfg).replace(/"/g, '&apos;');
  return '<div class="trow go" onclick="goOrderList(' + j + ')">' +
    '<span class="tl">' + esc(label) + (note ? '<i class="tn">' + note + '</i>' : '') + '</span>' +
    '<span class="tv"><i class="ta">&#8250;</i></span></div>';
}
function goOwed(name) {
  var rows = (d('balances') || {}).rows || [];
  DASH.owed = null;
  rows.forEach(function (r) { if (String(r.name) === String(name)) DASH.owed = r; });
  goNode('p-owed');
}
function owdrow(label, note, name) {
  var j = JSON.stringify(name).replace(/"/g, '&apos;');
  return '<div class="trow go" onclick="goOwed(' + j + ')">' +
    '<span class="tl">' + esc(label) + (note ? '<i class="tn">' + note + '</i>' : '') + '</span>' +
    '<span class="tv"><i class="ta">&#8250;</i></span></div>';
}
function statusName(s) {
  var m = { PENDING_DISPATCH: '待派单', DISPATCHED: '已派单', ACCEPTED: '已接单', DELIVERED: '已送达', CANCELLED: '已撤销', RETURNED: '已退货' };
  return m[s] || s;
}
tnode('o-list', '订单清单', function () {
  var cfg = DASH.olist || {};
  var key = okey('ol', cfg), path = buildOrderPath(cfg);
  loadOC(key, path);
  var c = DASH.oc[key];
  var h = crumb();
  if (!c || c === 'loading') return h + card(cfg.title || '订单清单', '#1E6FFF', '<div class="kn">正在取 GET ' + esc(path) + ' ……</div>');
  if (!c.ok) return h + card(cfg.title || '订单清单', '#E53935', '<div class="err">接口返回 ' + ints(c.status) + '：GET ' + esc(path) + '</div>');
  var rows = Array.isArray(c.body) ? c.body : [];
  var sum = sumOf(rows, function (o) { return o.goods_amount; });
  h += '<div class="kpis">' + kpi('这一层订单', ints(rows.length) + ' 张', esc(cfg.title || '按条件筛出来的'), '#1E6FFF') + kpi('商品金额合计', money(sum), '页面逐单相加（接口不给合计）', '#00B3A4') + '</div>';
  h += card('订单（点一张看它的全部明细）', '#1E6FFF',
    (rows.length ? rows.map(function (o) {
      return orow((o.shipper_name || o.temp_shipper_name || '（无货主名）') + ' · ' + String(o.order_date || '').slice(0, 10),
        money(o.goods_amount), (num(o.arrears_amount) ? 'orange' : ''), o.id, o.order_no,
        esc(o.order_no) + ' · ' + esc(statusName(o.status)) + (o.driver_name ? (' · 司机 ' + esc(o.driver_name)) : '') + (num(o.arrears_amount) ? (' · 挂账 ' + money(o.arrears_amount)) : ''));
    }).join('') : '<div class="dim">这一段这个条件下一张单都没有</div>') +
    '<div class="kn">接口：GET ' + esc(path) + '（' + ints(rows.length) + ' 张' + ((c.trunc === '1') ? '，<b>接口说还有更多</b>：X-Truncated=1，只回了 limit=' + esc(String(c.limit)) + '，接口不给总数' : '') + '）</div>');
  h += card('口径（/orders 的坑）', '#8A94A6',
    nrow('截断', '默认只回 300 张', '', '', '', 'limit 最大 5000，没有 offset；靠响应头 X-Truncated 告诉你还有更多，不给总数') +
    nrow('能按什么筛', '货主 / 状态 / 搜索词 / 日期', '', '', '', '没有 driver_id、product_id、vehicle_id —— 按司机取单只能用 q=司机姓名（同名会串）') +
    nrow('日期口径', '两条窗口', '', '', '', 'date_from/to 按下单日；delivered_from/to 按送达日。这一段用的是' + (cfg.win === 'created' ? '下单日' : '送达日')));
  if (cfg.note) h += card('这一层是怎么来的', '#7C4DFF', '<div class="kn">' + cfg.note + '</div>');
  return h;
});
tnode('o-one', '一张订单', function () {
  var id = DASH.oid, key = 'o|' + id;
  loadOC(key, '/orders/' + ints(id));
  var c = DASH.oc[key];
  var h = crumb();
  if (!c || c === 'loading') return h + card('一张订单', '#1E6FFF', '<div class="kn">正在取 GET /orders/' + ints(id) + ' ……</div>');
  if (!c.ok) return h + card('一张订单', '#E53935', '<div class="err">接口返回 ' + ints(c.status) + '：GET /orders/' + ints(id) + '</div>');
  var o = c.body || {};
  var lines = o.order_products || [];
  var gm = num(o.goods_amount), rt = num(o.returned_amount), st = num(o.settled_amount), rf = num(o.refunded_amount), ar = num(o.arrears_amount);
  var diff = (gm - rt) - ((st - rf) + ar);
  h += card('这张单', '#1E6FFF',
    nrow('单号', esc(o.order_no), '', '', '', esc(statusName(o.status)) + (o.is_exception ? (' · <span class="red">异常：' + esc(o.exception_reason || '') + '</span>') : '')) +
    nrow('货主', esc(o.shipper_name || o.temp_shipper_name || '—'), '', '', '', '') +
    nrow('司机', esc(o.driver_name || '还没派'), '', '', '', esc(o.driver_phone || '')) +
    nrow('下单 / 送达', String(o.created_at || '').slice(0, 10) + ' → ' + String(o.delivered_at || '').slice(0, 10), '', '', '', '') +
    nrow('地址', esc(o.delivery_description || '—'), '', '', '', esc(o.address_detail || '')));
  h += card('这张单的钱（接口给的四个数 + 挂账）', '#00B3A4',
    nrow('商品金额', money(o.goods_amount), '', '', '', '订单上所有商品行的合计') +
    nrow('退货金额', '− ' + money(o.returned_amount), '', '', '', '退回来的部分') +
    nrow('已收', money(o.settled_amount), 'green', '', '', '收到手的（现金或核销）') +
    nrow('已退', '− ' + money(o.refunded_amount), '', '', '', '') +
    nrow('还欠（挂账）', money(o.arrears_amount), num(o.arrears_amount) ? 'orange' : '', '', '', esc(o.paid ? '接口说这张单已收款' : ('未收款 · 付款方式 ' + (o.payment_method || '—') + (o.arrears_unit_name ? (' · 挂账单位 ' + o.arrears_unit_name) : '')))) +
    nrow('恒等式核对', (Math.abs(diff) < 0.005 ? '对得上' : ('差 ' + money(diff))), (Math.abs(diff) < 0.005 ? 'green' : 'red'), '', '', '商品金额 − 退货 = (已收 − 已退) + 挂账；页面只核对，不改数'));
  h += card('商品行（' + ints(lines.length) + ' 行）', '#7C4DFF',
    (lines.length ? lines.map(function (l) {
      return nrow(esc(l.product_name_snapshot || '—'), money(l.line_total), '', '', '',
        esc(String(l.quantity)) + ' ' + esc(l.unit || '') + ' × ' + money(l.unit_price) + (num(l.damage_quantity) ? (' · <span class="red">货损 ' + esc(String(l.damage_quantity)) + '</span>') : '') + (num(l.returned_quantity) ? (' · 已退 ' + esc(String(l.returned_quantity))) : ''));
    }).join('') : '<div class="dim">这张单没有商品行</div>') +
    '<div class="kn">货损件数与已退件数挂在商品行上（接口 order_products[]）；货损在送达时按行登记，同时生成一条「货损」现金流水。</div>');
  var extra = [];
  if (o.damage_note) extra.push(nrow('货损备注', esc(o.damage_note), '', '', '', ''));
  if (o.driver_remark) extra.push(nrow('司机备注', esc(o.driver_remark), '', '', '', ''));
  if (o.internal_notes) extra.push(nrow('内部备注', esc(String(o.internal_notes).slice(0, 80)), '', '', '', '派单员可见，货主看不到'));
  var photos = o.delivery_photo_urls || [];
  if (photos.length) extra.push(nrow('送达照片', ints(photos.length) + ' 张', '', '', '', '存在 /static/uploads/delivery/…，这里不内嵌'));
  if (o.remark) extra.push(nrow('下单备注', esc(o.remark), '', '', '', ''));
  if (extra.length) h += card('备注与照片', '#FF9F0A', extra.join(''));
  h += card('这一单在别的接口里也有', '#8A94A6',
    '<div class="kn">· 欠款页的逐单明细（/reports/customer-balances 的 rows[].orders[]）里有这一张，带账龄与已收。</div>' +
    '<div class="kn">· 现金流水（/cash-flows）每行有 order_id，能对上这一单。</div>' +
    '<div class="kn">· 开销（/expenses）每行有 order_id + order_no。</div>' +
    '<div class="kn">· 发票（/invoices）没有 order_id，要经账本行（ledger_ids）才到订单。</div>' +
    '<div class="kn">· 这一单的收款核销记录：GET /shipper-ledger/settlements?order_id=' + ints(id) + '（接口是有的，本轮没接）。</div>');
  return h;
});
tnode('p-owed', '欠款逐单', function () {
  var row = DASH.owed;
  var h = crumb();
  if (!row) return h + card('欠款逐单', '#FF6B2C', '<div class="kn">没有选中的人，回上一页点一个。</div>');
  var orders = row.orders || [];
  var b = d('balances');
  h += '<div class="kpis">' + kpi('这个人还欠', money(row.balance), ints(row.order_count) + ' 张单 · 最老 ' + ints(row.oldest_days) + ' 天', '#FF6B2C') + kpi('逐单明细', ints(orders.length) + ' 张', '接口 customer-balances?include_orders=true', '#7C4DFF') + '</div>';
  h += card('逐单（点一张看它的全部明细）', '#FF6B2C',
    (orders.length ? orders.map(function (o) {
      return orow((o.shipper_name || row.name) + ' · 送达 ' + String(o.delivered_on || '').slice(0, 10), money(o.arrears), 'orange', o.order_id, o.order_no,
        esc(o.order_no) + ' · 应收 ' + money(o.receivable) + ' · 已收 ' + money(o.collected) + ' · 账龄 ' + ints(o.days) + ' 天（' + esc(o.bucket) + '）');
    }).join('') : '<div class="dim">这个人没有逐单明细</div>') +
    '<div class="kn">时点账：到 ' + esc((b && b.as_of) || '—') + ' 为止。四桶与合计都是接口给的，页面不加。</div>');
  return h;
});
var baseCust1 = DASH.pages['p-cust1'];
tnode('p-cust1', '客户', function () {
  var id = DASH.narg || '', name = '';
  shipperRows().forEach(function (r) { if (String(r.shipper_id) === String(id)) name = r.shipper_name; });
  var owed = null, rows = (d('balances') || {}).rows || [];
  rows.forEach(function (r) { if (String(r.name) === String(name)) owed = r; });
  var extra = card('再往下（按单看）', '#1E6FFF',
    olrow('他这一段送达的订单', 'GET /orders?shipper_id=' + esc(String(id)) + ' + 这一段送达日', { title: (name || '这个客户') + ' 这一段送达的订单', params: { shipper_id: id }, win: 'delivered' }) +
    (owed ? owdrow('他的欠款逐单（' + money(owed.balance) + ' · ' + ints((owed.orders || []).length) + ' 张）', '接口 customer-balances 的逐单明细', name) : '') +
    '<div class="kn">订单清单里每一张都能点进「一张订单」，看商品行、货损与收款情况。</div>');
  return baseCust1() + extra;
});
/* 把五张表接上订单层（包一层，不改原节点） */
function wrapPage(id, label, extraFn) {
  var base = DASH.pages[id];
  if (!base) return;
  tnode(id, label, function () { return base() + extraFn(); });
}
wrapPage('t-ops', '运营分析表', function () {
  return card('再往下（按单看）', '#1E6FFF',
    olrow('这一段送达的全部订单', 'GET /orders?delivered_from/to（这一段）', { title: '这一段送达的全部订单', win: 'delivered' }) +
    nrow('按商品拆到订单', '去商品页点一个商品', '', 'p-cost', '', '每个商品点进去就是它的订单清单，再点一张到订单详情') +
    nrow('按客户拆到订单', '去客户页点一个货主', '', 'p-cust', '', '货主的订单清单：GET /orders?shipper_id=') +
    nrow('按司机拆到订单', '接口没有 driver_id', '', 'p-drv', '', '只能 q=司机姓名（同名会串）或 /freight-settlement 的 groups[].orders[]') +
    '<div class="kn">订单列表只认四种筛法：状态 / 搜索词 / 货主 / 日期区间；订单表里没有车辆字段，所以「按车看订单」在本数据模型里做不到。</div>');
});
wrapPage('t-balance', '资产负债表', function () {
  return card('再往下（按单看）', '#FF6B2C',
    nrow('别人欠我的钱', '按人 → 逐单', '', 'p-cust', '', '欠款逐单来自 /reports/customer-balances?include_orders=true（每行带 order_id）') +
    nrow('我欠司机的钱', '按司机看', '', 'p-drv', '', '司机侧三段（运费→账单→结算）都能点回订单') +
    '<div class="kn">库存能看结存与估算金额（库存页），应付能看供应商与逐张应付单（应付页）；但两者都只有<b>此刻</b>的数——没有期初/期末快照，也没有带 as_of 的历史时点；借款 / 实收资本系统里没有这个概念。</div>');
});
wrapPage('t-cash', '现金流量表', function () {
  return card('再往下（按单看）', '#00B3A4',
    olrow('收款流水对应的订单', '先看这一段送达的订单，再点单张', { title: '这一段送达的订单（对现金流水）', win: 'delivered', note: '现金流水每行有 order_id；滚动收款的行 order_id 为空（不绑单）。' }) +
    '<div class="kn">现金流水行上有 order_id + doc_id（doc_id 指向收款单 / 开销单 / 结算单 / 应付单，看 biz_type 决定是哪张表）。发票没有 order_id，要经账本行才到订单。</div>');
});
wrapPage('t-kpi', '关键指标表', function () {
  return card('再往下', '#8A94A6', '<div class="kn">关键指标都是比值，往下就是回到上面各表：毛利率→利润表，应收周转→欠款逐单，成本覆盖率→商品页，保本点→期间费用。</div>');
});
/* 客户页：欠得最多的三个人 → 逐单（p-owed） */
function topOwed(B) {
  var rows = (B.rows || []).slice().sort(function (a, b) { return (Number(b.balance) || 0) - (Number(a.balance) || 0); }).slice(0, 3);
  if (!rows.length) return '';
  return '<div class="kn">欠得最多的三个（点一个进去看他的逐单）：</div>' + rows.map(function (r) {
    return owdrow(r.name, ints(r.order_count) + ' 张单 · 最老 ' + ints(r.oldest_days) + ' 天 · ' + money(r.balance), r.name);
  }).join('');
}
/* 回首页时清掉下钻轨迹（否则面包屑会留着上一条链） */
(function () {
  var g0 = go;
  window.go = function (p) {
    if (p === 'dash' || p === 'login') { DASH.state.trail = []; }
    return g0.apply(null, arguments);
  };
})();
