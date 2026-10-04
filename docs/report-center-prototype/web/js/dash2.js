/* 仪表盘 v2 —— 按用户要求重排：先看钱和经营状态；异常单只报个数、沉到下面；
   多了「经营状态」和「建议」两块。取数完全复用 core.js，一个数字都不新造。 */

function dashDays() {
  var w = DASH.state.win;
  var from = parseISO(w.from), to = parseISO(w.to), today = parseISO(todayISO());
  var end = to > today ? today : to;
  return Math.max(1, Math.round((end - from) / 86400000) + 1);
}
function dashOwed(dr) {
  var owed = 0, n = 0;
  ((dr && dr.drivers) || []).forEach(function (r) { var v = num(r.freight_owed); if (v) { owed += v; n++; } });
  return { owed: owed, n: n };
}
function dashOldest(b) {
  var m = 0;
  ((b && b.rows) || []).forEach(function (r) { var v = num(r.oldest_days); if (v !== null && v > m) m = v; });
  return m;
}

/* 经营状态：每条 = 灯 + 名 + 值 + 一句白话；阈值都写在这里，改口径只改这一处 */
function dashHealth(t, p, b, dr, cs) {
  var out = [], days = dashDays();
  var rate = t ? pctOf(t.collected, t.total_amount) : null;
  var profit = p ? num(p.operating_profit) : null;
  var gm = p ? pctOf(p.gross_profit, p.revenue_covered) : null;
  var owed = dashOwed(dr).owed, owedN = dashOwed(dr).n;
  var tt = (b && b.totals) ? b.totals : null;
  var bk = tt ? (tt.buckets || {}) : {};
  var bal = tt ? num(tt.balance) : null;
  var perDay = (t && num(t.total_amount)) ? num(t.total_amount) / days : null;
  var coverDays = (bal !== null && perDay) ? Math.round(bal / perDay) : null;

  if (rate !== null) {
    out.push({ lv: rate >= 85 ? "good" : (rate >= 60 ? "warn" : "bad"), k: "钱收回来多少", v: rate + "%",
      d: "这一段应收 " + money(t.total_amount) + "，真收回来 " + money(t.collected) + "，其余 " + money(t.arrears_total) + " 挂在账上。挂账不等于坏账，但这一段基本没收现钱。" });
  }
  if (profit !== null) {
    out.push({ lv: profit > 0 ? "good" : "bad", k: "这一段赚没赚钱", v: money(profit),
      d: "毛利 " + money(p.gross_profit) + " 减掉司机运费 " + money(p.delivery_cost) + "、期间费用 " + money(p.operating_expense_total) + "、车辆折旧 " + money(p.depreciation_total) + " = " + money(profit) + "。" });
  }
  if (bal !== null && num(tt.balance)) {
    var old60 = (num(bk["61_90"]) || 0) + (num(bk.over_90) || 0);
    var oldPct = pctOf(old60, bal);
    var lv3 = (coverDays !== null && coverDays > 75) || (oldPct !== null && oldPct > 35) ? "bad" : ((coverDays !== null && coverDays > 45) ? "warn" : "good");
    out.push({ lv: lv3, k: "还欠着多少钱", v: money(bal),
      d: ints(tt.debtor_count) + " 人 · " + ints(tt.order_count) + " 张单" + (coverDays !== null ? ("；相当于这一段 " + coverDays + " 天的营业额") : "") + "；超过 60 天的 " + money(old60) + (oldPct === null ? "" : ("（占 " + oldPct + "%）")) + "，最老一笔 " + ints(dashOldest(b)) + " 天。" });
  }
  if (gm !== null) {
    var cov = pctOf(p.covered_lines, p.total_lines);
    out.push({ lv: gm >= 30 ? "good" : (gm >= 20 ? "warn" : "bad"), k: "毛利厚不厚", v: gm + "%",
      d: "毛利 ÷ 有成本的收入 = " + money(p.gross_profit) + " ÷ " + money(p.revenue_covered) + "；只有 " + (cov === null ? "—" : cov + "%") + " 的行算得出成本，另外 " + money(p.revenue_uncovered) + " 的收入没记进货价、不进毛利。" });
  }
  if (cs) {
    out.push({ lv: num(cs.net) >= 0 ? "good" : "warn", k: "现金进来还是出去", v: money(cs.net),
      d: "进来 " + money(cs.income) + " / 出去 " + money(cs.expense) + "，共 " + ints(cs.count) + " 笔。采购和运费是先垫出去的，挂账的钱没回来就会看到净流出，这本身正常。" });
  }
  if (owedN) {
    var inc = t ? num(t.collected) : null;
    out.push({ lv: (inc !== null && owed > inc) ? "warn" : "good", k: "该付司机的钱", v: money(owed),
      d: owedN + " 个司机还没结运费；这一段收回来 " + (inc === null ? "—" : money(inc)) + (inc !== null && owed > inc ? " —— 待结的比收回来的还多。" : "。") });
  }
  return out;
}
function dashVerdict(rows, t, p) {
  var bad = 0, warn = 0;
  rows.forEach(function (r) { if (r.lv === "bad") bad++; else if (r.lv === "warn") warn++; });
  var rate = t ? pctOf(t.collected, t.total_amount) : null;
  var profit = p ? num(p.operating_profit) : null;
  var s;
  if (profit !== null && profit < 0 && rate !== null && rate < 60) s = "这一段：货在卖，钱基本没收回来，账面还是亏的 —— 最该先看「催收」和「费用」这两块。";
  else if (profit !== null && profit < 0) s = "这一段：账面在亏，钱回来的比例还算正常，重点看成本费用那一块。";
  else if (rate !== null && rate < 60) s = "这一段：账面是赚的，但钱大部分还挂在账上，重点盯回款。";
  else s = "这一段：赚钱和收钱都还正常，没有需要立刻处理的事。";
  return s + "（" + rows.length + " 项里 " + bad + " 项要处理、" + warn + " 项留意）";
}

