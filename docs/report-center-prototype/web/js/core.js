/* 报表中心测试网页 —— 核心：登录 / 窗口 / 取数 / 外壳 */
var API_BASE = 'http://127.0.0.1:8000/api/v1';
var TOKEN_KEY = 'dash_token_v1';

var DASH = window.DASH = {
  pages: {},
  state: {
    token: localStorage.getItem(TOKEN_KEY) || '',
    role: '', uid: '',
    win: null,
    page: 'dash',
    data: {},
    busy: false,
    notice: '',
    error: '',
    raw: {}
  }
};

var ENTRIES = [
  ['turnover', '营业纵览', '这一段卖了多少、收回来多少、还挂着多少', 'often'],
  ['arrears', '客户欠款', '谁欠我钱、欠了多久、有没有超额度', 'often'],
  ['audit', '异常与审计', '哪几单卡住了、谁改了钱和数据', 'often'],
  ['finance', '资金收支', '这一段进来多少、出去多少', 'often'],
  ['drivers', '司机绩效', '每个司机跑了多少、还欠他多少运费', 'rarely'],
  ['profit', '经营利润', '营业额减掉各项成本后还剩多少', 'rarely'],
  ['products', '商品经营', '哪个商品赚钱、哪个货损多', 'rarely'],
  ['customers', '客户经营', '哪些客户在买、买得最多的几个人', 'rarely'],
  ['coverage', '成本覆盖', '有多少收入因为没有进货价算不出成本', 'rarely'],
  ['vehicle', '车辆成本', '每台车这一段花了多少钱', 'rarely'],
  ['tax', '税账', '开了多少票、收到多少票、该交多少', 'rarely']
];

var EXPORT_KIND = {
  turnover: 'turnover', products: 'products', drivers: 'drivers', customers: 'customers',
  finance: 'finance', audit: 'audit', profit: 'profit', vehicle: 'vehicle-cost',
  coverage: 'cost-coverage', tax: 'tax-summary', arrears: 'customer-balances'
};

/* ---------- 小工具 ---------- */
function num(v) {
  if (v === null || v === undefined || v === '') return null;
  var n = Number(v);
  return isNaN(n) ? null : n;
}
function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v).split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;').split('"').join('&quot;');
}
function money(v) {
  var n = num(v);
  if (n === null) return '—';
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function money0(v) {
  var n = num(v);
  if (n === null) return '—';
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}
function ints(v) {
  var n = num(v);
  if (n === null) return '—';
  return n.toLocaleString('zh-CN');
}
function pctOf(a, b) {
  var x = num(a), y = num(b);
  if (x === null || !y) return null;
  return Math.round(x / y * 1000) / 10;
}
function pad2(n) { return (n < 10 ? '0' : '') + n; }
function iso(d) { return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); }
function parseISO(s) { var p = String(s).split('-'); return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2])); }
function todayISO() { return iso(new Date()); }
function mins(sec) {
  var n = num(sec);
  if (n === null) return null;
  return Math.round(n / 60);
}

/* ---------- 窗口 ---------- */
var WINS = [
  ['today', '今天'], ['week', '本周'], ['month', '本月'], ['last', '上月'],
  ['quarter', '本季'], ['year', '本年'], ['all', '全部']
];
/* 时间药丸的规范档位：今天 / 本周 / 本月 / 本季 / 本年 / 全部（上月与自定义放在「换一个」里） */
var MAIN_WINS = ['today', 'week', 'month', 'quarter', 'year', 'all'];
function windowFor(key, ref) {
  var t = ref ? parseISO(ref) : new Date();
  if (key === 'today') return { key: 'today', label: '今天', from: iso(t), to: iso(t) };
  if (key === 'week') {
    var wd = (t.getDay() + 6) % 7;
    var s = new Date(t.getFullYear(), t.getMonth(), t.getDate() - wd);
    var e = new Date(s.getFullYear(), s.getMonth(), s.getDate() + 6);
    return { key: 'week', label: '本周', from: iso(s), to: iso(e) };
  }
  if (key === 'month') {
    var a = new Date(t.getFullYear(), t.getMonth(), 1);
    var b = new Date(t.getFullYear(), t.getMonth() + 1, 0);
    return { key: 'month', label: '本月', from: iso(a), to: iso(b) };
  }
  if (key === 'last') {
    var a2 = new Date(t.getFullYear(), t.getMonth() - 1, 1);
    var b2 = new Date(t.getFullYear(), t.getMonth(), 0);
    return { key: 'last', label: '上月', from: iso(a2), to: iso(b2) };
  }
  if (key === 'quarter') {
    var q = Math.floor(t.getMonth() / 3);
    var a3 = new Date(t.getFullYear(), q * 3, 1);
    var b3 = new Date(t.getFullYear(), q * 3 + 3, 0);
    return { key: 'quarter', label: '本季（Q' + (q + 1) + '）', from: iso(a3), to: iso(b3) };
  }
  if (key === 'year') {
    return { key: 'year', label: '本年', from: t.getFullYear() + '-01-01', to: t.getFullYear() + '-12-31' };
  }
  if (key === 'all') {
    return { key: 'all', label: '全部', from: '2020-01-01', to: todayISO() };
  }
  return { key: 'custom', label: '自定义', from: DASH.state.win.from, to: DASH.state.win.to };
}

