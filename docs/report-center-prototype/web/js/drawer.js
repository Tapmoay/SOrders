/* 左侧抽屉（原来的页面入口）+ 数值不带多余的零 + 报表页不再出现 JSON 样式 */
var _money = money;
money = function (v) {
  var n = num(v);
  if (n === null) return '—';
  var s = n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (s.slice(-3) === '.00') s = s.slice(0, -3);
  return s;
};
var _rawBlock = rawBlock;
rawBlock = function () { return ''; };
/* ---------- 图标 ---------- */
var SVG1 = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">';
var DIC = {
  home: SVG1 + '<path d="M3.5 10.8 12 3.5l8.5 7.3"/><path d="M6 9.6V20h12V9.6"/></svg>',
  menu: SVG1 + '<path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/></svg>',
  alert: SVG1 + '<path d="M12 4.5 21 19.5H3z"/><path d="M12 10v4"/><path d="M12 17h.01"/></svg>',
  truck: SVG1 + '<path d="M3 7h10v9H3z"/><path d="M13 10h4l3 3v3h-7z"/><circle cx="7" cy="18" r="1.6"/><circle cx="17" cy="18" r="1.6"/></svg>',
  box: SVG1 + '<path d="M12 3.5 20 8v8l-8 4.5L4 16V8z"/><path d="M4 8l8 4.5L20 8"/><path d="M12 12.5V20.5"/></svg>',
  users: SVG1 + '<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19c0-3 2.5-5 5.5-5s5.5 2 5.5 5"/><path d="M16 6.5a3 3 0 0 1 0 6"/><path d="M17.5 19c0-2.2-.8-3.9-2-5"/></svg>',
  car: SVG1 + '<path d="M4 15v-3l1.8-4h12.4L20 12v3"/><path d="M3 15h18v3h-3"/><path d="M6 18H3v-3"/><circle cx="7.5" cy="18" r="1.6"/><circle cx="16.5" cy="18" r="1.6"/></svg>',
  receipt: SVG1 + '<path d="M6 3.5h12v17l-3-2-3 2-3-2-3 2z"/><path d="M9 8.5h6"/><path d="M9 12.5h6"/></svg>',
  doc: SVG1 + '<path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4"/><path d="M9 13h6"/><path d="M9 16.5h4"/></svg>',
  out: SVG1 + '<path d="M15 5.5H19v13h-4"/><path d="M11 8.5 7.5 12l3.5 3.5"/><path d="M7.5 12H16"/></svg>'
};
DIC.turnover = IC.trend; DIC.customers = IC.wallet; DIC.finance = IC.flow;
DIC.profit = IC.pie; DIC.coverage = IC.target; DIC.tax = DIC.receipt;
DIC.products = DIC.box; DIC.shippers = DIC.users; DIC.vehicle = DIC.car; DIC.drivers = DIC.truck; DIC.audit = DIC.alert;
/* ---------- 抽屉 ---------- */
function drawerHTML() {
  function row(id, ic, name, sub) {
    var on = DASH.state.page === id ? ' on' : '';
    return '<button class="dwrow' + on + '" onclick="go(&apos;' + id + '&apos;);closeDrawer();">' +
      '<span class="dwi">' + ic + '</span><span class="dwt">' + esc(name) + '<i>' + esc(sub) + '</i></span></button>';
  }
  var rows = ENTRIES.map(function (e) { return row(e[0], DIC[e[0]] || DIC.doc, e[1], e[2]); }).join('');
  return '<div class="dw' + (DASH.dw ? ' open' : '') + '" onclick="closeDrawer();">' +
    '<div class="dwm" onclick="event.stopPropagation();">' +
    '<div class="dwh">报表中心<i>手机样式 · 连的是真后端 127.0.0.1:8000</i></div>' +
    row('dash', DIC.home, '报表首页', '五张表 · 一层层点到订单') +
    '<div class="dws">原来的页面</div>' + rows +
    '<div class="dws">别的</div>' +
    row('dev-raw', DIC.doc, '接口原文', '对照用，平时不用看') +
    '<button class="dwrow" onclick="closeDrawer();logout(&apos;已退出登录&apos;);"><span class="dwi">' + DIC.out +
    '</span><span class="dwt">退出登录<i>换个人看</i></span></button>' +
    '<div class="dwnote">数字都来自接口原文，页面自己不做加减；报表页面上不出现 JSON。</div>' +
    '</div></div>';
}
function openDrawer() { DASH.dw = 1; render(); }
function closeDrawer() { if (!DASH.dw) return; DASH.dw = 0; render(); }
function goD(id) { closeDrawer(); go(id); }
var _headPrev = headHTML;
headHTML = function () {
  var h = _headPrev();
  var mic = '<button class="ib mic" onclick="openDrawer();return false;">' + DIC.menu + '</button>';
  if (DASH.state.page === 'dash') h = h.replace('<span class="ib ghost"></span>', mic);
  else h = h.replace('</button>', '</button>' + mic);
  return h;
};
var _renderPrev = render;
render = function () {
  _renderPrev();
  var ph = document.querySelector('.phone');
  if (ph && DASH.state.token) {
    ph.insertAdjacentHTML('beforeend', drawerHTML());
    swipeBind();
  }
};
/* 从左边往右滑打开、往左滑关掉 */
function swipeBind() {
  var ph = document.querySelector('.phone');
  if (!ph || ph.getAttribute('data-sw')) return;
  ph.setAttribute('data-sw', '1');
  var x0 = null;
  ph.addEventListener('touchstart', function (e) { x0 = e.touches[0].clientX; }, { passive: true });
  ph.addEventListener('touchend', function (e) {
    if (x0 === null) return;
    var dx = e.changedTouches[0].clientX - x0;
    if (dx > 55 && !DASH.dw) openDrawer();
    if (dx < -55 && DASH.dw) closeDrawer();
    x0 = null;
  }, { passive: true });
}
document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && DASH.dw) closeDrawer(); });
/* ---------- 接口原文（只在抽屉里进） ---------- */
DASH.pages['dev-raw'] = function () {
  var keys = ['turnover', 'profit', 'balances', 'tax', 'cashSummary', 'cashBreakdown', 'cashFlows', 'expenses', 'invoices', 'drivers', 'shippers', 'exceptions', 'products', 'vehicle', 'vehicles', 'coverage', 'suppliers', 'invSummary', 'stock', 'payables', 'logs', 'arrearsUnits'];
  var body = keys.map(function (k) {
    var b = d(k), n = '没有取到';
    if (b !== null && b !== undefined) { n = (Object.prototype.toString.call(b) === '[object Array]') ? (b.length + ' 条') : (Object.keys(b).length + ' 个字段'); }
    return '<details class="more"><summary>' + esc(k) + ' · ' + n + '</summary><pre class="rawpre">' +
      esc(JSON.stringify(b, null, 1).slice(0, 3000)) + '</pre></details>';
  }).join('');
  return card('接口原文', '#8A94A6', '<div class="kn">这里只给自己核对接口用。报表页面上不出现这种原文。</div>' + body);
};
DASH.pnode['dev-raw'] = '接口原文';
