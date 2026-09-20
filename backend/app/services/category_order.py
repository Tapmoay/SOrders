"""分类名册「整份顺序」的校验 —— 商品 / 地点 / 开销 / 运费 四个名册**共用这一份**。

## 为什么必须收成一处（2026-09-21 精简）
四个 `/reorder` 端点原来各抄了一遍同样的 13 行校验。重复本身不致命，致命的是它守的
那条规矩：**只传一部分顺序时，"没提到的那些该排哪儿"是没有答案的** ——
按"没提到的保持原序"实现，会在两端各错一次，而且**不报错**（用户只会发现"顺序又乱了"）。
四个副本意味着这条规矩要改四次，漏一处就是那一个名册静默错位。

## 三条判据（顺序就是用户看到的报错顺序）
1. 同一编号出现两次 → 拒绝（"整份顺序"里出现重复说明客户端自己拼错了）；
2. 有编号不在这个名册里 → 拒绝。⚠️ **不许区分"编号不存在"与"这行不是你的"**：
   那会把"这个编号存不存在"变成一条可以探测的信息（见 `place_categories.py` 的按人分区）；
3. 名册里有行没被提到 → 拒绝，并**告诉他少了哪几个**（只列前 5 个，多的用「…」带过）。
"""

from __future__ import annotations

from typing import Any, Iterable

from fastapi import HTTPException

__all__ = ["ordered_ids"]


def ordered_ids(by_id: dict[int, Any], raw_ids: Iterable[int]) -> list[int]:
    """校验「整份顺序」，通过则**原样返回**它（调用方据此逐行写 `sort_order`）。

    `by_id` 是"这个名册里现有的行"（调用方按各自的可见范围查出来）；校验只看编号集合，
    不碰数据库 —— 写库仍由各端点自己做（四个名册的审计动作与计数各不相同）。
    """
    ids = list(raw_ids)
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=400, detail="顺序里有重复的分类，请重新排一次")
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise HTTPException(status_code=400, detail=f"顺序里有不存在的分类编号：{unknown}")
    missing = [i for i in by_id if i not in set(ids)]
    if missing:
        names = "、".join(by_id[i].name for i in missing[:5])
        raise HTTPException(
            status_code=400,
            detail=f"顺序里少了 {len(missing)} 个分类（{names}…）。请提交**完整**的分类顺序。",
        )
    return ids
