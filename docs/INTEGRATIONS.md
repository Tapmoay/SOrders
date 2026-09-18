# 第三方与基础设施集成约定

<!-- ref-prefix: android/app/src/main/java/com/tapmoay/sorders/ -->

供实现与代码生成时统一环境变量、接口形态与模块边界。详见 [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md)。

---

## 1. 高德地图

| 用途 | 说明 |
|------|------|
| 货主选点 | 高德 JS API（地图选点组件或 PlacePicker），回填经纬度与地址文本 |
| 司机导航 | Web 端：高德 URI / H5 导航；移动端优先唤起高德 App（`androidamap://` / iOS URL scheme） |

**环境变量**（见仓库根目录 [.env.example](../.env.example)）：

| 变量 | 说明 |
|------|------|
| `VITE_AMAP_KEY` / `AMAP_KEY` | 高德 Key（Web 端 JS Key；前端构建需 `VITE_` 前缀） |
| `AMAP_SECURITY_JS_CODE` | 若使用 JS API 2.0 安全密钥，配合服务端或白名单 |

**注意**：Key 需在高德控制台配置 **域名白名单**（HTTPS）；禁止把仅服务端密钥暴露给浏览器。

---

## 2. 账本导出（Excel / PDF）

| 环节 | 建议 |
|------|------|
| 触发 | 用户请求导出 → 创建 **异步任务**（`export_jobs`） |
| 生成 | 工作进程：Excel（如 `exceljs`）、PDF（如 `pdf-lib` / 服务端渲染） |
| 存储 | 生成文件上传 **对象存储**，得到限时签名 URL（或内部 file_id） |
| 通知 | 通过 **消息中心** 推送「导出完成」+ 下载链接（与需求 3.1.4 一致） |
| 权限 | 下载链接需校验用户身份与货主/派单员范围 |

大文件必须异步，避免阻塞 API 与超时。

---

## 3. WebSocket 与消息队列

| 组件 | 职责 |
|------|------|
| **WebSocket** | 客户端长连接：订单状态、派单/撤销、消息中心未读数 |
| **消息队列**（如 Redis Pub/Sub、RabbitMQ） | 解耦业务事件与推送实例；多实例部署时广播到持有连接的服务实例 |

**客户端行为**（与需求 3.4.3 对齐）：

- 断线自动重连（指数退避 + 上限）。
- 重连成功后 **拉取离线期间未读消息** 与关键状态增量。
- 服务端对关键事件（派单、撤销、送达）做 **未送达补发**（按用户维度记录待补发队列）。

---

## 4. 消息中心

| 项 | 说明 |
|----|------|
| 存储 | 持久化表：`messages`（用户 ID、类型、标题、正文、payload、已读、创建时间） |
| 推送 | 新消息写入 DB → 发 MQ → WS 推未读数或消息摘要 |
| 客户端 | 顶部消息图标 + 红点；支持已读、全部已读、删除 |
| 语音播报 | 司机端：见 §5「司机端新单提醒」——**不用系统 TTS**，用固定音频素材 + 重复播报（TTS 只做兜底） |

---

## 5. 司机端新单提醒（系统通知 + 语音播报 + 后台常驻）

需求原话：「派单员派的单给他，他那个要有对应的消息通信还有语音播报——说来，来单了来单了，
大概 3 秒钟，可以重复多次，就像货拉拉的样子」。下面这三层缺一层，司机那头就只是「今天没响」。

### 5.1 三层结构

| 层 | 做什么 | 在哪 |
|----|--------|------|
| **系统通知** | 消息进通知栏/锁屏，新单走**高优先级渠道**（有横幅、有震动、锁屏可见） | `core/NotifyCenter.kt` |
| **语音播报** | 司机端新单循环播「古典号角 + 来订单了，你有新的订单，请及时查看」（一段 ≈5 秒 × 用户设置的次数） | `core/NewOrderPlayer.kt` + `res/raw/new_order.wav` |
| **后台常驻** | 关掉 App / 熄屏后仍然收得到（前台服务按住进程，Socket 长连接不断） | `core/AlertService.kt` + `core/BootReceiver.kt` |

### 5.2 通知渠道（渠道 id 定了就别改，改了等于用户在系统里的设置被重置）

| 渠道 | 重要性 | 声音 | 用在哪 |
|------|--------|------|--------|
| `orders` | HIGH | **不出系统提示音**（声音由 App 自己放，才停得下来） | 新派单、任务撤回、订单取消 |
| `messages` | DEFAULT | 系统默认 | 普通站内信 |
| `service` | MIN | 无 | 后台接收的常驻通知（可一键关） |

### 5.3 播报规则（判定全在 `core/NewOrderAlert.kt`，纯函数、有单测）

