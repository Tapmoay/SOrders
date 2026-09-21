-- 校验「日期筛选差 8 小时」这个修复：库里按**业务日**算出来的单数，必须等于接口按同一日期查出来的。
-- 业务日 = `DATE(created_at + INTERVAL 8 HOUR)`（库里存 UTC，业务时区 +8）。
-- 配合 `_verify_date_window.py`（那边打接口拿数字）一起看 —— 两个数相等才算修好了。
SELECT '库里按业务日算：2026-09-21 下单的单数' AS 检查项, COUNT(*) AS 值
FROM orders WHERE DATE(created_at + INTERVAL 8 HOUR) = '2026-09-21';

-- 对照：**修之前**接口实际取的是"北京 09-21 08:00 ~ 09-22 08:00"这个窗口，
-- 也就是库里下面这个数。两个数不同才说明修复真的改变了行为。
SELECT '（对照）按 UTC 零点口径：北京 09-21 08:00~09-22 08:00 的单数', COUNT(*)
FROM orders
WHERE created_at >= '2026-09-21 00:00:00' AND created_at < '2026-09-22 00:00:00';
