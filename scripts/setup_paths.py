#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""首次使用：把文档与脚本里的路径占位符替换成你的实际路径。

默认 dry-run（只预览）。加 --apply 才写回文件。

    python scripts/setup_paths.py --skill-dir /abs/skill --workspace /abs/workspace
    python scripts/setup_paths.py --skill-dir /abs/skill --workspace /abs/workspace --apply

占位符见 README §4.3。本脚本不会创建任何数据文件，也不会上传任何内容。

注意：`<UPSTREAM_OWNER>` / `<AUTOMATION_ID>` / `<REDACTED_TOKEN>` / `<DEVICE_SN>`
是「原值已被抹除」的标记，不是待配置项，无需替换；本脚本也不会去猜任何人的账号。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_EXT = {".md", ".py", ".yaml", ".yml", ".json", ".css", ".html", ".svg", ".txt"}
SELF = Path(__file__).resolve()

# 只替换这些已知占位符，避免误伤文档里的普通尖括号内容
PLACEHOLDERS = (
    "<SKILL_DIR>", "<WORKSPACE>", "<DATA_DIR>", "<RUNTIME_DIR>",
    "<NAS_DB_DIR>", "<HOME>", "<LEGACY_DIR>", "<LEGACY_SCRIPT>",
    "<CREDENTIALS_FILE>", "<UPSTREAM_REPO>",
)


def build_mapping(skill_dir: str, workspace: str,
                  credentials_file: str = "", upstream_repo: str = "") -> dict[str, str]:
    home = str(Path.home())
    return {
        "<SKILL_DIR>": skill_dir.rstrip("\\/"),
        "<WORKSPACE>": workspace.rstrip("\\/"),
        "<DATA_DIR>": os.path.join(workspace, "data"),
        "<RUNTIME_DIR>": os.path.join(workspace, "runtime"),
        "<NAS_DB_DIR>": os.path.join(workspace, "db"),
        "<HOME>": home,
        "<LEGACY_DIR>": workspace.rstrip("\\/"),
        "<LEGACY_SCRIPT>": "setup.ps1",
        # 凭证与上游仓库都只写使用者自己的值，默认值不含任何账号 / key
        "<CREDENTIALS_FILE>": credentials_file or os.path.join(home, ".credentials", "ocr.json"),
        "<UPSTREAM_REPO>": upstream_repo or "<请填写你自己的上游仓库>",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="配置技能包里的路径占位符")
    ap.add_argument("--skill-dir", required=True, help="本技能包的绝对路径")
    ap.add_argument("--workspace", required=True, help="学习资料根目录的绝对路径")
    ap.add_argument("--credentials-file", default="",
                    help="你自己的 OCR 凭证文件绝对路径（本仓库绝不含任何凭证）")
    ap.add_argument("--upstream-repo", default="",
                    help="你自己的上游知识图谱仓库（格式 owner/repo，可选）")
    ap.add_argument("--apply", action="store_true", help="真正写回；不加则只预览")
    args = ap.parse_args()

    skill_dir = os.path.abspath(os.path.expanduser(args.skill_dir))
    workspace = os.path.abspath(os.path.expanduser(args.workspace))
    mapping = build_mapping(skill_dir, workspace,
                            args.credentials_file, args.upstream_repo)

    hits: list[tuple[Path, dict[str, int]]] = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p == SELF or p.suffix.lower() not in SCAN_EXT:
            continue
        if ".git" in p.parts or "__pycache__" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found = {k: text.count(k) for k in PLACEHOLDERS if k in text}
        if not found:
            continue
        hits.append((p, found))
        if args.apply:
            for k, v in mapping.items():
                text = text.replace(k, v)
            p.write_text(text, encoding="utf-8", newline="\n")

    mode = "已写回" if args.apply else "预览（未修改任何文件）"
    print(f"{mode}：命中 {len(hits)} 个文件")
    for p, found in hits:
        rel = p.relative_to(ROOT)
        detail = " ".join(f"{k}×{n}" for k, n in found.items())
        print(f"  {rel}  {detail}")
    if not args.apply and hits:
        print("\n确认无误后加 --apply 写回。")
    print("\n路径映射：")
    for k, v in mapping.items():
        print(f"  {k:<16} -> {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