/* 要拉的全部接口（一个窗口一次全拉） */
function endpointsFor(w) {
  var q = 'mode=day&date=' + w.to + '&date_from=' + w.from + '&date_to=' + w.to;
  var d = 'date_from=' + w.from + '&date_to=' + w.to;
  return [
    ['turnover', '营业纵览', '/reports/turnover?' + q],
    ['products', '商品经营', '/reports/products?' + q],
    ['profit', '经营利润', '/reports/profit?' + q],
    ['vehicle', '车辆成本', '/reports/vehicle-cost?' + q],
    ['coverage', '成本覆盖', '/reports/cost-coverage?' + q],
    ['tax', '税账', '/reports/tax-summary?' + q],
    ['balances', '客户欠款', '/reports/customer-balances?' + q + '&include_orders=true'],
    ['arrearsUnits', '挂账单位', '/arrears-units'],
    ['drivers', '司机绩效', '/stats/driver-performance?' + d],
    ['shippers', '货主绩效', '/stats/shipper-performance?' + d],
    ['exceptions', '异常单', '/stats/exception-orders?' + d],
    ['cashSummary', '资金汇总', '/cash-flows/summary?' + d],
    ['cashBreakdown', '资金构成', '/cash-flows/breakdown?' + d],
    ['cashFlows', '资金流水', '/cash-flows?' + d + '&limit=100'],
    ['expenses', '开销明细', '/expenses?' + d],
    ['invoices', '发票台账', '/invoices?' + d + '&limit=200'],
    ['logs', '操作日志', '/operation-logs?limit=60'],
    ['vehicles', '车辆台账', '/vehicles'],
    ['suppliers', '供应商与应付', '/suppliers'],
    ['invSummary', '库存结存', '/inventory/summary'],
    ['stock', '商品档案与进货价', '/products?limit=500'],
    ['payables', '应付单', '/supplier-payables?limit=200']
  ];
}

/* ---------- 取数 ---------- */
async function apiGet(path) {
  var t0 = Date.now();
  var res = await fetch(API_BASE + path, { headers: { Authorization: 'Bearer ' + DASH.state.token } });
  var txt = await res.text();
  var body = null;
  try { body = JSON.parse(txt); } catch (e) { body = txt.slice(0, 300); }
  return { ok: res.ok, status: res.status, body: body, ms: Date.now() - t0 };
}

async function loadAll(w, opts) {
  DASH.state.busy = true;
  DASH.state.notice = (opts && opts.notice) || '';
  render();
  var list = endpointsFor(w);
  var out = await Promise.all(list.map(function (e) {
    return apiGet(e[2]).then(function (r) { return [e[0], e[1], e[2], r]; })
      .catch(function (err) { return [e[0], e[1], e[2], { ok: false, status: 0, body: String(err), ms: 0 }]; });
  }));
  var data = {}, statuses = [], ok0 = 0, bad = 0;
  out.forEach(function (r) {
    data[r[0]] = r[3];
    statuses.push({ key: r[0], name: r[1], path: r[2], ok: r[3].ok, status: r[3].status, ms: r[3].ms });
    if (r[3].ok) ok0++; else bad++;
  });
  DASH.state.data = data;
  DASH.state.statuses = statuses;
  DASH.state.busy = false;
  var bad401 = statuses.filter(function (s) { return s.status === 401; }).length;
  if (bad401) { logout('登录已过期，请重新登录'); return; }
  render();
}

function d(name) {
  var r = DASH.state.data[name];
  return (r && r.ok) ? r.body : null;
}
function notesOf(names) {
  var out = [];
  names.forEach(function (n) {
    var b = d(n);
    if (b && b.notes && b.notes.length) b.notes.forEach(function (x) { out.push(x); });
  });
  return out;
}