/* 建议：只把数据里最该先看的地方指出来，每条都写依据和去处 */
function dashAdvice(t, p, b, dr) {
  var out = [], days = dashDays();
  var rate = t ? pctOf(t.collected, t.total_amount) : null;
  var owed = dashOwed(dr).owed;
  var tt = (b && b.totals) ? b.totals : null;
  var bk = tt ? (tt.buckets || {}) : {};
  var old60 = (num(bk["61_90"]) || 0) + (num(bk.over_90) || 0);
  if (tt && num(tt.balance) && (old60 > 0 || (rate !== null && rate < 60))) {
    out.push({ t: "先把超过 60 天的 " + money(old60) + " 催一遍",
      d: "欠款一共 " + money(tt.balance) + "（" + ints(tt.debtor_count) + " 人 · " + ints(tt.order_count) + " 张单）。越放越难收，按名单从欠得最多、最久的往下打最省事。",
      b: "依据：customer-balances 的账龄四桶 + 欠款人名单", go: "arrears", goName: "客户欠款" });
  }
  if (p && num(p.operating_profit) < 0) {
    var expR = t ? pctOf(p.operating_expense_total, t.total_amount) : null;
    out.push({ t: "看期间费用这一块",
      d: "这一段亏 " + money(Math.abs(num(p.operating_profit))) + "：期间费用 " + money(p.operating_expense_total) +
        (expR === null ? "" : ("（占营业额 " + expR + "%，摊到每天约 " + money(num(p.operating_expense_total) / days) + "）")) +
        "、司机运费 " + money(p.delivery_cost) + "、商品成本 " + money(p.cost_total) + "。费用是可砍的，运费和成本要谈。",
      b: "依据：profit 的 operating_expense_total / delivery_cost / operating_profit", go: "finance", goName: "资金收支" });
  }
  if (p && pctOf(p.covered_lines, p.total_lines) !== null && pctOf(p.covered_lines, p.total_lines) < 95) {
    out.push({ t: "把没记进货价的商品补上",
      d: money(p.revenue_uncovered) + " 的收入算不出成本（" + ints(num(p.total_lines) - num(p.covered_lines)) + " 行），这部分既不知道赚不赚，也会让毛利看着偏高。",
      b: "依据：cost-coverage 的 uncovered / 缺进货价的商品清单", go: "coverage", goName: "成本覆盖" });
  }
  if (p && num(p.depreciation_total) === 0) {
    out.push({ t: "车辆折旧现在算成 0",
      d: "车辆台账里购买价 / 使用年限没填全的，折旧就按 0 算 —— 成本被少算、利润偏好看。补上台账再回来看利润。",
      b: "依据：vehicle-cost 的 depreciation_total = 0、逐车 depreciation_covered", go: "vehicle", goName: "车辆成本" });
  }
  if (owed > 0 && t && num(t.collected) !== null && owed > num(t.collected)) {
    out.push({ t: "该付司机的 " + money(owed) + " 先留出来",
      d: "这一段收回来 " + money(t.collected) + "，还没结给司机的运费 " + money(owed) + "。回款慢的时候这笔要先留着，不然周转会紧。",
      b: "依据：driver-performance 的 freight_owed 逐司机相加", go: "drivers", goName: "司机绩效" });
  }
  var allOrd = t ? (num(t.total_orders) || 0) + (num(t.cancelled_orders) || 0) : 0;
  var cancR = t ? pctOf(t.cancelled_orders, allOrd) : null;
  if (cancR !== null && cancR >= 15) {
    out.push({ t: "撤销单占了 " + cancR + "%，查一下原因",
      d: "这一段送达 " + ints(t.total_orders) + " 单、撤销 " + ints(t.cancelled_orders) + " 单（撤销的不进营业额）。比例这么高通常是缺货、派不出去或客户临时改单 —— 订单管理里能查到每一单。",
      b: "依据：turnover 的 cancelled_orders / total_orders", go: "audit", goName: "异常与审计" });
  }
  return out.slice(0, 4);
}

