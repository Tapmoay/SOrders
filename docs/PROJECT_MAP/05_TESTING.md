# 05 测试手册（环境/账号/工具/坑）

> 本手册是"大规模测试"的执行基础。所有命令都基于 Windows 本机 + 模拟器。

## 1. 环境全景

| 组件 | 位置/启动 | 端口 |
|---|---|---|
| 后端 API+Socket | `cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` | 8000 |
| APK 静态下载（可选） | `python -m http.server 8001 --bind 0.0.0.0`（workdir=android/app/build/outputs/apk/debug） | 8001 |
| SQLite 库 | `backend/sorders.db` | - |
| Android SDK / 模拟器 | D:/APPS/sdk | - |
| adb | D:/APPS/sdk/platform-tools/adb.exe | - |

## 2. 模拟器与账号（三台）

| 端口 | AVD | 分辨率 | 用户角色 | 登录账号（密码均 pass12345） |
|---|---|---|---|---|
| **5554** | Pixel_2_XL_API_35 | 1440x2880 | 派单员 | 13800000001（Dispatcher） |
| **5556** | Pixel_6_API_35 | 1080x2400 | 货主（批发商 is_member） | 13800000002（Shipper） |
| **5558** | 7_WSVGA_Tablet_API_35 | 600x1024 | 司机 | 13800000003（Driver，另有 13000000009 SALARY 司机） |

### 启动模拟器（电脑重启后必须重新启动）
```powershell
Start-Process 'D:/APPS/sdk/emulator/emulator.exe' -ArgumentList '-avd Pixel_2_XL_API_35 -port 5554'
Start-Process 'D:/APPS/sdk/emulator/emulator.exe' -ArgumentList '-avd Pixel_6_API_35 -port 5556'
Start-Process 'D:/APPS/sdk/emulator/emulator.exe' -ArgumentList '-avd 7_WSVGA_Tablet_API_35 -port 5558'
# 冷启动约 2 分钟；日志文件按端口分（_emu_55xx.log）避免锁冲突
```

### 通用操作
```powershell
adb devices                          # 在线设备
adb -s emulator-5554 install -r app-debug.apk   # 重装（keep 登录态）
adb -s emulator-5554 shell am force-stop com.tapmoay.sorders
adb -s emulator-5554 shell monkey -p com.tapmoay.sorders -c android.intent.category.LAUNCHER 1  # 启动
```

## 3. 测试数据（现有）

**商品**（id, 名称, 默认价, 批价档）：
- id1 ttt 23.5（批价一21/二19）｜id2 325 34（30/28）｜id3 红富士 12.5（11/10.5/10）｜id4 香蕉 8（7.2/6.8）
- id5 砂糖橘 15（13.5/13/12.5）｜id6 农夫山泉 22（20/19）｜id7 苹果汁 30（27/25/24/23）｜id8 火腿肠 45（42/40/38）

**批发商**：id2 Shipper(13800000002, is_member)｜id5 老李｜id6 恒通｜id7 宏发
**price_rules**：s2: p1=21.15 / p2=30.6 / p8=28；s5/s6/s7 各 8 条（批价一）
**订单**：SO20260831556999（已 ACCEPTED+坐标 29.28105,117.18734 景德镇陶瓷博物馆东门）｜SO20260903846523（ttt×10 已送达）
**其他**：9-3 当天 7 单已送达（营业额 ¥1104.50 / 运费 ¥45 / 货损 ttt×2 ¥40 / cash 已收 ¥23.5 / 挂账 ¥1081）

## 4. 常用命令速查

```powershell
# 登录并调接口（PowerShell）
$tok=(Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/v1/auth/login' -ContentType 'application/json' -Body '{"phone":"13800000001","password":"pass12345"}').access_token
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/reports/turnover?mode=day&date=2026-09-03' -Headers @{Authorization="Bearer $tok"}

# 截图（注意 PowerShell > 重定向会损坏二进制！用 python）
python -c "import subprocess; d=subprocess.run(['D:/APPS/sdk/platform-tools/adb.exe','-s','emulator-5554','exec-out','screencap','-p'],capture_output=True).stdout; open('shot.png','wb').write(d)"

# uiautomator dump
adb -s emulator-5554 shell uiautomator dump /sdcard/ui.xml; adb -s emulator-5554 shell cat /sdcard/ui.xml > ui.xml

# 修改模拟器系统日期（验证跨日场景）
adb -s emulator-5554 root; adb -s emulator-5554 shell su 0 date 090308002026.00
```

## 5. UI 自动化经验（血泪坑）

| 场景 | 做法 / 坑 |
|---|---|
| 点击元素 | 先 uiautomator dump 或截图定位再 tap；Compose 页面 dump 可能**漏节点/为空** → 以截图为准 |
| tap 坐标换算 | 截图显示 565x1130 时设备坐标 ≈ 显示坐标 ×(1440/565, 2880/1130=2.549)；参考截图比例 |
| 底部导航点击 | y 坐标取 2720 左右（1440x2880），太低会进手势区 |
| AlertDialog 打开时 | `keyevent 4` 是**关弹窗**不是返回；表单点外部可能误关 |
| input text 弹键盘 | 键盘会遮挡，点字段后输入内容可能点到别处；数字建议用步进按钮（+/-） |
| swipe 手势 | 起点 y≥2400 触发 Home 手势！起点 y<2300 才安全 |
| 中文 UI 文本 | dump 可能带空格（"确 认"）不匹配；模糊匹配 |
| DatePickerDialog | 选日期后必须点「确定」；点按钮位置用截图量（不同分辨率不同） |

## 6. 后端/脚本常见坑

- **GBK 乱码**：python 输出中文 → `sys.stdout.reconfigure(encoding='utf-8')`
- **PowerShell && 不可用**：用分号或 cmd /c
- **PowerShell > 重定向二进制损坏**（adb exec-out screencap）→ 用 python subprocess
- **uvicorn 被旧进程占 8000**：`Get-NetTCPConnection -LocalPort 8000 -State Listen` → Stop-Process
- **.py 改动必重启** uvicorn；重启前确认旧进程已杀（job_kill 可能没杀干净）
- **git add -A 会误提交大量临时文件**（`_*.png`、`_dl/`、`_amap_probe/`）→ 只 add 源码路径
- 模拟器访问后端固定走 `10.0.2.2`；真机走 `local.properties api_base_url`；IP 变了=全端超时

## 7. 建议的回归测试清单（大规模测试用）

1. **登录**：三端账号登录/登出/会话恢复（重启 App 不失登录态）
2. **货主下单**：选商品（特价优先级）→ 数量 → 地址（地图/收藏）→ 提交 → 订单出现在待派单池
3. **派单**：池→指派（运费/计费/收现勾选）→ 司机端收到推送
4. **司机完成**：接单→送达→（拍照/现金/挂账分流）→ 状态 DELIVERED
5. **账本**：订单账自动同步、手动记账、货主账/批发商账聚合、收款单、挂账单位
6. **报表**：6 页数据/毛利覆盖率/待结运费/导出 xlsx 落盘
7. **导航**：订单详情 → 高德导航直拉
8. **异常**：超时自动异常、手动标记、解决
9. **库存/商品/价格**：商品增改、批价档、批量调价、库存流水
10. **消息**：Socket 实时刷新、消息中心
11. **导出**：账本导出租（异步任务）、报表导出（同步 xlsx）
