"""量两份播报素材的**音色**（基频），回答"这是谁的声音"。

### 为什么需要它
素材是二进制，`git` 里看不出音色，而**换错音色不会报任何错**：文件照样能播、
时长照样对得上，只有用户听到才知道不对。2026-09-21 就是这么出事的：
生成派单员那句时用了脚本当时的默认音色（云健，男声），而用户 2026-09-17 指定的是
**晓晓（女声）**——他一听就发现了。

判据是硬证据：把开头号角掐掉，对语音段逐帧自相关估基频。
女声（晓晓/晓伊）中位 F0 ≈ 200~280Hz，男声（云健/云希/云扬）≈ 90~140Hz。

用法：
    python _tools/media/_probe_clip_voice.py                        # 量 res/raw 下所有播报素材
    python _tools/media/_probe_clip_voice.py 某个.wav [另一个.wav]   # 量指定的文件
退出码：0 = 全部是女声（用户选的音色）；1 = 有素材不是（红线靠它变红）。
"""
import sys
import wave
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "android/app/src/main/res/raw"

SR = 24000
HORN_SKIP_S = 1.05       # 号角 ≈0.99 秒（G4/C5/E5/G5），再留一点余量
MIN_F0, MAX_F0 = 70.0, 400.0

#: 用户 2026-09-17 选的音色（见 `_gen_new_order_clip.py::DEFAULT_VOICE`）。女声的下限取 165Hz：
#: 晓晓实测 245~261Hz、晓伊也在这一带；男声最高约 140Hz，中间留出余量就不会误判。
FEMALE_MIN_HZ = 165.0


def voice_part(path: Path) -> np.ndarray:
    """掐掉开头号角与尾部静音，只留语音"""
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SR or w.getnchannels() != 1:
            raise SystemExit(f"{path.name}: 只处理 24kHz 单声道（实际 "
                             f"{w.getframerate()}Hz {w.getnchannels()}ch）")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
    seg = pcm[int(HORN_SKIP_S * SR):]
    win = int(0.02 * SR)
    energy = np.array([np.sqrt(np.mean(seg[i:i + win] ** 2)) for i in range(0, len(seg) - win, win)])
    loud = np.where(energy > 0.005)[0]
    return seg[: (loud[-1] + 1) * win] if len(loud) else seg


def f0_series(x: np.ndarray) -> np.ndarray:
    """逐帧自相关估基频（要的是量级，不是精确曲线）"""
    win, hop = int(0.04 * SR), int(0.02 * SR)
    lo, hi = int(SR / MAX_F0), int(SR / MIN_F0)
    out = []
    for i in range(0, max(0, len(x) - win), hop):
        frame = x[i:i + win]
        if np.sqrt(np.mean(frame ** 2)) < 0.02:       # 静音/清音帧跳过
            continue
        frame = frame - frame.mean()
        ac = np.correlate(frame, frame, mode="full")[win - 1:]
        ac /= (ac[0] + 1e-12)
        seg = ac[lo:hi]
        if not len(seg):
            continue
        lag = int(np.argmax(seg)) + lo
        if ac[lag] > 0.3:                              # 相关性太低说明这帧不可信
            out.append(SR / lag)
    return np.array(out)


def main() -> int:
    args = sys.argv[1:]
    files = [Path(a) for a in args] if args else sorted(RAW.glob("*.wav"))
    if not files:
        print(f"❌ {RAW} 下没有 wav")
        return 1
    bad = 0
    for path in files:
        if not path.exists():
            print(f"❌ 找不到 {path}")
            bad += 1
            continue
        f0 = f0_series(voice_part(path))
        if not len(f0):
            print(f"{path.name:24s} 量不出基频（素材是空的？）")
            bad += 1
            continue
        med = float(np.median(f0))
        female = med >= FEMALE_MIN_HZ
        bad += 0 if female else 1
        print(f"{'✅' if female else '❌'} {path.name:22s} 中位 F0 = {med:6.1f}Hz  → "
              f"{'女声（用户选的音色）' if female else '**不是女声——换错音色了**'}"
              f"   （10~90 分位 {np.percentile(f0, 10):.0f}~{np.percentile(f0, 90):.0f}Hz，{len(f0)} 帧）")
    if bad:
        print(f"\n❌ {bad} 份素材的音色不对。改法："
              f"python _tools/media/_gen_new_order_clip.py --kind {{driver,dispatcher}}"
              f"（默认音色就是用户选的晓晓，别加 --voice）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
