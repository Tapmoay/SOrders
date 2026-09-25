"""报表的**只读查询边界**（第二轮 R2-05 · 指南 §八 / §九）。

指南 §八：「报表是**事实消费者，而不是事实生产者**」。

  turnover_query.py / product_query.py / arrears_query.py / loader.py / _common.py

⛔ 判据 `_tools/qa/_check_report_boundary.py` 在 AST 层面钉着这个包。
"""
