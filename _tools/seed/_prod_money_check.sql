-- 「钱对得上」判定（**避免连接扇出**：一单多行商品 × 一条账本行会让 SUM 重复计数 —— 踩过）。
-- 判据：对每个有"订单来源"账本行的单，账本合计 必须等于 该单商品行合计。
SELECT '账本(订单来源) 与 商品行合计 不一致的单数' AS 检查项, COUNT(*) AS 值 FROM (
  SELECT l.order_id,
         SUM(l.total) AS ledger_sum,
         (SELECT SUM(p.line_total) FROM order_products p WHERE p.order_id = l.order_id) AS prod_sum
  FROM ledgers l
  WHERE l.source = 'ORDER'
  GROUP BY l.order_id
) t
WHERE ABS(t.ledger_sum - COALESCE(t.prod_sum, 0)) > 0.005;

-- 顺便把不一致的单列出来（最多 5 张），便于判断是不是"退货/货损"那类合法差异
SELECT x.order_id AS 单号, x.ledger_sum AS 账本合计, x.prod_sum AS 商品行合计,
       ROUND(x.ledger_sum - COALESCE(x.prod_sum, 0), 2) AS 差额, o.status AS 状态
FROM (
  SELECT l.order_id,
         SUM(l.total) AS ledger_sum,
         (SELECT SUM(p.line_total) FROM order_products p WHERE p.order_id = l.order_id) AS prod_sum
  FROM ledgers l WHERE l.source = 'ORDER' GROUP BY l.order_id
) x JOIN orders o ON o.id = x.order_id
WHERE ABS(x.ledger_sum - COALESCE(x.prod_sum, 0)) > 0.005
LIMIT 5;
