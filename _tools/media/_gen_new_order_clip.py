"""生成司机端「新单提醒」音频素材：古典号角 + 真人感语音。

### 为什么从「系统 TTS」换成这个
第一版是用 Windows 自带的 SAPI（Huihui）合成的，用户听完的反馈是：
「声音比较小」「语音很机器人」「要 80% 音量」「第一次是响亮的古典号角，大小交替响亮一下，
然后再是『来订单了，你有新的订单请及时查看』，这句话播 2~3 遍」。
SAPI 是拼接连绵音，机器感是它的天花板；改用微软 Edge 的**神经语音**（edge-tts）
才有真人感，代价是生成时要联网（离线时自动退回 SAPI，见 `_sapi_fallback`）。

### 成品结构
    [号角 哒-哒-哒——哒—— ≈1.0 秒] + [语音「来订单了，你有新的订单，请及时查看」≈3.x 秒]
整段由 App 按用户设置的次数重复播放（见 core/NewOrderAlert.kt）。

用法：
    python _tools/media/_gen_new_order_clip.py                # 默认音色，写进 res/raw/new_order.wav
    python _tools/media/_gen_new_order_clip.py --voice zh-CN-XiaoxiaoNeural
    python _tools/media/_gen_new_order_clip.py --list-voices  # 列出可选中文音色
    python _tools/media/_gen_new_order_clip.py --candidates   # 试听用：同一句话多音色各出一份
"""
import argparse
import asyncio
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "android/app/src/main/res/raw/new_order.wav"

TEXT = "来订单了，你有新的订单，请及时查看"

# 音色：默认取「云健」——解说/播报风格，有力但不刺耳，适合"有事了"这种提醒。
# （晓晓=亲切女声、云希=阳光男声、云扬=新闻男声，见 --list-voices）
DEFAULT_VOICE = "zh-CN-YunjianNeural"
DEFAULT_RATE = "+12%"

SR = 24000  # 神经语音原生 24kHz；跟着它走，避免重采样把清晰度磨掉

# 语音整体比号角低一点：号角负责"抓住注意力"，语音负责"说清是什么事"
HORN_PEAK = 0.97
VOICE_PEAK = 0.80
FINAL_PEAK = 0.99


def horn(dur_notes: list[tuple[float, float, float]]) -> np.ndarray:
    """合成号角。

    `dur_notes` = [(频率 Hz, 时长秒, 力度 0~1), ...]，力度就是用户说的「大小交替」。

    音色取「铜管」的做法：
    - 谐波叠加（1/n^0.8）：比正弦亮、比锯齿圆，听感像号角而不是蜂鸣器；
    - 每个音起头有一点点**向下弯音**（铜管起吹的"blat"），这是"真人吹的"关键细节；
    - 长音加 5.5Hz 颤音（±0.4%），不带颤音的长音听起来像电子音。
    """
    out = np.zeros(0, dtype=np.float64)
    t_all = np.arange(0, 1, 1 / SR)
    for freq, dur, gain in dur_notes:
        n = int(SR * dur)
        t = t_all[:n]
        # 起吹弯音：前 25ms 音高略高，快速回到基准
        bend = 1.0 + 0.012 * np.exp(-t / 0.018)
        # 长音（>0.3s）才有颤音
        vib = 1.0 + (0.004 * np.sin(2 * np.pi * 5.5 * t) if dur > 0.3 else 0.0)
        phase = 2 * np.pi * freq * np.cumsum(bend * vib) / SR
        wave_ = np.zeros(n, dtype=np.float64)
        for h in range(1, 9):
            wave_ += (1.0 / h**0.8) * np.sin(h * phase)
        wave_ /= np.max(np.abs(wave_))
        # 包络：12ms 起音（防爆音）、60ms 收尾
        env = np.ones(n)
        a = min(int(0.012 * SR), n)
        r = min(int(0.06 * SR), n)
        env[:a] = np.linspace(0, 1, a) ** 2
        env[n - r:] = np.linspace(1, 0, r) ** 1.5
        out = np.concatenate([out, wave_ * env * gain])
    # 号角整体归一化到 HORN_PEAK（"响亮"是需求，不是风格）
    m = np.max(np.abs(out))
    return out / m * HORN_PEAK if m > 0 else out


def silence(sec: float) -> np.ndarray:
    return np.zeros(int(SR * sec), dtype=np.float64)


def load_audio(path: Path) -> np.ndarray:
    """读任意格式（含 mp3）→ 单声道 float。优先 soundfile（libsndfile ≥1.1 支持 mp3）。"""
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    mono = data.mean(axis=1)
    if sr != SR:
        # 线性重采样够了：素材是语音，不追求采样级保真
        idx = np.linspace(0, len(mono) - 1, int(len(mono) * SR / sr))
        mono = np.interp(idx, np.arange(len(mono)), mono)
    return mono


async def edge_voice(text: str, voice: str, rate: str, dest: Path) -> None:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate)
    with open(dest, "wb") as fh:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
    if dest.stat().st_size < 2000:
        raise RuntimeError(f"在线语音返回内容过小（{dest.stat().st_size} 字节）")


