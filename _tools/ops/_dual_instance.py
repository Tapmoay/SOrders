#!/usr/bin/env python3
'''_dual_instance.py —— **真的起两个实例**，跑指南 §R3-03-D 要的那几个实验（R3-03）。

> ⛔ 指南原话：「不要：『代码看起来支持双实例』。要：Instance A / Instance B 真正同时启动。」

## 它做什么

```text
临时目录/
  ├── db.sqlite       两个实例共用同一个库（先跑 python -m app.migrations upgrade）
  └── uploads/        两个实例共用同一个上传目录（R3-03-A 的决策：本机文件系统资产）
实例 A: uvicorn :8111    实例 B: uvicorn :8112      （同一个 DATABASE_URL / UPLOADS_DIR / JWT_SECRET_KEY）
```

## 实验（--all 全跑）

| # | 实验 | 它证明什么 |
| --- | --- | --- |
| 1 | `rest` | 两个实例都接请求；A 登录拿到的 token 到 B 上**也认**（同一个库 + 同一个签名密钥）|
| 2 | `scheduler` | 两个实例同时启动时，启动即跑的那轮治理**只跑了一次**（选主生效）|
| 3 | `upload` | A 上传的图，**B 取得到**（同一个上传目录）|
| 4 | `kill` | 杀掉 A 之后 B 继续服务 |
| 5 | `socket` | ⛔ 本机**没有 Redis** → 如实报「没验」，不假装通过 |

## ⚠️ 它证不了什么（写在最前面，免得被当成更强的保证）

· 本机是 **SQLite**：跨主机的 `GET_LOCK`（迁移锁 / 调度锁）在 SQLite 上**如实不做**，
  所以「跨机器只跑一次」这一条**在这里证不了**，只证到「同机两个进程」；
· `socket` 那一格（A 建连接 / B 发事件）需要 Redis 适配器 —— 本机没有 Redis，本工具如实报未验；
· nginx upstream / 失败摘除需要 nginx —— 本机也没有，属 R3-05 的活。

用法：python _tools/ops/_dual_instance.py --all
'''
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
PORT_A, PORT_B = 8111, 8112
#: 两个实例**必须**用同一个签名密钥：否则 A 发的 token 到 B 上就是不合法，
#: 而那会表现成「多实例下用户一会儿掉线一会儿不掉」—— 这是多实例就绪度的一条硬前提。
TEST_SECRET = 'dual-instance-test-secret-32chars-min!!'
DISPATCHER_PHONE = '13800000001'
DISPATCHER_PASS = 'pass12345'


def sub_env(db: Path, uploads: Path, tmp: Path | None = None) -> dict:
    env = dict(os.environ)
    if tmp is not None:
        # ⛔ 把子进程的 TEMP/TMP 也指到本次临时目录：`_already_ran_today()` 的标记文件与
        #    两把锁的文件都在 `tempfile.gettempdir()` 下 —— 不隔离的话，**上一次跑留下的标记**
        #    会让这一次两个实例都直接走 `skipped_same_day`（第一版就是这么被骗过的：
        #    日志里两条「治理完成」，看着像「两个都跑了」，其实两条都是「跳过」）。
        env['TEMP'] = str(tmp)
        env['TMP'] = str(tmp)
    env['DATABASE_URL'] = 'sqlite:///' + str(db)
    env['UPLOADS_DIR'] = str(uploads)
    env['JWT_SECRET_KEY'] = TEST_SECRET
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    env.pop('SORDERS_SKIP_MIGRATIONS', None)
    return env


