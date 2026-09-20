# 往模拟器里的 SOrders AI 聊天框发一条中文消息（并截图）。
#
# 为什么需要它：`adb shell input text` 打不了中文（NPE），
# 而"把文本弄进输入框 -> 点发送"这套动作每次要 4~5 次往返。
# 这里封成一个命令：一条消息 = 一次调用 + 一张截图。
#
# ⚠️ 两条踩出来的经验（2026-09-16 改）：
# 1. **粘贴改用 `input keyevent 279`（KEYCODE_PASTE）**，不要再走"长按 → 点 Paste 菜单"。
#    那个菜单的位置随键盘高度、输入框行数、系统版本一起变，实测点空过好几次
#    （表现是"脚本说已发送、其实输入框是空的"）。279 只要求输入框有焦点。
# 2. **发送按钮的位置不能写死**：输入框会随消息行数长高，发送按钮跟着它的垂直中心走。
#    所以用 `uiautomator dump` 找 EditText 的真实 bounds，把"在它右边、垂直中心与之对齐"
#    的那个可点节点认成发送按钮。
#
# ⛔ **前置条件：模拟器要开「剪贴板共享」**（2026-09-21 实测）：共享没开时 `Set-Clipboard` 只把文本放进
#    **宿主机**剪贴板，模拟器那边粘贴不到 —— 表现就是步骤 3 那句「粘贴没进输入框」（它**会**如实报错，
#    不会假装已发送）。临时绕法（不改模拟器设置）：`adb shell input text` 打 ASCII（中文要写拼音），
#    再手点输入框右边那个**蓝色圆箭头**发送键；⚠️ `input keyevent 66`（回车）只会插入换行，发不出去。
#
# 用法：
#   _emulator_say.ps1 -Text "给刘长顺生成 2026-10 的工资单"
#   _emulator_say.ps1 -Text "..." -NoSend        # 只粘贴不发送（核对输入框）
param(
    [Parameter(Mandatory = $true)][string]$Text,
    [string]$Serial = "emulator-5554",
    [int]$WaitSeconds = 25,
    [string]$Shot = "$env:TEMP\_dsh_say.png",
    [switch]$NoSend
)

$adb = 'D:\APPS\sdk\platform-tools\adb.exe'
$DUMP = Join-Path $env:TEMP "_dsh_ui.xml"

function Sh([string]$path) {
    & $adb -s $Serial shell screencap -p /sdcard/_shot.png | Out-Null
    & $adb -s $Serial pull /sdcard/_shot.png $path 2>&1 | Out-Null
}

function Get-Bounds($s) {
    if ($s -match '\[(\d+),(\d+)\]\[(\d+),(\d+)\]') {
        return @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], [int]$Matches[4])
    }
    return $null
}

function Dump-Nodes() {
    & $adb -s $Serial shell "uiautomator dump /sdcard/_ui.xml" | Out-Null
    & $adb -s $Serial pull /sdcard/_ui.xml $DUMP 2>&1 | Out-Null
    [xml]$doc = Get-Content $DUMP -Encoding UTF8 -Raw
    return $doc.SelectNodes("//node")
}

function Find-EditBox($nodes) {
    foreach ($n in $nodes) { if ($n.class -like "*EditText") { return (Get-Bounds $n.bounds) } }
    return $null
}

# 发送按钮 = 输入框右边、垂直中心与之对齐的可点节点
function Find-SendButton($nodes, $e) {
    $ecy = [int](($e[1] + $e[3]) / 2)
    $best = $null; $bestDx = 99999
    foreach ($n in $nodes) {
        if ($n.clickable -ne "true") { continue }
        $b = Get-Bounds $n.bounds
        if ($null -eq $b) { continue }
        if ($b[0] -le $e[2]) { continue }
        $cy = [int](($b[1] + $b[3]) / 2)
        if ([Math]::Abs($cy - $ecy) -gt 80) { continue }
        $dx = $b[0] - $e[2]
        if ($dx -lt $bestDx) { $bestDx = $dx; $best = $b }
    }
    if ($null -eq $best) { return $null }
    return @([int](($best[0] + $best[2]) / 2), [int](($best[1] + $best[3]) / 2))
}

# 1. 点一下输入框，让它拿到焦点（键盘会跟着弹起来）
$nodes = Dump-Nodes
$box = Find-EditBox $nodes
if ($null -eq $box) { $box = @(32, 2232, 890, 2379) }   # 兜底：键盘收起时的实测位置
$ex = [int](($box[0] + $box[2]) / 2)
$ey = [int](($box[1] + $box[3]) / 2)
& $adb -s $Serial shell "input tap $ex $ey" | Out-Null
Start-Sleep -Milliseconds 1500

# 2. 把文本放进系统剪贴板（模拟器同步宿主机剪贴板），再按 KEYCODE_PASTE
Set-Clipboard -Value $Text
Start-Sleep -Milliseconds 400
& $adb -s $Serial shell "input keyevent 279" | Out-Null
Start-Sleep -Milliseconds 1200

# 3. 核对真的粘进去了（粘失败时**必须报错**，不能假装已发送）
$nodes2 = Dump-Nodes
$box2 = Find-EditBox $nodes2
if ($null -ne $box2) { $box = $box2 }
$got = ""
foreach ($n in $nodes2) { if ($n.class -like "*EditText") { $got = $n.text; break } }
if ([string]::IsNullOrWhiteSpace($got)) {
    Sh $Shot
    Write-Output "⚠️ 粘贴没进输入框（EditText 是空的），消息没发出去（截图见 $Shot）"
    exit 1
}

if ($NoSend) {
    Sh $Shot
    Write-Output "已粘贴未发送（输入框现在是「$got」）-> $Shot"
    exit 0
}

# 4. 粘贴后输入框变高了，重新量一次再点发送
$send = Find-SendButton $nodes2 $box
if ($null -eq $send) {
    Sh $Shot
    Write-Output "⚠️ 没找到发送按钮，消息没发出去（截图见 $Shot）"
    exit 1
}
& $adb -s $Serial shell "input tap $($send[0]) $($send[1])" | Out-Null
Start-Sleep -Seconds $WaitSeconds
Sh $Shot
Write-Output "已发送「$got」（发送按钮 $($send[0]),$($send[1])）并截图 -> $Shot"
