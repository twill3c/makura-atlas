#!/usr/bin/env python3
"""wtctl.py — worktree 並列 + クリーンベースライン + 差分ゲート。

Python 標準ライブラリ + git のみで動作する。仕様は WT_SPEC.md(WT-xx)。

使い方:
  python scripts/wtctl.py open  --loop loop_004 [--base main]
  python scripts/wtctl.py list
  python scripts/wtctl.py gate  [--base main]          # 差分ゲート単体(CI でも使用)
  python scripts/wtctl.py check                        # worktree 内で: ゲート + 失敗帰属
  python scripts/wtctl.py close --loop loop_004 [--force]
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

JST = dt.timezone(dt.timedelta(hours=9))
BASELINE_FILE = ".wt-baseline.json"

DEFAULT_CONFIG = {
    "base_branch": "main",
    "test_command": "python -m pytest -q --tb=no",
    "setup_command": None,
    "gate": {
        "max_total_lines": 500,
        "max_files": 30,
        "exempt": ["logs/loops/*", "out/*", "*.lock", "docs/generated/*"],
    },
    "secret_scan": True,
}

SECRET_BLOCK = [
    (r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", "秘密鍵ヘッダ"),
    (r"AKIA[0-9A-Z]{16}", "AWS アクセスキー"),
    (r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[=:]\s*['\"][^'\"]{8,}['\"]", "資格情報の直書き"),
]
SECRET_WARN = [
    (r"\beval\s*\(", "eval() の使用"),
    (r"(?i)(execute|cursor\.execute)\s*\(\s*[\"'].*%s.*[\"']\s*%", "SQL 文字列連結の疑い"),
]


def git(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失敗:\n{r.stderr.strip()}")
    return r.stdout


def repo_root(cwd: Path | None = None) -> Path:
    return Path(git(["rev-parse", "--show-toplevel"], cwd=cwd).strip())


def load_config(root: Path) -> dict:
    path = root / ".wt" / "gate.json"
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if path.exists():
        user = json.loads(path.read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def run_tests(cmd: str, cwd: Path) -> dict:
    """テストを実行し、緑/赤と失敗テスト ID(pytest の場合)を返す。"""
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    failed_ids = sorted(set(re.findall(r"^FAILED\s+(\S+)", r.stdout, re.MULTILINE)))
    tail = "\n".join((r.stdout.strip().splitlines() or [""])[-3:])
    return {
        "command": cmd,
        "returncode": r.returncode,
        "green": r.returncode == 0,
        "failed_ids": failed_ids,
        "summary": tail,
        "ts": dt.datetime.now(JST).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- open

def worktrees_dir(root: Path) -> Path:
    return root.parent / f"{root.name}.worktrees"


def cmd_open(args) -> int:
    root = repo_root()
    cfg = load_config(root)
    base = args.base or cfg["base_branch"]
    git(["rev-parse", "--verify", base])  # ベース存在確認
    branch = f"loop/{args.loop}"
    path = worktrees_dir(root) / args.loop
    if path.exists():
        raise SystemExit(f"既に存在します: {path}(WT-01a: 1 ループ 1 worktree)")
    path.parent.mkdir(parents=True, exist_ok=True)
    git(["worktree", "add", str(path), "-b", branch, base], cwd=root)
    print(f"worktree 作成: {path}(ブランチ {branch} ← {base})")

    setup = cfg.get("setup_command")
    if setup:
        # WT-02e: 依存インストール等をベースライン測定より前に実行する。
        # これを行わないと Node 等のプロジェクトでは常に偽の赤ベースラインになる(HC-001)
        print(f"セットアップ実行中(WT-02e): {setup}")
        r = subprocess.run(setup, shell=True, cwd=path, capture_output=True, text=True)
        if r.returncode != 0:
            tail = "\n".join(((r.stderr or r.stdout).strip().splitlines() or [""])[-5:])
            print(f"  ✗ setup_command 失敗(exit {r.returncode}):\n{tail}")
            print(f"  ベースラインは未測定です。原因解消後に open をやり直すか、"
                  f"`close --loop {args.loop} --force` で worktree を破棄してください")
            return 1

    print("クリーンベースライン測定中(WT-02a)…")
    baseline = run_tests(cfg["test_command"], path)
    baseline["base_branch"] = base
    baseline["base_commit"] = git(["rev-parse", "--short", base], cwd=root).strip()
    (path / BASELINE_FILE).write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if baseline["green"]:
        print(f"  ✓ ベースライン緑({baseline['summary']})— エージェントに引き渡し可能")
    else:
        print(f"  ⚠ ベースライン赤: 既存失敗 {len(baseline['failed_ids'])} 件を記録しました(WT-02b)")
        for fid in baseline["failed_ids"][:10]:
            print(f"      - {fid}")
        print("    以後の check では、この既存失敗はエージェントに帰属しません")
    print(f"次: cd {path} でループを開始(loop_start の記録を忘れずに)")
    return 0


# ---------------------------------------------------------------- gate

def numstat(base_ref: str, root: Path) -> list[tuple[int, int, str]]:
    mb = git(["merge-base", base_ref, "HEAD"], cwd=root).strip()
    out = git(["diff", "--numstat", mb], cwd=root)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a, d, f = parts
        rows.append((0 if a == "-" else int(a), 0 if d == "-" else int(d), f))
    return rows


def added_lines(base_ref: str, root: Path) -> list[tuple[str, int, str]]:
    mb = git(["merge-base", base_ref, "HEAD"], cwd=root).strip()
    out = git(["diff", "--unified=0", mb], cwd=root)
    result, fname, lineno = [], "?", 0
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            fname = line[6:]
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            result.append((fname, lineno, line[1:]))
            lineno += 1
    return result


def run_gate(root: Path, cfg: dict, base_ref: str) -> tuple[bool, list[str]]:
    msgs: list[str] = []
    ok = True
    exempt = cfg["gate"]["exempt"]

    def is_exempt(f: str) -> bool:
        return any(fnmatch.fnmatch(f, pat) for pat in exempt)

    rows = numstat(base_ref, root)
    counted = [(a, d, f) for a, d, f in rows if not is_exempt(f)]
    total = sum(a + d for a, d, _ in counted)
    nfiles = len(counted)
    exempted = len(rows) - nfiles
    limit_l = cfg["gate"]["max_total_lines"]
    limit_f = cfg["gate"]["max_files"]

    msgs.append(f"差分: {total} 行 / {nfiles} ファイル(免除 {exempted} ファイル、基準 {base_ref}→HEAD+未コミット)")
    if total > limit_l:
        ok = False
        msgs.append(f"  ✗ WT-03b: 総変更 {total} 行 > 上限 {limit_l} 行。上限を上げるのではなく PR を分割してください")
        top = sorted(counted, key=lambda r: -(r[0] + r[1]))[:5]
        for a, d, f in top:
            msgs.append(f"      {a+d:>5} 行  {f}")
    if nfiles > limit_f:
        ok = False
        msgs.append(f"  ✗ WT-03b: 変更 {nfiles} ファイル > 上限 {limit_f} ファイル")

    if cfg.get("secret_scan", True):
        hits_block, hits_warn = [], []
        for fname, lineno, text in added_lines(base_ref, root):
            if is_exempt(fname):
                continue
            for pat, label in SECRET_BLOCK:
                if re.search(pat, text):
                    hits_block.append(f"{fname}:{lineno} — {label}")
            for pat, label in SECRET_WARN:
                if re.search(pat, text):
                    hits_warn.append(f"{fname}:{lineno} — {label}")
        for h in hits_block:
            ok = False
            msgs.append(f"  ✗ WT-03d(block): {h}")
        for h in hits_warn:
            msgs.append(f"  ⚠ WT-03d(warn): {h}")

    msgs.append("ゲート: " + ("合格" if ok else "不合格"))
    return ok, msgs


def cmd_gate(args) -> int:
    root = repo_root()
    cfg = load_config(root)
    ok, msgs = run_gate(root, cfg, args.base or cfg["base_branch"])
    print("\n".join(msgs))
    return 0 if ok else 1


# ---------------------------------------------------------------- check

def cmd_check(args) -> int:
    root = repo_root()
    cfg = load_config(root)
    bl_path = root / BASELINE_FILE
    baseline = json.loads(bl_path.read_text(encoding="utf-8")) if bl_path.exists() else None
    base_ref = (baseline or {}).get("base_branch", cfg["base_branch"])

    ok, msgs = run_gate(root, cfg, base_ref)
    print("\n".join(msgs))

    print("\nテスト再実行 + 失敗帰属(WT-02c)…")
    current = run_tests(cfg["test_command"], root)
    if baseline is None:
        print("  ⚠ ベースラインなし(wtctl open で作られていない worktree)。全失敗を表示します")
        base_failed: set[str] = set()
    else:
        base_failed = set(baseline["failed_ids"])
    cur_failed = set(current["failed_ids"])
    new_f = sorted(cur_failed - base_failed)
    pre_f = sorted(cur_failed & base_failed)
    fixed = sorted(base_failed - cur_failed)

    print(f"  現在: {'緑' if current['green'] else '赤'}({current['summary']})")
    if fixed:
        print(f"  ✓ 既存失敗の修正: {len(fixed)} 件")
    if pre_f:
        print(f"  = 既存失敗の残存(帰属しない): {len(pre_f)} 件")
    if new_f:
        ok = False
        print(f"  ✗ 新規失敗(このループの変更に帰属 — GEN-REGRESS として記録すべき): {len(new_f)} 件")
        for fid in new_f[:10]:
            print(f"      - {fid}")

    print("\ncheck: " + ("合格 — PR 作成可(WT-02d)" if ok else "不合格 — PR 作成前に解消が必要"))
    return 0 if ok else 1


# ---------------------------------------------------------------- list / close

def cmd_list(args) -> int:
    root = repo_root()
    out = git(["worktree", "list", "--porcelain"], cwd=root)
    entries, cur = [], {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
        elif " " in line:
            k, v = line.split(" ", 1)
            cur[k] = v
        else:
            cur[line] = True
    if cur:
        entries.append(cur)

    for e in entries:
        path = Path(e["worktree"])
        branch = e.get("branch", "(detached)").replace("refs/heads/", "")
        dirty = bool(git(["status", "--porcelain"], cwd=path).strip())
        bl = path / BASELINE_FILE
        blmark = "-"
        if bl.exists():
            b = json.loads(bl.read_text(encoding="utf-8"))
            blmark = "緑" if b["green"] else f"赤({len(b['failed_ids'])})"
        main_mark = "(main checkout)" if path == root and not branch.startswith("loop/") else ""
        print(f"  {branch:<24} {'dirty' if dirty else 'clean':<6} baseline:{blmark:<8} {path} {main_mark}")
    return 0


def registered_worktrees(root: Path) -> set[Path]:
    out = git(["worktree", "list", "--porcelain"], cwd=root)
    return {
        Path(line[len("worktree "):].strip()).resolve()
        for line in out.splitlines()
        if line.startswith("worktree ")
    }


def remove_worktree(root: Path, path: Path, force: bool, attempts: int = 3) -> tuple[bool, str]:
    """WT-04c: Windows のファイルロック(node_modules 等)に備えてリトライする。"""
    err = ""
    for i in range(attempts):
        r = subprocess.run(
            ["git", "worktree", "remove", "--force" if force else "--", str(path)],
            cwd=root, capture_output=True, text=True)
        if r.returncode == 0:
            return True, ""
        err = r.stderr.strip()
        if i < attempts - 1:
            time.sleep(1.0)
    return False, err


def cmd_close(args) -> int:
    root = repo_root()
    cfg = load_config(root)
    branch = f"loop/{args.loop}"
    path = worktrees_dir(root) / args.loop
    if not path.exists():
        raise SystemExit(f"worktree が見つかりません: {path}")

    branch_exists = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", branch],
        cwd=root, capture_output=True).returncode == 0
    if not args.force:
        registered = path.resolve() in registered_worktrees(root)
        if registered and git(["status", "--porcelain"], cwd=path).strip():
            raise SystemExit(f"未コミットの変更があります: {path}(WT-04a。--force で無視)")
        if branch_exists:
            merged = subprocess.run(
                ["git", "merge-base", "--is-ancestor", branch, cfg["base_branch"]],
                cwd=root, capture_output=True).returncode == 0
            if not merged:
                raise SystemExit(f"{branch} は {cfg['base_branch']} に未マージです(WT-04a。--force で無視)")

    removed, err = remove_worktree(root, path, args.force)
    if not removed:
        subprocess.run(["git", "worktree", "prune"], cwd=root, capture_output=True)
        if path.resolve() in registered_worktrees(root):
            # 登録もディレクトリも残っている: 状態を変えずに失敗させる
            raise SystemExit(f"worktree を削除できません: {path}\n{err}")
        # 登録は解除済み(または元から未登録)。残骸の直接削除を試みる(WT-04c)
        try:
            shutil.rmtree(path)
            removed = True
        except OSError:
            pass

    subprocess.run(["git", "branch", "-D" if args.force else "-d", branch],
                   cwd=root, capture_output=True)
    if not removed:
        # 登録解除には成功し、ディレクトリ削除のみ失敗(WT-04c)。閉鎖としては成立
        print(f"⚠ WT-04c: worktree の登録は解除しましたが、ディレクトリを削除できませんでした")
        print(f"   (Windows のファイルロック等)。手動で削除してください: {path}")
        print(f"閉鎖(ディレクトリ残存): {branch}({path})")
        return 0
    print(f"閉鎖: {branch}({path})")
    return 0


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="worktree 並列 + 差分ゲート CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    op = sub.add_parser("open", help="ループ用 worktree を作成しベースラインを測る")
    op.add_argument("--loop", required=True)
    op.add_argument("--base", help="ベースブランチ(既定: gate.json / main)")
    op.set_defaults(func=cmd_open)

    lp = sub.add_parser("list", help="worktree 一覧と状態")
    lp.set_defaults(func=cmd_list)

    gp = sub.add_parser("gate", help="差分ゲート単体(CI でも使用)")
    gp.add_argument("--base")
    gp.set_defaults(func=cmd_gate)

    cp = sub.add_parser("check", help="worktree 内で: ゲート + テスト失敗の帰属判定")
    cp.set_defaults(func=cmd_check)

    xp = sub.add_parser("close", help="マージ済み worktree とブランチを片付ける")
    xp.add_argument("--loop", required=True)
    xp.add_argument("--force", action="store_true")
    xp.set_defaults(func=cmd_close)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
