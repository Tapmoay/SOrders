/* 手机样式的壳：把测试网页包成一部手机（顶部标题 + 时间药丸 + 单列卡片 + 子页返回）
   数据层完全复用 core.js；这里只换 render/head/login 这几件外壳。 */
function winOf(key) {
  for (var i = 0; i < WINS.length; i++) { if (WINS[i][0] === key) return WINS[i]; }
  return [key, key];
}
function pNameOf(key) {
  if (key === 'dash') return '报表中心';
  for (var i = 0; i < ENTRIES.length; i++) { if (ENTRIES[i][0] === key) return ENTRIES[i][1]; }
  return key;
}
function pPills() {
  var w = DASH.state.win;
  var p = MAIN_WINS.map(function (k) {
    var x = winOf(k);
    return '<button class="pill' + (w.key === k ? ' on' : '') + '" onclick="setWin(&apos;' + k + '&apos;)">' + x[1] + '</button>';
  }).join('');
  var quick = [
    ['last', '上月'],
    ['2026-09-25', '2026-09-25', '9-25'],
    ['2026-09-01', '2026-09-30', '2026-09'],
    ['2026-08-01', '2026-08-31', '2026-08'],
    ['2026-07-01', '2026-07-31', '2026-07'],
    ['2026-06-01', '2026-06-30', '2026-06']
  ].map(function (r) {
    if (r[0] === 'last') {
      return '<button class="pill sm' + (w.key === 'last' ? ' on' : '') + '" onclick="setWin(&apos;last&apos;)">' + r[1] + '</button>';
    }
    return '<button class="pill sm' + (w.from === r[0] && w.to === r[1] ? ' on' : '') +
      '" onclick="setRange(&apos;' + r[0] + '&apos;,&apos;' + r[1] + '&apos;,&apos;' + r[2] + '&apos;)">' + r[2] + '</button>';
  }).join('');
  return '<div class="pills">' + p + '</div>' +
    '<details class="wmore"><summary>当前窗口 ' + esc(w.from) + ' ~ ' + esc(w.to) + '（' + esc(w.label) + '）· 换一个</summary>' +
    '<div class="wrow"><input id="f_from" type="date" value="' + esc(w.from) + '"><span class="tilde">~</span>' +
    '<input id="f_to" type="date" value="' + esc(w.to) + '"></div>' +
    '<div class="wrow"><button class="pill" onclick="setWin(&apos;custom&apos;)">用这段</button>' +
    '<button class="pill go" onclick="loadAll(DASH.state.win)">刷新数据</button></div>' +
    '<div class="wlab">真库里有数据的窗口</div><div class="pills">' + quick + '</div></details>';
}
function headHTML() {
  var isDash = DASH.state.page === 'dash';
  var left = isDash ? '<span class="ib ghost"></span>'
    : '<button class="ib" onclick="go(&apos;dash&apos;)">&#8249; 返回</button>';
  var right = EXPORT_KIND[DASH.state.page]
    ? '<button class="ib" onclick="doExport()">导出</button>'
    : '<button class="ib" onclick="loadAll(DASH.state.win)">刷新</button>';
  var w = DASH.state.win;
  var winTxt = esc(w.from) + ' ~ ' + esc(w.to);
  return '<div class="pstick"><div class="pbar">' + left +
    '<div class="ptitle">' + esc(pNameOf(DASH.state.page)) +
    '<span class="psub">' + esc(w.label) + ' · ' + winTxt + '</span></div>' + right + '</div>' + pPills() + '</div>';
}
function chart(series) {
  if (!series || !series.length) return '<div class="dim">这一段没有数据</div>';
  var raw = series, per = 1, merged = false, rawLen = series.length;
  if (series.length > 62) {
    per = Math.ceil(series.length / 40);
    var acc = [];
    for (var i0 = 0; i0 < series.length; i0 += per) {
      var chunk = series.slice(i0, i0 + per), a0 = 0, f0 = 0;
      chunk.forEach(function (x) { a0 += num(x.amount) || 0; f0 += num(x.freight) || 0; });
      acc.push({ label: chunk[0].label, amount: a0, freight: f0, n: chunk.length });
    }
    series = acc; merged = true;
  }
  var max = 0;
  series.forEach(function (s) { max = Math.max(max, num(s.amount) || 0, num(s.freight) || 0); });
  if (max <= 0) return '<div class="dim">这一段没有数据</div>';
  var step = series.length > 12 ? Math.ceil(series.length / 6) : 1;
  var bars = series.map(function (s, i) {
    var a = (num(s.amount) || 0) / max * 100;
    var f = (num(s.freight) || 0) / max * 100;
    var show = (i % step === 0) || i === series.length - 1;
    return '<div class="col" title="' + (merged ? ('合并 ' + s.n + ' 天（从 ' + esc(s.label) + ' 起）：') : (esc(s.label) + '：')) +
      '营业额 ' + money(s.amount) + ' / 运费 ' + money(s.freight) + '">' +
      '<div class="cb"><i class="b1" style="height:' + a + '%"></i><i class="b2" style="height:' + f + '%"></i></div>' +
      '<span>' + (show ? esc(s.label) : '') + '</span></div>';
  }).join('');
  return '<div class="chart' + (series.length > 12 ? ' thin' : '') + '">' + bars + '</div>' +
    '<div class="legend"><span><i class="sw b1"></i>营业额</span><span><i class="sw b2"></i>司机运费</span>' +
    '<span class="dim">同一把尺子（最高柱 = ' + money0(max) + '）· 一共 ' + series.length + ' 根柱子</span></div>' +
    (series.length > 12 ? '<div class="axlab">横轴：' + esc(series[0].label) + ' &#8594; ' + esc(series[series.length - 1].label) +
      '（柱子上悬停/长按能看到每一根的准确数）</div>' : '') +
    (merged ? '<div class="axlab">接口给的是逐日 ' + rawLen + ' 天，手机上画不下这么多根，页面把每 ' + per + ' 天并成一根（只是画面上的合并，数字是相加的，各柱之和仍然等于总额；逐日原文在下面「原始 JSON」里）。</div>' : '');
}
function navHTML() { return ''; }
function topHTML() { return ''; }
function footHTML() {
  var st = DASH.state.statuses || [];
  var bad = st.filter(function (s) { return !s.ok; });
  return '<details class="ift"><summary>接口状态 ' + (st.length - bad.length) + '/' + st.length + ' 通 · 身份 ' +
    esc(DASH.state.role || '—') + ' #' + esc(DASH.state.uid || '—') + '</summary>' + statusHTML() +
    '<div class="who"><a href="#" onclick="logout();return false;">退出登录</a></div></details>' +
    '<div class="foot">这是<b>测试网页</b>（手机样式）：每个数字都来自 ' + esc(API_BASE) +
    ' 的真接口原文，页面自己不做加减。App 里的报表中心一行没动。</div>';
}
function loginHTML() {
  return '<div class="stage"><div class="phone">' + statusbarHTML() + '<div class="ph"><div class="login"><div class="lbox">' +
    '<h1>报表中心</h1><p>手机样式 · 连真后端 <b>' + esc(API_BASE) + '</b></p>' +
    '<label>手机号 / 登录名<input id="f_phone" value="13800000001"></label>' +
    '<label>密码<input id="f_pwd" type="password" value="pass12345"></label>' +
    '<button class="primary" onclick="doLogin()">登录</button>' +
    '<div id="login_msg" class="msg">' + esc(DASH.state.notice || '') + '</div>' +
    '<div class="hint">三个内置账号：13800000001（派单员）/ …002（货主）/ …003（司机），密码都是 pass12345。报表接口只对派单员开放，另两个会 403 —— 有意为之。</div>' +
    '</div></div></div></div></div>';
}
function go(page) {
  DASH.state.page = page;
  render();
  var ph = document.querySelector('.ph');
  if (ph) ph.scrollTop = 0;
  window.scrollTo(0, 0);
}
function statusbarHTML() {
  return '<div class="statusbar"><span>9:41</span><span class="sbmid">测试 · 连真后端</span><span>LTE &#183; 100%</span></div>';
}
function render() {
  if (!DASH.state.token) { document.getElementById('root').innerHTML = loginHTML(); return; }
  if (!DASH.state.win) DASH.state.win = windowFor('month');
  var page = DASH.pages[DASH.state.page] || DASH.pages.dash;
  var notice = DASH.state.notice ? '<div class="notice"><a href="#" onclick="DASH.state.notice=&apos;&apos;;render();return false;">&#215;</a>' + esc(DASH.state.notice) + '</div>' : '';
  document.getElementById('root').innerHTML =
    '<div class="stage"><div class="phone">' + statusbarHTML() + '<div class="ph">' +
    headHTML() + notice +
    '<div class="screen">' + (DASH.state.busy ? '<div class="loading">正在取数…</div>' : page()) + '</div>' +
    footHTML() + '</div></div></div>';
}
