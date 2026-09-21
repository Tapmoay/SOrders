-- 生产灌数后的**库内口径抽查**（配合 `_prod_api_smoke.py`：一个查库、一个查接口）。
-- 用法（在服务器上）：mysql -uroot sorders --table < /root/prod-data-check.sql
--
-- ⚠️ 基准必须用「**送达**的业务日」，不是「下单日」：跨夜送达的单，入账日/账单月
--    本来就该落在送达那天（第一版我拿下单日去比，报出 699 行"不一致"——那是查询错，不是数据错）。
--    业务日 = `date( coalesce(送达时刻, 下单日) + 8 小时 )`（库里存 UTC，业务时区 +8）。
-- ⛔ 别把这些 SQL 内联进 PowerShell 的 ssh 字符串：`<>`、`()` 会被 PS 解析掉（踩过两次）。

-- ① 账本入账日 vs **送达**业务日。
-- ⚠️ 必须排除**退货红冲**（`source='RETURN'`）：那几行记的是"退货这件事发生在哪天"，
--    整单退货是今天退的，红冲就该落在今天 —— 第一版没排除，报出 8 行"不一致"，是查询错不是数据错。
SELECT '① 账本 entry_date 与「送达业务日」不一致的行数（已排除退货红冲）' AS 检查项, COUNT(*) AS 值
FROM ledgers l JOIN orders o ON o.id = l.order_id
WHERE l.source <> 'RETURN'
  AND l.entry_date <> DATE(COALESCE(o.delivered_at, o.order_date) + INTERVAL 8 HOUR);

SELECT '② 司机账单 month 与「送达业务月」不一致的行数', COUNT(*)
FROM driver_bills b JOIN orders o ON o.id = b.order_id
WHERE b.month <> DATE_FORMAT(COALESCE(o.delivered_at, o.order_date) + INTERVAL 8 HOUR, '%Y-%m');

-- ③ 凌晨单（业务当地 00:00~08:00，UTC 已是前一天）：派生行不许被挪到前一天
SELECT '③ 凌晨单的账本行被挪到前一天的行数', COUNT(*)
FROM ledgers l JOIN orders o ON o.id = l.order_id
WHERE HOUR(COALESCE(o.delivered_at, o.order_date) + INTERVAL 8 HOUR) < 8
  AND l.entry_date <> DATE(COALESCE(o.delivered_at, o.order_date) + INTERVAL 8 HOUR);

-- ④ 金额：只对**已送达**的单比（其余状态本来就不入账）
SELECT '④ 已送达单的商品行合计(元)' AS 检查项, ROUND(SUM(p.line_total), 2) AS 值
FROM order_products p JOIN orders o ON o.id = p.order_id WHERE o.status = 'DELIVERED';
SELECT '④ 账本里订单来源合计(元)', ROUND(SUM(total), 2) FROM ledgers WHERE source = 'ORDER';

SELECT '⑤ 订单状态分布' AS 检查项, status AS 值, COUNT(*) AS 单数
FROM orders GROUP BY status ORDER BY 单数 DESC;

SELECT '⑥ 逐月单量（应与造数报告一致）' AS 检查项, DATE_FORMAT(order_date, '%Y-%m') AS 值, COUNT(*) AS 单数
FROM orders GROUP BY 值 ORDER BY 值;

-- ⑦ 状态与照片：**别用 `NOT IN ('', '[]')` 比这一列**（它是 JSON，字符串比较不可靠，
--    第一版就是被这个骗了，报出"312 张非送达单却有照片"，实际那些单的值就是 `[]`）。
--    判据改成"里面有没有真 URL"，一眼可读。
SELECT '⑦ 非送达单里带了照片 URL 的（应为 0）' AS 检查项, COUNT(*) AS 值
FROM orders WHERE status <> 'DELIVERED' AND delivery_photo_urls LIKE '%/static/uploads/%';
SELECT '⑦b 已送达却没有照片 URL 的（应为 0）', COUNT(*)
FROM orders WHERE status = 'DELIVERED'
  AND (delivery_photo_urls IS NULL OR delivery_photo_urls NOT LIKE '%/static/uploads/%');

SELECT '⑧ 账号数' AS 检查项, COUNT(*) AS 值 FROM users;

SELECT '⑨ 抽查 3 个非送达单的 delivery_photo_urls 长什么样' AS 检查项;
SELECT order_no, status, LEFT(COALESCE(delivery_photo_urls, '<NULL>'), 70) AS 照片字段
FROM orders WHERE status <> 'DELIVERED' LIMIT 3;

-- ⑩ 那 8 行"账本日 ≠ 送达业务日"到底是什么（第一版抽查报出来的，得看清是不是真错）
SELECT '⑩ 账本日与送达业务日不一致的明细' AS 检查项;
SELECT l.id AS 账本行, l.order_id AS 单号, l.entry_date AS 账本日, o.status AS 状态,
       o.delivered_at AS 送达时刻UTC, o.order_date AS 下单日
FROM ledgers l JOIN orders o ON o.id = l.order_id
WHERE l.entry_date <> DATE(COALESCE(o.delivered_at, o.order_date) + INTERVAL 8 HOUR)
LIMIT 8;

-- ⑪ 照片 URL 指向的目录真的在盘上吗（抽样 5 张，只比目录存在性）
SELECT '⑪ 照片 URL 抽样' AS 检查项, o.order_no, LEFT(o.delivery_photo_urls, 60) AS 照片字段
FROM orders o WHERE o.status = 'DELIVERED' AND o.delivery_photo_urls IS NOT NULL LIMIT 5;