def _sapi_fallback(text: str, dest: Path) -> None:
    """离线兜底：Windows 自带 Huihui。机器感比神经语音重，但总比"没声音"强。

    临时写一段 .ps1 而不是把中文塞进 -Command：PowerShell 5.1 按 ANSI 读命令行会读成乱码，
    合成出来就是乱码发音（这个坑踩过）。写文件时显式写 UTF-8 **with BOM**。
    """
    ps = f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -eq "zh-CN" }} | Select-Object -First 1
if ($v) {{ $s.SelectVoice($v.VoiceInfo.Name) }}
$s.Rate = 1
$s.Volume = 100
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo({SR},
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile("{dest}", $fmt)
$s.Speak("{text}")
$s.Dispose()
"""
    tmp = Path(tempfile.gettempdir()) / "sorders_sapi.ps1"
    tmp.write_text(ps, encoding="utf-8-sig")
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tmp)], check=True)


def build(voice: str, rate: str, text: str = TEXT) -> tuple[np.ndarray, str]:
    """→ (整段音频, 语音来源说明)"""
    tmp = Path(tempfile.gettempdir()) / "sorders_voice.mp3"
    src = ""
    try:
        asyncio.run(edge_voice(text, voice, rate, tmp))
        voice_pcm = load_audio(tmp)
        src = f"edge-tts {voice} {rate}"
    except Exception as e:  # 断网 / 服务变更 → 退回本机 SAPI
        print(f"⚠️ 在线语音不可用（{type(e).__name__}: {str(e)[:80]}）→ 退回 Windows SAPI")
        wav = Path(tempfile.gettempdir()) / "sorders_voice_sapi.wav"
        _sapi_fallback(text, wav)
        voice_pcm = load_audio(wav)
        src = "Windows SAPI Huihui（离线兜底）"

    vm = np.max(np.abs(voice_pcm))
    voice_pcm = voice_pcm / vm * VOICE_PEAK if vm > 0 else voice_pcm

    # 号角：哒(强) 哒(弱) 哒(强) 哒———(最强，拖长) —— 用户要的「大小交替响亮一下」
    fanfare = horn([
        (392.00, 0.17, 1.00),   # G4 强
        (523.25, 0.13, 0.55),   # C5 弱
        (659.25, 0.17, 1.00),   # E5 强
        (783.99, 0.52, 1.00),   # G5 最强（拖长）
    ])
    clip = np.concatenate([fanfare, silence(0.14), voice_pcm, silence(0.12)])
    m = np.max(np.abs(clip))
    if m > 0:
        clip = clip / m * FINAL_PEAK
    return clip, src


def write_wav(path: Path, pcm: np.ndarray) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(pcm, -1.0, 1.0)
    ints = (data * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(ints.tobytes())
    return len(ints) / SR


def list_voices() -> None:
    import edge_tts

    async def go():
        return await edge_tts.list_voices()

    for v in asyncio.run(go()):
        if v.get("Locale", "").startswith("zh-CN"):
            print(f"  {v['ShortName']:32s} {v.get('Gender',''):7s} {v.get('VoiceTag',{}).get('VoicePersonalities')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--rate", default=DEFAULT_RATE)
    ap.add_argument("--text", default=TEXT)
    ap.add_argument("--list-voices", action="store_true")
    ap.add_argument("--candidates", action="store_true", help="多音色各出一份整段音频供试听")
    args = ap.parse_args()

    if args.list_voices:
        print("可选中文音色：")
        list_voices()
        return 0

    if args.candidates:
        out_dir = ROOT / "_agent/voice-candidates"
        out_dir.mkdir(parents=True, exist_ok=True)
        picks = [
            ("zh-CN-YunjianNeural", "云健-解说有力"),
            ("zh-CN-YunxiNeural", "云希-阳光活泼"),
            ("zh-CN-YunyangNeural", "云扬-新闻专业"),
            ("zh-CN-XiaoxiaoNeural", "晓晓-亲切女声"),
            ("zh-CN-XiaoyiNeural", "晓伊-活泼女声"),
        ]
        for voice, label in picks:
            clip, src = build(voice, args.rate)
            p = out_dir / f"{voice}.wav"
            sec = write_wav(p, clip)
            print(f"✅ {label:16s} {sec:.2f}s  {p}")
        return 0

    clip, src = build(args.voice, args.rate, args.text)
    sec = write_wav(OUT, clip)
    wave_ms = int(round(sec * 1000))
    print(f"✅ 已生成 {OUT}")
    print(f"   语音来源：{src}")
    print(f"   整段时长：{sec:.2f} 秒（{wave_ms} ms）")
    print(f"   ⚠️ 请同步 NewOrderAlert.CLIP_MS = {wave_ms}L（红线会拿 wav 文件头对账）")
    print(f"   ⚠️ 号角时长常量 HORN_MS 也要核对：{int(round(1.0 * 1000))} ms 左右")
    return 0


if __name__ == "__main__":
    sys.exit(main())