| 维度 | 规则 |
|------|------|
| 谁播 | **只有司机**。派单员/货主大部分时间在电脑前，而且「来单了」对他们是错的信息 |
| 播什么 | 新派单 → `new_order.wav` = **古典号角（大小交替，≈1 秒）+ 语音「来订单了，你有新的订单，请及时查看」（≈3.7 秒）**；撤回/取消 → 只说一遍（复用同一段音频） |
| 播几次 | 用户可选 1 / 2 / 3 次 / 一直响到我接单（默认 3 次）；「一直响」有 60 秒止损 |
| 语音怎么来的 | **微软神经语音（edge-tts）**，不是手机/系统 TTS——第一版用 Windows SAPI 合成，用户听完的评价是「很机器人」，神经语音才有真人感（离线时自动退回 SAPI） |
| 去重 | 同一次派单后端会从 `notification` 与 `realtime` 两条链路各推一次，60 秒内同一单只响一次 |
| 何时闭嘴 | 司机接单 / 已送达 / 撤回 / 取消 / **点开通知** / 用户关掉开关 —— 都能立刻打断 |
| 音量 | 响的时候若媒体音量不足 **80%**，临时提到 80%，播完还原（可在设置里关）。**只抬不降**：用户自己开到 100% 时不该被我们按回去 |

### 5.4 后台常驻的两个硬约束

1. **前台服务类型用 `specialUse`（API 34+）**：Android 15 对 `dataSync` 有「每 24 小时累计 6 小时」
   的硬上限，司机的手机是要整天挂着的，被系统掐掉就等于又收不到单了。
   API 29~33 用 `dataSync`（那时还没有 `specialUse`），清单里两种都声明。
2. **Android 12+ 只允许 App 可见时启动前台服务**：所以启动点只有两个——
   进主界面（`RoleHomeScreen` 调 `AlertService.sync`）与开机/更新后（`BootReceiver`，走系统豁免）。
   设置页拨开关也走同一个 `sync`，避免两处逻辑分叉（分叉的表现是「设置里显示开着、其实服务没起」）。

### 5.5 权限清单

`POST_NOTIFICATIONS`、`VIBRATE`、`FOREGROUND_SERVICE`、
`FOREGROUND_SERVICE_DATA_SYNC`、`FOREGROUND_SERVICE_SPECIAL_USE`、`RECEIVE_BOOT_COMPLETED`。

省电策略白名单**不申请** `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`（Play 政策敏感），
而是从设置页跳到系统的「电池优化」列表让用户自己勾——状态用
`PowerManager.isIgnoringBatteryOptimizations` 读（读这个不需要权限）。

### 5.6 排障（司机说「没响」时按这个顺序看）

```
adb logcat -s SOrdersAlert          # 服务是否就绪 / 收到点击 / 开始播报 / 被打断 / 完整播了几次
adb shell dumpsys notification --noredact | findstr tapmoay   # 通知到底发出去没有（含渠道与优先级）
adb shell dumpsys activity services com.tapmoay.sorders         # 前台服务在不在（isForeground / types）
```

「没响」的三种情况在界面上完全一样，日志能分开：**根本没收到事件**（没有 `开始播报`）、
**收到了但素材放不出来**（有 `音频素材放不出来，退回系统 TTS`）、**收到了但被用户设置关掉**
（有 `不播报：语音提醒被用户关掉了`）。

### 5.7 素材与检查

- **重新生成音频**：`python _tools/media/_gen_new_order_clip.py`（号角用 numpy 合成；
  语音走 edge-tts 神经语音，**离线时自动退回 Windows SAPI**）。
  换音色：`--voice zh-CN-XiaoxiaoNeural`；挑音色：`--list-voices` / `--candidates`（多音色各出一份试听）。
  改完素材必须同步改 `NewOrderAlert.CLIP_MS`（脚本会直接打印该填的数字，红线还会拿 wav 头对账）。
- 红线：`python _tools/ai/_check_notify_guardrails.py`（权限/渠道/停止规则/素材结构/音量比例）。
- 反向验证：`python _tools/ai/_reverse_verify_notify.py`（28 种注入，证明红线真的会红）。
- 真机 E2E：`python _tools/notify/_assign_order.py`（走后端真实派单链路），
  操作模拟器用 `python _tools/notify/_ui.py`（按文字点，不写死坐标）。
- 音量核对（用户要求 80%）：先把媒体音量调低，再派一单，播放期间读
  `adb shell media volume --stream 3 --get`——播报中应是 80%，播完回到原值。

---

## 6. 司机端离线照片队列

| 项 | 说明 |
|----|------|
| 存储 | 浏览器 **IndexedDB** 存待上传 blob + 订单 ID + 重试次数 |
| 恢复 | 监听 `online` 或定时轮询，上传成功后删除本地记录 |
| 水印 | 上传前在 Canvas 绘制时间 + 地点（订单地址或 GPS）；失败时回退为仅时间 |

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-02 | 初版：与需求文档及 PROJECT_OVERVIEW 对齐 |
| 2026-09-16 | 新增 §5「司机端新单提醒」：系统通知渠道、语音播报规则、后台常驻（前台服务）与排障入口；§4 的语音播报改为指向实现 |

