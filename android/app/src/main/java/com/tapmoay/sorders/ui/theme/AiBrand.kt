package com.tapmoay.sorders.ui.theme

import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

/**
 * AI 的品牌外观 = Google AI 智能体（Gemini）那套做法。
 *
 * 三件东西必须一起用，缺一个就不像了：
 *  1. **三段品牌渐变**（蓝 → 紫 → 粉），见 [AiBrandColors]；
 *  2. **渐变圆角块 + 白色四角星**的图标形态（Google 的 AI 图标就是这个样子）；
 *  3. 单色强调取渐变起点那个 Google 蓝（[AiBlue]）——按钮、链接、选中态用它。
 *
 * 为什么是"一个文件 + 一个函数"而不是各处自己写 `Brush.linearGradient(...)`：
 * 渐变只要有一处颜色顺序写反、或者少一段，出来的就不是那个观感了，
 * 而这种偏差**没有任何测试会报错**——只能靠"只有一处定义"来避免。
 */
val AiBrandColors: List<Color> = listOf(Color(AiBlue), Color(AiPurple), Color(AiPink))

/**
 * 对角渐变画刷（左上 → 右下）。
 *
 * 用在：工作台的 AI 图标块、聊天页空状态的星标徽章、发送键。
 * 白字/白图标压在上面时对比度：起点 #4285F4 对白 3.6:1、中段 4.0:1、终点 3.0:1，
 * 都是大图标（≥24dp）而非小字，够用；**不要**把白色小字压在渐变终点那一段上。
 */
fun aiBrandBrush(): Brush = Brush.linearGradient(AiBrandColors)