def run(code: str, env: dict) -> tuple[int, str]:
    p = subprocess.run([sys.executable, '-c', code], cwd=str(BACKEND), env=env,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def http(port: int, path: str, *, token: str | None = None, data: bytes | None = None,
         ctype: str | None = None, timeout: float = 10.0) -> tuple[int, bytes]:
    req = urllib.request.Request('http://127.0.0.1:' + str(port) + path, data=data, method='POST' if data else 'GET')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    if ctype:
        req.add_header('Content-Type', ctype)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:                                  # noqa: BLE001
        return 0, str(e).encode('utf-8', 'replace')


def multipart(field: str, filename: str, blob: bytes, ctype: str) -> tuple[bytes, str]:
    b = '----dual' + uuid.uuid4().hex
    body = b''.join([
        ('--' + b + chr(13) + chr(10)).encode(),
        ('Content-Disposition: form-data; name="' + field + '"; filename="' + filename + '"'
         + chr(13) + chr(10)).encode(),
        ('Content-Type: ' + ctype + chr(13) + chr(10) + chr(13) + chr(10)).encode(),
        blob, (chr(13) + chr(10)).encode(),
        ('--' + b + '--' + chr(13) + chr(10)).encode(),
    ])
    return body, 'multipart/form-data; boundary=' + b


class Instance:
    def __init__(self, name: str, port: int, db: Path, uploads: Path, tmp: Path) -> None:
        self.name, self.port = name, port
        self.log = tmp / ('log_' + name + '.txt')
        self._fh = open(self.log, 'w', encoding='utf-8')
        env = sub_env(db, uploads, tmp)
        self.proc = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
            cwd=str(BACKEND), env=env, stdout=self._fh, stderr=subprocess.STDOUT)

    def wait_ready(self, seconds: float = 90.0) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False
            # ⚠️ 给足超时：本机没有 Redis 时 `/health` 里那次探测要**等连接超时**（实测 ~2.0s），
            # 而第一版这里写的是 2.0s —— 于是每个探针都超时，两个实例都被判成「没起来」。
            code, _ = http(self.port, '/health', timeout=15.0)
            if code == 200:
                return True
            time.sleep(0.5)
        return False

    def text(self) -> str:
        self._fh.flush()
        try:
            return self.log.read_text(encoding='utf-8', errors='replace')
        except OSError:
            return ''

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=20)
        try:
            self._fh.close()
        except OSError:
            pass


