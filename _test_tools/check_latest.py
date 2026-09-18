import requests
# 检查 latest 路径
try:
    r = requests.get("https://workbench-cli.oss-cn-hangzhou.aliyuncs.com/latest/checksums.sha256", timeout=30)
    print("checksums status:", r.status_code)
    print(r.text[:500])
except Exception as e:
    print("checksums FAIL:", e)

try:
    r2 = requests.head("https://workbench-cli.oss-cn-hangzhou.aliyuncs.com/latest/workbench-windows-amd64.zip", timeout=30)
    print("zip HEAD status:", r2.status_code, "len:", r2.headers.get("Content-Length"))
except Exception as e:
    print("zip FAIL:", e)