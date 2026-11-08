#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""quark_ocr.py — 夸克扫描王 OCR 通道（手写 / 公式 / 印刷体三合一）。

为什么需要它（阶段22 真实作业实测）：
  RapidOCR 对学生的手写答案**完全读不出** —— 「重复赘余」被读成「这冰上次增可」，
  手写的 `C` 直接丢失。而批改看的就是手写答案。
  夸克把印刷体判为 PrintedText、手写判为 WrittenText、公式判为 PrintedFormula，
  实测手写置信度 1.00，且把手写内容嵌回正确位置（`……不同的一项(C)`）。

凭证：`<CREDENTIALS_FILE>`（不放技能目录，避免随技能被带走）
      {"client_id": "...", "client_secret": "..."}

用法（供 ingest_source 调用，也可命令行单测）：
    python quark_ocr.py <图片> [<图片2> ...]

⚠️ 三个必须知道的坑：
  1. 有 QPS 限流：连发会报 `A0300`。批量必须间隔 ≥1.2 秒。
  2. 复杂公式会降级为 `FormulaFigure`（只返回 base64 图片，不转文本）——
     这是静默失效，必须检查 `formula_figures` 并回退视觉模型。
  3. `reqId` 是必填字段，漏了会报 `A0201 缺少必填参数`（文档参数表里像个可选字段，其实不是）。

接口返回码：00000 成功 / A0300 限流 / A0401 图片太大 / A0403 宽高比过大
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ENDPOINT = "https://scan-business.quark.cn/vision"
CRED_FILE = Path.home() / '.workbuddy' / 'quark_credentials.json'
MIN_INTERVAL = 1.2          # 秒，低于这个值容易触发 A0300


def load_credentials():
    """返回 (client_id, client_secret)；未配置返回 (None, None)。"""
    if not CRED_FILE.exists():
        return None, None
    try:
        d = json.loads(CRED_FILE.read_text(encoding='utf-8'))
    except Exception:
        return None, None
    cid = (d.get('client_id') or '').strip()
    sec = (d.get('client_secret') or '').strip()
    return (cid, sec) if cid and sec else (None, None)


def available():
    cid, sec = load_credentials()
    return bool(cid and sec)


def _sign(cid, sec, nonce, ts):
    raw = f"{cid}_vision_SHA3-256_{nonce}_{ts}_{sec}"
    return hashlib.sha3_256(raw.encode('utf-8')).hexdigest()


def recognize(img_path, function_option='RecognizeGeneralDocument',
              need_image=False, timeout=120):
    """识别一张图。返回结构化 dict，失败也返回 dict（不抛异常）。

    {
      ok: bool, code: str, error: str,
      text: 全文,
      blocks: [{type, value, conf, pos}],   # type ∈ PrintedText/WrittenText/
                                            #   PrintedFormula/WrittenFormula/Illustration/Stamp
      written: [手写块],                     # 只要手写，批改直接用这个
      formulas: [公式块],
      formula_figures: int,                  # >0 说明公式没转文本，降级了
      degraded: bool,                        # 是否发生降级，调用方应回退视觉模型
      elapsed: 秒
    }
    """
    out = {'ok': False, 'code': '', 'error': '', 'text': '', 'blocks': [],
           'written': [], 'formulas': [], 'formula_figures': 0,
           'degraded': False, 'elapsed': 0.0}

    cid, sec = load_credentials()
    if not cid:
        out['error'] = 'unavailable: 未配置凭证文件'
        return out

    p = Path(img_path)
    if not p.exists():
        out['error'] = 'file not found: %s' % p
        return out
    try:
        b64 = base64.b64encode(p.read_bytes()).decode()
    except Exception as e:                                   # noqa: BLE001
        out['error'] = 'read failed: %s' % e
        return out

    nonce = uuid.uuid4().hex
    ts = int(time.time() * 1000)
    body = {
        'dataBase64': b64,
        'dataType': 'image',
        'serviceOption': 'ocr',
        'inputConfigs': json.dumps({'function_option': function_option}),
        'outputConfigs': json.dumps({'need_return_image': 'True' if need_image else 'False'}),
        'reqId': uuid.uuid4().hex,          # ← 必填！漏了报 A0201
        'clientId': cid,
        'signMethod': 'SHA3-256',
        'signNonce': nonce,
        'timestamp': ts,
        'signature': _sign(cid, sec, nonce, ts),
    }
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            resp = json.loads(e.read().decode('utf-8'))
        except Exception:                                    # noqa: BLE001
            out.update(error='HTTP %d' % e.code, elapsed=time.time() - t0)
            return out
    except Exception as e:                                   # noqa: BLE001
        out.update(error='%s: %s' % (type(e).__name__, str(e)[:120]),
                   elapsed=time.time() - t0)
        return out

    out['elapsed'] = round(time.time() - t0, 2)
    out['code'] = str(resp.get('code') or '')
    if out['code'] != '00000':
        out['error'] = '%s: %s' % (out['code'], (resp.get('message') or '')[:150])
        return out

    infos = ((resp.get('data') or {}).get('OcrInfo') or [])
    blocks = []
    texts = []
    for info in infos:
        texts.append(info.get('Text') or '')
        for det in info.get('Detail') or []:
            t = det.get('Type') or ''
            v = (det.get('Value') or '').strip()
            if t == 'FormulaFigure':
                out['formula_figures'] += 1
                continue
            if not v:
                continue
            rec = {'type': t, 'value': v,
                   'conf': round(float(det.get('Confidence') or 0), 3)}
            if det.get('Position'):
                rec['pos'] = det['Position']
            blocks.append(rec)
            if 'Written' in t:
                out['written'].append(rec)
            if 'Formula' in t:
                out['formulas'].append(rec)

    out.update(ok=True, text='\n'.join(x for x in texts if x), blocks=blocks)
    # 有 FormulaFigure 说明公式没转成文本 → 调用方必须回退视觉模型补
    out['degraded'] = out['formula_figures'] > 0
    return out


def recognize_batch(paths, interval=MIN_INTERVAL, **kw):
    """批量识别，自动控速。返回 {path: result}。"""
    out = {}
    last = 0.0
    for p in paths:
        wait = interval - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        out[str(p)] = recognize(p, **kw)
        last = time.time()
    return out


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    if not available():
        print('❌ 未配置凭证：%s' % CRED_FILE)
        sys.exit(1)
    for p in args:
        r = recognize(p)
        print('\n=== %s ===' % Path(p).name)
        if not r['ok']:
            print('  ❌ %s' % r['error'])
            continue
        print('  ✅ %.2fs  块=%d 手写=%d 公式=%d 降级=%s'
              % (r['elapsed'], len(r['blocks']), len(r['written']),
                 len(r['formulas']), r['degraded']))
        for b in r['blocks']:
            print('    [%-15s] %.2f %r' % (b['type'], b['conf'], b['value'][:60]))