/* ---------------- 仪表盘 ---------------- */
function pageDash2() {
  var t = d("turnover"), p = d("profit"), b = d("balances"), tx = d("tax");
  var dr = d("drivers"), ex = d("exceptions"), cs = d("cashSummary");
  var exRows = ex || [];
  var owedInfo = dashOwed(dr);
  var h = failCard("turnover") + failCard("profit") + failCard("balances");

  /* ① 这一段：营业额 / 毛利 */
  if (t) {
    var gp = p ? p.gross_profit : null;
    var gpPct = p ? pctOf(p.gross_profit, p.revenue_covered) : null;
    h += "<div class=\"kpis\">" +
      kpi("这一段营业额", money(t.total_amount), ints(t.total_orders) + " 单 · 单均价 " + money(t.avg_order) + " · 撤销 " + ints(t.cancelled_orders) + " 单", "#1E6FFF") +
      kpi("这一段毛利", money(gp), p ? ("毛利率 " + (gpPct === null ? "—" : gpPct + "%") + "（毛利 ÷ 参与毛利的收入 " + money(p.revenue_covered) + "）") : "没取到利润接口", "#00B3A4") +
      "</div>";
  }

  /* ② 经营状态（新增：先看这里，知道这一段到底怎么样） */
  var rows = dashHealth(t, p, b, dr, cs);
  if (rows.length) {
    h += card("经营状态（这一段怎么样）", "#8A4FFF",
      "<div class=\"verdict\">" + esc(dashVerdict(rows, t, p)) + "</div>" +
      rows.map(function (r) {
        return "<div class=\"hl " + r.lv + "\"><div class=\"hlh\"><i></i><b>" + esc(r.k) + "</b><em>" + esc(r.v) + "</em></div>" +
          "<div class=\"hld\">" + esc(r.d) + "</div></div>";
      }).join("") +
      "<div class=\"kn\">灯：<b>绿</b> = 正常、<b>黄</b> = 留意、<b>红</b> = 这一段要处理。这几条是页面按接口给的数算的（收款率 60/85%、毛利率 20/30%、账龄 60 天、欠款相当于 45/75 天营业额），阈值写在页面源码的 dashHealth 里，觉得口径不对可以改。</div>");
  }

  /* ③ 钱：还没收回来的钱（时点账） */
  if (b && b.totals) {
    var tt = b.totals, bk = tt.buckets || {};
    var order = ["0_30", "31_60", "61_90", "over_90"];
    var names = { "0_30": "0-30 天", "31_60": "31-60 天", "61_90": "61-90 天", "over_90": "90 天以上" };
    var colors = { "0_30": "#00B578", "31_60": "#1E6FFF", "61_90": "#FF9F0A", "over_90": "#E53935" };
    var tot = num(tt.balance) || 0;
    var segs = order.map(function (k) {
      var v = num(bk[k]) || 0;
      var p2 = tot > 0 ? (v / tot * 100) : 0;
      return "<i style=\"width:" + p2 + "%;background:" + colors[k] + "\" title=\"" + names[k] + " " + money(v) + "\"></i>";
    }).join("");
    h += card("还没收回来的钱（时点账 · 到 " + esc(b.as_of) + " 为止）", "#FF6B2C",
      "<div class=\"big\">" + money(tt.balance) + "</div>" +
      "<div class=\"sub\">" + ints(tt.debtor_count) + " 人 · " + ints(tt.order_count) + " 张单 —— 这是<b>累计</b>还欠着的钱（时点），不是这一段新欠的。</div>" +
      "<div class=\"stack\">" + segs + "</div>" +
      order.map(function (k) { return kv("<i class=\"dot\" style=\"background:" + colors[k] + "\"></i>" + names[k], money(bk[k])); }).join("") +
      kv("＝ 该收的钱", money(tt.balance), "tot") +
      kv("预收（客户先给的钱，单列）", money(tt.prepaid)) +
      kv("没挂到名册单位上的", ints(tt.no_unit_count) + " 人 · " + money(tt.no_unit_balance)) +
      kv("超信用额度的", ints(tt.over_limit_count) + " 家", num(tt.over_limit_count) ? "red" : "") +
      "<div class=\"kn\">四桶之和 = 该收的钱（接口逐桶给的数，页面不加总）。这一格是<b>到今天为止</b>的账，跟「这一段」的营业额不是一回事。</div>");
  }

  /* ④ 钱 · 这一段 */
  if (t) {
    var col = num(t.collected) || 0, arr = num(t.arrears_total) || 0;
    var back = col + arr;
    var r2 = pctOf(t.collected, t.total_amount);
    h += card("钱 · 这一段", "#00B578",
      kv("这一段营业额（应收）", money(t.total_amount)) +
      kv("这一段收回来", money(t.collected), "green") +
      kv("这一段新增挂账", money(t.arrears_total), "orange") +
      kv("收款率（已收 ÷ 应收）", r2 === null ? "—" : r2 + "%", r2 !== null && r2 < 60 ? "red" : "green") +
      "<div class=\"kn\">接口的两个数相加 = <b>" + money(back) + "</b>，与营业额 " + money(t.total_amount) +
      (Math.abs(back - (num(t.total_amount) || 0)) < 0.005 ? " 对得上" : " <b class=\"red\">对不上</b>") + "（后端口径：已收 + 挂账 = 营业额，未收款不让营业额变小）。</div>" +
      (cs ? "<div class=\"kn\">现金流水（另一个口径，含非订单的收付）：进 " + money(cs.income) + " / 出 " + money(cs.expense) + " / 净 " + money(cs.net) + "，共 " + ints(cs.count) + " 笔。</div>" : ""));
  }

  /* ⑤ 赚了多少 */
  if (p) {
    h += card("赚了多少 · 这一段", "#00B3A4",
      kv("参与毛利的收入（有成本的那部分）", money(p.revenue_covered)) +
      kv("− 商品成本", "− " + money(p.cost_total), "orange") +
      kv("＝ 商品毛利", money(p.gross_profit), "green tot") +
      kv("− 司机运费（按单应付）", "− " + money(p.delivery_cost), "orange") +
      kv("− 期间费用", "− " + money(p.operating_expense_total), "orange") +
      kv("− 车辆折旧", "− " + money(p.depreciation_total), "orange") +
      kv("＝ 营业利润", money(p.operating_profit), "tot " + (num(p.operating_profit) < 0 ? "red" : "green")) +
      "<div class=\"kn\">不进毛利、但营业额里仍然有的那一部分：<b>" + money(p.revenue_uncovered) + "</b>（" + ints(num(p.total_lines) - num(p.covered_lines)) + " 行没有进货价）。成本覆盖率 " + ints(p.covered_lines) + " / " + ints(p.total_lines) + " 行。</div>" +
      (p.tax_total ? "<div class=\"kn\">税金及附加（开销里分类名带「税」的）：" + money(p.tax_total) + "</div>" : ""));
  }

  /* ⑥ 建议 */
  var adv = dashAdvice(t, p, b, dr);
  if (adv.length) {
    h += card("建议（按这一段的数据说的）", "#FF9F0A",
      adv.map(function (a, i) {
        return "<div class=\"adv\"><div class=\"advh\"><span class=\"n\">" + (i + 1) + "</span>" + esc(a.t) + "</div>" +
          "<div class=\"advd\">" + esc(a.d) + "</div>" +
          "<div class=\"advb\">" + esc(a.b) + " · <a href=\"#\" onclick=\"go(&apos;" + a.go + "&apos;);return false;\">去看" + esc(a.goName) + " &#8250;</a></div></div>";
      }).join("") +
      "<div class=\"kn\">建议只是把数据里最该先看的地方指出来，怎么处理还是你定。以后要更聪明（比如按客户、按线路分开算），可以再加。</div>");
  }

  /* ⑦ 走势 */
  if (t && t.series && t.series.length) {
    h += card("走势（接口 series 原文）", "#1E6FFF", chart(t.series) +
      "<div class=\"kn\">窗口两端同一天时接口按<b>小时</b>给桶（只给有单的那些小时，不是硬凑 24 个），跨天按<b>天</b>给。各柱之和 = " + money(sumBy(t.series, function (r) { return r.amount; })) +
      "（营业额 " + money(t.total_amount) + "）；运费之和 = " + money(sumBy(t.series, function (r) { return r.freight; })) + "。</div>");
  }

  /* ⑧ 税 · 这一段 */
  if (tx) {
    h += card("税 · 这一段（按开票日期）", "#C08A4E",
      kv("销项税（开出去的票）", money(tx.output ? tx.output.tax_amount : null)) +
      kv("进项税（收到的票）", money(tx.input ? tx.input.tax_amount : null), "green") +
      kv("＝ 本期应交增值税", money(tx.vat_payable), "tot orange") +
      kv("发票张数", ints(tx.invoices ? tx.invoices.length : 0) + " 张 · 作废 " + ints(tx.voided_count) + " 张") +
      "<div class=\"kn\">增值税是价外税，<b>不进营业利润</b>；" + (tx.output && num(tx.output.untaxed_amount) ?
        "有 " + money(tx.output.untaxed_amount) + " 的销项票没填税率，单列在 untaxed 里，没有替它猜。" : "这一段没有缺税率的票。") + "</div>");
  }

  /* ⑨ 要盯的事（缩小：异常单只报个数，明细去订单管理） */
  var over = (b && b.totals) ? num(b.totals.over_limit_count) : null;
  var moneyRisk = exRows.filter(function (r) { return String(r.exception_reason).indexOf("钱货") >= 0; }).length;
  var slowSorted = exRows.slice().sort(function (a, c) { return (daysSince(c.order_date) || 0) - (daysSince(a.order_date) || 0); });
  var slow = null;
  for (var si = 0; si < slowSorted.length; si++) {
    var rr = String(slowSorted[si].exception_reason || "") + String(slowSorted[si].status || "");
    if (rr.indexOf("撤销") < 0 && rr.indexOf("CANCEL") < 0) { slow = slowSorted[si]; break; }
  }
  h += card("要盯的事", "#E53935",
    (owedInfo.owed > 0 ? "<div class=\"todo\" onclick=\"go(&apos;drivers&apos;)\"><i class=\"dot\" style=\"background:#00A2C7\"></i>该付司机的钱（还没结的运费）<b>" + money(owedInfo.owed) + " · " + owedInfo.n + " 人</b><em>&#8250;</em></div>" : "") +
    (over ? "<div class=\"todo\" onclick=\"go(&apos;arrears&apos;)\"><i class=\"dot\" style=\"background:#FF9F0A\"></i>超信用额度的客户<b>" + over + " 家</b><em>&#8250;</em></div>" : "") +
    (exRows.length
      ? "<div class=\"todo\" onclick=\"go(&apos;audit&apos;)\"><i class=\"dot\" style=\"background:#E53935\"></i>异常单（这一段按下单日）<b>" + exRows.length + " 单</b><em>&#8250;</em></div>"
      : "<div class=\"todo\"><i class=\"dot\" style=\"background:#00B578\"></i>这一段没有异常单<b>0 单</b></div>") +
    (moneyRisk ? "<div class=\"kn\">其中「钱货风险」" + moneyRisk + " 单 —— 这类是钱或货真出问题的，建议先去订单管理处理。</div>" : "") +
    (slow ? "<div class=\"kn\">拖得最久的一单：" + esc(slow.order_no) + "（" + esc(excCat(slow.exception_reason)) + "）已 " + ints(daysSince(slow.order_date)) + " 天。</div>" : "") +
    "<div class=\"kn\">异常单的每一单明细在<b>订单管理</b>里看，报表中心这里只报个数；要按窗口翻清单，点进「异常与审计」。</div>");

  /* ⑩ 详细报表入口 */
  function tile(e) {
    return "<div class=\"tile\" onclick=\"go(&apos;" + e[0] + "&apos;)\"><b>" + esc(e[1]) + "</b><span>" + esc(e[2]) + "</span></div>";
  }
  h += card("详细报表（点开看细节）", "#8A94A6",
    "<div class=\"tg\">常用（每天都可能点）</div><div class=\"tiles\">" +
    ENTRIES.filter(function (e) { return e[3] === "often"; }).map(tile).join("") + "</div>" +
    "<div class=\"tg\">偶尔才查（有具体问题时再点）</div><div class=\"tiles\">" +
    ENTRIES.filter(function (e) { return e[3] === "rarely"; }).map(tile).join("") + "</div>");

  h += notesBlock(["turnover", "profit", "balances", "tax"], "口径（后端随接口一起给的说明）");
  h += rawBlock(["turnover", "profit", "balances", "tax", "drivers", "exceptions", "cashSummary"]);
  return h;
}

DASH.pages.dash = pageDash2;