/* ---------- 登录 ---------- */
async function doLogin() {
  var phone = document.getElementById('f_phone').value.trim();
  var pwd = document.getElementById('f_pwd').value;
  var box = document.getElementById('login_msg');
  box.textContent = '正在登录…';
  try {
    var res = await fetch(API_BASE + '/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone: phone, password: pwd })
    });
    var b = await res.json();
    if (!res.ok) { box.textContent = '登录失败 ' + res.status + '：' + JSON.stringify(b); return; }
    DASH.state.token = b.access_token;
    DASH.state.role = b.role;
    DASH.state.uid = b.user_id;
    localStorage.setItem(TOKEN_KEY, b.access_token);
    box.textContent = '';
    await boot();
  } catch (e) {
    box.textContent = '请求失败：' + e + '（后端在 127.0.0.1:8000 吗？）';
  }
}

function logout(msg) {
  localStorage.removeItem(TOKEN_KEY);
  DASH.state.token = '';
  DASH.state.role = '';
  DASH.state.data = {};
  DASH.state.notice = msg || '';
  render();
}

/* ---------- 启动 ---------- */
async function boot() {
  DASH.state.win = DASH.state.win || windowFor('month');
  await loadAll(DASH.state.win);
  /* 本月没有已送达的单时，自动退到上月 —— 真库的数据不在当月，空页面容易被当成坏了 */
  var t = d('turnover');
  if (t && t.total_orders === 0) {
    var cur = DASH.state.win;
    var chain = ['last', 'quarter', 'year'];
    for (var i = 0; i < chain.length; i++) {
      var c = windowFor(chain[i]);
      if (c.from === cur.from && c.to === cur.to) continue;
      var probe = await apiGet('/reports/turnover?mode=day&date=' + c.to + '&date_from=' + c.from + '&date_to=' + c.to);
      if (probe.ok && probe.body.total_orders > 0) {
        DASH.state.win = c;
        await loadAll(c, { notice: '「' + cur.label + '」这个区间（' + cur.from + ' ~ ' + cur.to + '）里没有已送达的单，页面自动切到最近有数据的「' + c.label + '（' + c.from + ' ~ ' + c.to + '）」。要看别的区间，点上面的时间药丸，或在「换一个」里自己填起止日。' });
        return;
      }
    }
  }
}

