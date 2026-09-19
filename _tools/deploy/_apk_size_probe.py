"""APK 体积构成探测：为什么这个包有 74MB（判断"分 ABI / 开 R8"能省多少）。"""
import sys, zipfile, collections, os

path = sys.argv[1] if len(sys.argv) > 1 else r"android\app\build\outputs\apk\debug\app-debug.apk"
print("APK:", path, os.path.getsize(path), "bytes")

z = zipfile.ZipFile(path)
buckets = collections.Counter()
detail = collections.Counter()
for i in z.infolist():
    n = i.filename
    c = i.compress_size
    if n.startswith("lib/"):
        parts = n.split("/")
        abi = parts[1] if len(parts) > 2 else "?"
        buckets["lib/" + abi] += c
        detail[n] += c
    elif n.startswith("classes") and n.endswith(".dex"):
        buckets["dex"] += c
    elif n.startswith("assets/"):
        buckets["assets"] += c
        detail[n] += c
    elif n.startswith("res/"):
        buckets["res"] += c
    elif n.startswith("META-INF/"):
        buckets["META-INF"] += c
    else:
        buckets["other"] += c

total = sum(buckets.values())
print("--- 压缩后体积分布 (MB) ---")
for k, v in buckets.most_common():
    print(f"  {k:28s} {v/1048576:8.2f} MB  {v*100.0/total:5.1f}%")
print(f"  {'TOTAL':28s} {total/1048576:8.2f} MB")

print("--- lib 明细 (MB, 压缩后) ---")
for k, v in detail.most_common(20):
    if k.startswith("lib/"):
        print(f"  {k:56s} {v/1048576:7.2f} MB")

print("--- assets 明细 top15 (MB, 压缩后) ---")
for k, v in detail.most_common(40):
    if k.startswith("assets/"):
        print(f"  {k:56s} {v/1048576:7.2f} MB")