def login(port: int) -> str | None:
    body = json.dumps({'phone': DISPATCHER_PHONE, 'password': DISPATCHER_PASS}).encode()
    code, raw = http(port, '/api/v1/auth/login', data=body, ctype='application/json')
    if code != 200:
        return None
    try:
        return json.loads(raw.decode('utf-8')).get('access_token')
    except Exception:                                       # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    for name in ('rest', 'scheduler', 'upload', 'kill', 'socket'):
        ap.add_argument('--' + name, action='store_true')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--keep', action='store_true', help='跑完不删临时目录（排障用）')
    a = ap.parse_args()
    picked = [n for n in ('rest', 'scheduler', 'upload', 'kill', 'socket')
              if a.all or getattr(a, n)] or ['rest', 'scheduler', 'upload', 'kill', 'socket']

    tmp = Path(tempfile.mkdtemp(prefix='r3_dual_'))
    print('临时目录：' + str(tmp))
    db, uploads = tmp / 'db.sqlite', tmp / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    env = sub_env(db, uploads, tmp)
    bad = 0
    A = B = None
    try:
        print('▶ 准备：迁移 + 造一个派单员账号')
        code, out = run('from app.core.schema_bootstrap import prepare_schema; '
                        'from sqlalchemy import create_engine; import os; '
                        'prepare_schema(create_engine(os.environ[' + repr('DATABASE_URL') + '], future=True)); '
                        'print(' + repr('schema ready') + ')', env)
        print('  ' + (out.strip().splitlines()[-1] if out.strip() else str(code)))
        code, out = run('from app.database import SessionLocal; from app.models import User; '
                        'from app.core.security import hash_password; '
                        'db = SessionLocal(); '
                        'u = db.query(User).filter(User.phone == ' + repr(DISPATCHER_PHONE) + ').first(); '
                        'u = u or User(username=' + repr(DISPATCHER_PHONE) + ', phone=' + repr(DISPATCHER_PHONE)
                        + ', password_hash=hash_password(' + repr(DISPATCHER_PASS)
                        + '), full_name=' + repr('DualDispatcher') + ', role=' + repr('dispatcher') + '); '
                        'db.add(u); db.commit(); print(' + repr('user ok') + ')', env)
        if 'user ok' not in out:
            print('❌ 造账号失败：' + out.strip()[-300:])
            return 1

        print('▶ 同时启动两个实例（A :' + str(PORT_A) + ' / B :' + str(PORT_B) + '）')
        A = Instance('A', PORT_A, db, uploads, tmp)
        B = Instance('B', PORT_B, db, uploads, tmp)
        ok_a, ok_b = A.wait_ready(), B.wait_ready()
        print('  A 就绪=' + str(ok_a) + '  B 就绪=' + str(ok_b))
        if not (ok_a and ok_b):
            print('❌ 有一个实例没起来（日志尾部）：');
            print((A.text() + B.text())[-1500:])
            return 1
        time.sleep(6)      # 让启动那轮治理跑完

        if 'rest' in picked:
            print('▶ 实验 1：两个实例都接请求 + token 跨实例有效')
            ca, _ = http(PORT_A, '/health')
            cb, _ = http(PORT_B, '/health')
            tok = login(PORT_A)
            me_b = http(PORT_B, '/api/v1/users/me', token=tok)[0] if tok else 0
            ok = ca == 200 and cb == 200 and me_b == 200
            print('  A /health=' + str(ca) + '  B /health=' + str(cb)
                  + '  A 登录=' + ('ok' if tok else 'fail') + '  B 用 A 的 token 读 /users/me=' + str(me_b))
            print('  ' + ('✅ 成立' if ok else '❌ 不成立'));
            bad += 0 if ok else 1

        if 'scheduler' in picked:
            print('▶ 实验 2：启动即跑的那轮治理只跑了一次（选主）')
            logs = A.text() + B.text()
            # ⛔ 判据必须看**返回了哪种结果**，不能只看有没有那行日志：
            #    `main` 那行是无条件打的（`数据保留治理完成: {...}`），跳过时打的是
            #    `{'skipped_same_day': 1}` —— 第一版按行数数，把「两个都跳过」读成了「两个都跑了」。
            real = [ln for ln in logs.splitlines()
                    if '数据保留治理完成' in ln and 'skipped' not in ln]
            # ⛔ 只数**结果行**（每个实例启动时恰好打一行 `数据保留治理完成: {...}`）：
            #    跳过会同时打「本轮跳过」的说明行和这一行结果 —— 把两行都数进去会重复计（第一版就是）。
            skipped = len([ln for ln in logs.splitlines()
                           if '数据保留治理完成' in ln and 'skipped' in ln])
            done = len(real)
            ok = done == 1 and skipped >= 1
            print('  真跑 ' + str(done) + ' 次 / 跳过 ' + str(skipped) + ' 次'
                  + '（跳过＝拿不到选主权或今天已跑过）')
            print('  ' + ('✅ 成立（只跑一次）' if ok else '❌ 不成立'));
            bad += 0 if ok else 1

        if 'upload' in picked:
            print('▶ 实验 3：A 上传的图，B 取得到')
            tok = login(PORT_A)
            blob = b'\xff\xd8\xff\xe0' + b'dual-instance-probe' * 8 + b'\xff\xd9'
            body, ctype = multipart('file', 'probe.jpg', blob, 'image/jpeg')
            st, raw = http(PORT_A, '/api/v1/shipper/locations/image', token=tok, data=body, ctype=ctype)
            url = ''
            try:
                url = json.loads(raw.decode('utf-8')).get('url', '')
            except Exception:                                   # noqa: BLE001
                pass
            got_b, back = (0, b'')
            if url:
                got_b, back = http(PORT_B, url)
            ok = st == 200 and got_b == 200 and back == blob
            print('  A 上传=' + str(st) + '  url=' + url + '  B 取=' + str(got_b)
                  + '  字节一致=' + str(back == blob))
            print('  ' + ('✅ 成立（同一个上传目录）' if ok else '❌ 不成立'));
            bad += 0 if ok else 1

        if 'kill' in picked:
            print('▶ 实验 4：杀掉 A 之后 B 继续服务')
            A.kill()
            time.sleep(2)
            cb, _ = http(PORT_B, '/health')
            tok = login(PORT_B)
            me = http(PORT_B, '/api/v1/users/me', token=tok)[0] if tok else 0
            ok = cb == 200 and me == 200
            print('  A 已杀；B /health=' + str(cb) + '  B 登录+读自己=' + str(me))
            print('  ' + ('✅ 成立' if ok else '❌ 不成立'));
            bad += 0 if ok else 1

        if 'socket' in picked:
            print('▶ 实验 5：A 建连接 / B 发事件（Socket.IO 跨实例）')
            print('  ⛔ **没验**：本机没有 Redis（Socket.IO 的跨进程适配器要它）。');
            print('     不假装通过，也不算失败 —— 这一格记在 docs/R3_PROGRESS.md 上是 ❌。')
            print('     要有意义的验证需要：一台有 Redis 的机器（本机装 Redis，或用生产机上的');
            print('     一个**独立 Redis DB 序号**跑一对临时实例）—— 前者要动本机环境，后者归属 R3-05。')
    finally:
        for inst in (A, B):
            if inst is not None:
                inst.kill()
        if a.keep:
            print('（--keep：临时目录保留在 ' + str(tmp) + '）')
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    if bad:
        print()
        print('❌ ' + str(bad) + ' 个实验不成立')
        return 1
    print()
    print('✅ 已跑的实验全部成立（socket 那一格如实未验，见上面的理由）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