/* ---------- 交互 ---------- */
function setWin(key) {
  if (DASH.state.busy) return;
  if (key === 'custom') {
    var f = document.getElementById('f_from').value;
    var t = document.getElementById('f_to').value;
    if (!f || !t) { alert('自定义区间要同时给开始和结束（后端也只收成对的两个日期）'); return; }
    if (f > t) { alert('开始日期不能晚于结束日期'); return; }
    DASH.state.win = { key: 'custom', label: '自定义', from: f, to: t };
  } else {
    DASH.state.win = windowFor(key);
  }
  loadAll(DASH.state.win);
}
function setRange(from, to, label) {
  if (DASH.state.busy) return;
  DASH.state.win = { key: 'custom', label: label || '自定义', from: from, to: to };
  loadAll(DASH.state.win);
}
function go(page) {
  DASH.state.page = page;
  render();
  window.scrollTo(0, 0);
}
function toggleRaw(key) {
  DASH.state.raw[key] = !DASH.state.raw[key];
  render();
}
async function doExport() {
  var kind = EXPORT_KIND[DASH.state.page];
  if (!kind) { alert('这一页没有对应的导出'); return; }
  var w = DASH.state.win;
  var url = API_BASE + '/reports/export?kind=' + kind + '&mode=day&date=' + w.to + '&date_from=' + w.from + '&date_to=' + w.to;
  var res = await fetch(url, { headers: { Authorization: 'Bearer ' + DASH.state.token } });
  if (!res.ok) { alert('导出失败 ' + res.status); return; }
  var blob = await res.blob();
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  var cd = res.headers.get('Content-Disposition') || '';
  var m = cd.split('filename=')[1];
  a.download = m ? m.split(';')[0].split('"').join('') : (kind + '.xlsx');
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ---------- 渲染外壳 ---------- */
function navHTML() {
  var w = DASH.state.win || (DASH.state.win = windowFor('month'));
  var often = ENTRIES.filter(function (e) { return e[3] === 'often'; });
  var rarely = ENTRIES.filter(function (e) { return e[3] === 'rarely'; });
  function item(e) {
    return '<div class="nv' + (DASH.state.page === e[0] ? ' on' : '') + '" onclick="go(&apos;' + e[0] + '&apos;)">' +
      '<b>' + esc(e[1]) + '</b><span>' + esc(e[2]) + '</span></div>';
  }
  return '<div class="brand"><b>报表中心 · 测试网页</b><span>连的是真后端 ' + esc(API_BASE) + '</span></div>' +
    '<div class="nv' + (DASH.state.page === 'dash' ? ' on' : '') + '" onclick="go(&apos;dash&apos;)"><b>仪表盘</b><span>打开先看这一页</span></div>' +
    '<h4>常用报表（2 层 · 第一档）</h4>' + often.map(item).join('') +
    '<h4>偶尔才查（2 层 · 第二档）</h4>' + rarely.map(item).join('') +
    statusHTML() +
    '<div class="who">登录身份：' + esc(DASH.state.role || '—') + ' #' + esc(DASH.state.uid || '—') +
    '<a href="#" onclick="logout();return false;">退出登录</a></div>' +
    '<div class="who">窗口：' + esc(w.from) + ' ~ ' + esc(w.to) + '</div>';
}

function statusHTML() {
  var st = DASH.state.statuses || [];
  if (!st.length) return '';
  var bad = st.filter(function (s) { return !s.ok; });
  return '<h4>接口状态（' + (st.length - bad.length) + '/' + st.length + ' 通）</h4>' +
    '<div class="st">' + st.map(function (s) {
      return '<div class="str' + (s.ok ? '' : ' bad') + '" title="' + esc(s.path) + '">' +
        '<span>' + esc(s.name) + '</span><em>' + (s.ok ? '200' : s.status) + ' · ' + s.ms + 'ms</em></div>';
    }).join('') + '</div>';
}

function topHTML() {
  var w = DASH.state.win || (DASH.state.win = windowFor('month'));
  var pills = WINS.map(function (x) {
    return '<button class="pill' + (w.key === x[0] ? ' on' : '') + '" onclick="setWin(&apos;' + x[0] + '&apos;)">' + x[1] + '</button>';
  }).join('');
  var quick = [
    ['2026-09-25', '2026-09-25', '9-25（单日最多）'],
    ['2026-09-01', '2026-09-30', '2026-09'],
    ['2026-08-01', '2026-08-31', '2026-08'],
    ['2026-07-01', '2026-07-31', '2026-07'],
    ['2026-06-01', '2026-06-30', '2026-06']
  ].map(function (r) {
    return '<button class="pill sm" onclick="setRange(&apos;' + r[0] + '&apos;,&apos;' + r[1] + '&apos;,&apos;' + r[2] + '&apos;)">' + r[2] + '</button>';
  }).join('');
  return '<div class="bar">' +
    '<div class="row1">' + pills +
    '<input id="f_from" type="date" value="' + esc(w.from) + '"><span class="tilde">~</span>' +
    '<input id="f_to" type="date" value="' + esc(w.to) + '">' +
    '<button class="pill" onclick="setWin(&apos;custom&apos;)">用这段</button>' +
    '<button class="pill go" onclick="loadAll(DASH.state.win)">刷新</button>' +
    (EXPORT_KIND[DASH.state.page] ? '<button class="pill" onclick="doExport()">导出 Excel</button>' : '') +
    '</div>' +
    '<div class="row2">真库里有数据的窗口：' + quick + '</div>' +
    '<div class="row2"><span class="dim">当前看的是</span> <b>' + esc(w.from) + ' ~ ' + esc(w.to) + '</b>' +
    (w.key === 'custom' ? '（自定义）' : '（' + esc(w.label) + '）') +
    '<span class="dim"> · 接口按 date_from/date_to 成对发，窗口决定一切</span></div>' +
    '</div>';
}

function render() {
  if (!DASH.state.token) {
    document.getElementById('root').innerHTML = loginHTML();
    return;
  }
  var page = DASH.pages[DASH.state.page] || DASH.pages.dash;
  var notice = DASH.state.notice ? '<div class="notice">' + esc(DASH.state.notice) + '<a href="#" onclick="DASH.state.notice=&apos;&apos;;render();return false;">×</a></div>' : '';
  document.getElementById('root').innerHTML =
    '<div class="layout"><aside class="nav">' + navHTML() + '</aside>' +
    '<main class="main">' + topHTML() + notice +
    '<div class="screen">' + (DASH.state.busy ? '<div class="loading">正在取数…</div>' : page()) + '</div>' +
    '<footer class="foot">这个网页是<b>测试用</b>的：它连的是 127.0.0.1:8000 的真后端，显示的每个数字都是接口返回的原文，页面自己不做加减。' +
    'App 里的报表中心没被改动一行。</footer></main></div>';
}

function loginHTML() {
  return '<div class="login"><div class="lbox">' +
    '<h1>报表中心 · 测试网页</h1>' +
    '<p>连的是本机后端 <b>' + esc(API_BASE) + '</b>。用派单员账号登录即可（前端只是把接口的原始数字摆出来）。</p>' +
    '<label>手机号 / 登录名<input id="f_phone" value="13800000001"></label>' +
    '<label>密码<input id="f_pwd" type="password" value="pass12345"></label>' +
    '<button class="primary" onclick="doLogin()">登录</button>' +
    '<div id="login_msg" class="msg">' + esc(DASH.state.notice || '') + '</div>' +
    '<div class="hint">三个内置账号：13800000001（派单员）/ 13800000002（货主）/ 13800000003（司机），密码都是 pass12345。' +
    '报表接口只对派单员开放，用另两个登录会看到 403 —— 那是有意为之。</div>' +
    '</div></div>';
}

/* 页面级公用小块 */
function card(title, color, body, cls) {
  return '<section class="card ' + (cls || '') + '">' +
    (title ? '<h3 style="--c:' + color + '">' + esc(title) + '</h3>' : '') + body + '</section>';
}
function kv(k, v, cls, note) {
  return '<div class="kv"><span class="k">' + k + '</span><span class="v ' + (cls || '') + '">' + v + '</span></div>' +
    (note ? '<div class="kn">' + note + '</div>' : '');
}
function kpi(label, value, sub, color) {
  return '<div class="kpicard"><div class="kl">' + esc(label) + '</div>' +
    '<div class="kvv" style="color:' + color + '">' + value + '</div>' +
    (sub ? '<div class="ks">' + sub + '</div>' : '') + '</div>';
}
function moneyCls(v) { return num(v) < 0 ? 'red' : ''; }
function notesBlock(names, title) {
  var ns = notesOf(names);
  if (!ns.length) return '';
  return card(title || '口径（后端随接口一起给的说明）', '#8A94A6',
    '<ul class="notes">' + ns.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>');
}
function rawBlock(keys) {
  var on = DASH.state.raw[DASH.state.page];
  var body = keys.map(function (k) {
    var r = DASH.state.data[k];
    if (!r) return '';
    return '<h5>' + esc(k) + ' → HTTP ' + r.status + '</h5><pre>' + esc(JSON.stringify(r.body, null, 2)).slice(0, 60000) + '</pre>';
  }).join('');
  return '<section class="card raw"><h3 style="--c:#8A94A6">原始 JSON（接口原文）' +
    '<button class="pill sm" onclick="toggleRaw(&apos;' + DASH.state.page + '&apos;)">' + (on ? '收起' : '展开') + '</button></h3>' +
    (on ? body : '<div class="dim">这一页的数字全部来自下面这些接口，展开可以逐字核对。</div>') + '</section>';
}
function bar(pct, color) {
  var p = pct === null ? 0 : Math.max(0, Math.min(100, pct));
  return '<div class="prog"><i style="width:' + p + '%;background:' + (color || '#1E6FFF') + '"></i></div>';
}
function chart(series) {
  if (!series || !series.length) return '<div class="dim">这一段没有数据</div>';
  var max = 0;
  series.forEach(function (s) {
    max = Math.max(max, num(s.amount) || 0, num(s.freight) || 0);
  });
  if (max <= 0) return '<div class="dim">这一段没有数据</div>';
  var bars = series.map(function (s) {
    var a = (num(s.amount) || 0) / max * 100;
    var f = (num(s.freight) || 0) / max * 100;
    return '<div class="col" title="' + esc(s.label) + '：营业额 ' + money(s.amount) + ' / 运费 ' + money(s.freight) + '">' +
      '<div class="cb"><i class="b1" style="height:' + a + '%"></i><i class="b2" style="height:' + f + '%"></i></div>' +
      '<span>' + esc(s.label) + '</span></div>';
  }).join('');
  return '<div class="chart">' + bars + '</div>' +
    '<div class="legend"><span><i class="sw b1"></i>营业额</span><span><i class="sw b2"></i>司机运费</span>' +
    '<span class="dim">同一把尺子（最高柱 = ' + money0(max) + '）</span></div>';
}
