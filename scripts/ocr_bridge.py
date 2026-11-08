#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ocr_bridge.py — 复用 local-ocr 的 RapidOCR 引擎，批量给摄取层的裁剪图打文字基准。

为什么不直接调 local-ocr/scripts/ocr.py：
  它的 CLI 只吃整个文件，而且 `--box` 只把置信度写进输出、坐标被丢掉了
  （`lines.append(f"[{score:.2f}] {text}" if box else text)`），没法按块对应。
  这里用同一个 RapidOCR 引擎，一次加载模型、批量处理摄取层切出来的条带，
  属于「复用现成库」，不是重写 OCR。

必须用 local-ocr 的 venv 解释器跑（venv_path.txt 里那个），
因为 rapidocr_onnxruntime 只装在那边：

    <ocr_venv_python> ocr_bridge.py <图1.png> [图2.png ...]

输出：单行 JSON 数组，每项
    {"file": "p001_s01.png", "ok": true, "full": "...", "lines": [{"text","score"}]}

失败项 ok=false 并带 error，绝不抛异常打断整批。
"""

from __future__ import annotations

import json
import os
import sys


def run(paths, min_score=0.0):
    from rapidocr_onnxruntime import RapidOCR

    eng = RapidOCR()
    out = []
    for p in paths:
        item = {'file': os.path.basename(p), 'ok': False, 'full': '', 'lines': []}
        if not os.path.exists(p):
            item['error'] = 'file not found'
            out.append(item)
            continue
        try:
            res, _ = eng(p)
            lines = []
            for _box, text, score in (res or []):
                t = str(text).strip()
                if t and float(score) >= min_score:
                    lines.append({'text': t, 'score': round(float(score), 3)})
            item['lines'] = lines
            item['full'] = '\n'.join(x['text'] for x in lines)
            item['ok'] = True
        except Exception as e:                                  # noqa: BLE001
            item['error'] = '%s: %s' % (type(e).__name__, str(e)[:160])
        out.append(item)
    return out


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    paths = sys.argv[1:]
    if not paths:
        print('[]')
        return 0
    try:
        print(json.dumps(run(paths), ensure_ascii=False))
    except Exception as e:                                      # noqa: BLE001
        # 引擎都起不来（未部署/依赖坏）时给空结果，让调用方静默降级
        print('[]')
        sys.stderr.write('ocr_bridge failed: %s\n' % e)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
