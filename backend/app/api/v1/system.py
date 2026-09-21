"""系统级接口：给 App 的**运行期配置**（不是业务数据）。

现在只有一条：**测试账号的默认 AI 配置**（2026-09-21 用户要求：
「只要是测试账号默认就跑，我们那个 api key」）。

为什么放在服务端而不是编进 App：
这个仓库是**公开的**，APK 也挂在 `http://8.145.40.22/apk` 上给任何人下载 ——
把 key 编进包里等于公开它。放服务端 `.env`（600）之后，只有**登录 + 白名单**两头都过的
账号才能拿到，而且换 key 不用重新发版。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.deps import CurrentUser

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/ai-default")
def read_ai_default(current: CurrentUser) -> dict[str, str]:
    """测试账号的默认 AI 配置（api_key / base_url / model / note）。

    ### 三道门，缺一不可
    1. **必须登录**（`CurrentUser`）；
    2. **必须是白名单手机号**（`AI_TEST_PHONE_PREFIX` 前缀匹配；留空 = 能力关闭）；
    3. 服务端**没配 key 就如实 404** —— 不许返回空串让客户端去猜（那会变成
       "看起来配好了、一问就报错"，这个仓库把这一类列为最坏的一种 bug）。

    返回的是**明文 key**：它落到那台设备上，拿到测试账号的人就能读到（用户已确认这个取舍）。
    所以白名单必须收得紧，泄露了就换 key —— 换完不用发版，App 下次自检就会拿到新的。
    """
    settings = get_settings()
    prefix = settings.ai_test_phone_prefix.strip()
    phone = (getattr(current, "phone", "") or "").strip()

    if not prefix or not phone.startswith(prefix):
        raise HTTPException(status_code=403, detail="这个账号不是测试账号，默认模型服务不开放。")
    if not settings.ai_default_api_key.strip():
        raise HTTPException(status_code=404, detail="服务端还没有配置默认模型服务。")

    return {
        "api_key": settings.ai_default_api_key.strip(),
        "base_url": settings.ai_default_base_url.strip(),
        "model": settings.ai_default_model.strip(),
        "note": "测试账号默认模型服务（服务端下发；填上你自己的 Key 就会改用自己的）",
    }
