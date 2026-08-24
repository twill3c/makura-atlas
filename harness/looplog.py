#!/usr/bin/env python3
"""looplog.py — 構造化ループログの記録・検証・要約・エクスポート。

Python 標準ライブラリのみで動作する(LL-00e)。

使い方:
  python scripts/looplog.py append  --loop loop_003 --event loop_start \
      --data goal="Silver層の結合実装" spec_refs='["F-03"]' \
             scaffold_version=1.2.0 agent=claude-code
  python scripts/looplog.py append  --loop loop_003 --event failure \
      --data code=GEN-REGRESS severity=S2 detected_stage=5 \
             summary="T-032がデグレード" resolution=rollback
  python scripts/looplog.py append  --loop loop_003 --event correction \
      --data supersedes=12 reason="loop_end を誤順序で記録したため無効化(LL-08)"
  python scripts/looplog.py validate
  python scripts/looplog.py summary --loop loop_003
  python scripts/looplog.py export  --out out/
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

SCHEMA_VERSION = "1.2"
JST = dt.timezone(dt.timedelta(hours=9))

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR_DEFAULT = "logs/loops"
TAXONOMY_PATH = REPO_ROOT / "schema" / "taxonomy.json"

ENVELOPE_REQUIRED = ("v", "ts", "project", "loop_id", "event", "data")

EVENT_SPECS: dict[str, dict[str, tuple[type, ...]]] = {
    # event: {field: (types...)} — 必須フィールドのみ列挙(LOOP_LOG_SPEC §2)
    "loop_start": {
        "goal": (str,),
        "spec_refs": (list,),
        "scaffold_version": (str,),
        "agent": (str,),
    },
    "stage_end": {
        "stage": (int,),
        "stage_name": (str,),
        "result": (str,),
    },
    "test_run": {
        "command": (str,),
        "passed": (int,),
        "failed": (int,),
    },
    "failure": {
        "code": (str,),
        "severity": (str,),
        "detected_stage": (int,),
        "summary": (str,),
        "resolution": (str,),
    },
    "escalation": {
        "reason": (str,),
        "question": (str,),
    },
    "commit": {
        "sha": (str,),
        "kind": (str,),
    },
    "loop_end": {
        "outcome": (str,),
        "failure_count": (int,),
        "summary": (str,),
    },
    "correction": {
        "supersedes": (int,),
        "reason": (str,),
    },
}

ENUMS = {
    ("stage_end", "result"): {"pass", "fail", "skip"},
    ("loop_end", "outcome"): {"success", "partial", "aborted"},
    # data / spec はプロジェクト規約のコミット種別(HC-003: data 専用コミット、
    # スペック駆動プロジェクトの spec: コミット)を写像なしで記録するための拡張
    ("commit", "kind"): {"feat", "fix", "test", "docs", "refactor", "chore", "data", "spec"},
}


def load_taxonomy() -> dict:
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        return json.load(f)


def now_ts() -> str:
    return dt.datetime.now(JST).isoformat(timespec="seconds")


def detect_project() -> str:
    """プロジェクト名は主リポジトリのディレクトリ名から推定(--project で上書き可)。

    cwd 名をそのまま使うと、worktree(`../<repo>.worktrees/<loop_id>/`)での実行時に
    ループ ID が project として記録され、集計の結合キーが壊れる(HC-008)。
    worktree-kit の配置規約(WT-01a/b)→ git common dir → cwd 名の順で導出する。
    """
    cwd = Path.cwd()
    for anc in cwd.parents:
        if anc.name.endswith(".worktrees"):
            return anc.name[: -len(".worktrees")]
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            common = Path(r.stdout.strip())
            if not common.is_absolute():
                common = cwd / common
            common = common.resolve()
            if common.name == ".git":
                return common.parent.name
    except OSError:
        pass
    return cwd.name


def _v_tuple(v) -> tuple:
    """スキーマバージョン文字列を比較可能なタプルへ("1.2" → (1, 2))。"""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


# ---------------------------------------------------------------- corrections

def read_parsed(path: Path) -> list[tuple[int, dict]]:
    """(物理行番号, レコード) の列を返す。JSON 解析できない行は読み飛ばす(検証は validate_file 側)。"""
    parsed: list[tuple[int, dict]] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            parsed.append((lineno, rec))
    return parsed


def voided_event_counts(parsed: list[tuple[int, dict]]) -> dict[str, int]:
    """correction が無効化したレコードを event 別に数える(LL-09 修復スロット / HC-017)。"""
    by_line = {ln: rec for ln, rec in parsed}
    counts: dict[str, int] = {}
    for _, rec in parsed:
        if rec.get("event") != "correction":
            continue
        target = rec.get("data", {}).get("supersedes")
        if not isinstance(target, int):
            continue
        event = by_line.get(target, {}).get("event")
        if isinstance(event, str):
            counts[event] = counts.get(event, 0) + 1
    return counts


def apply_corrections(
    parsed: list[tuple[int, dict]], fname: str
) -> tuple[list[tuple[int, dict]], list[str]]:
    """correction イベントを適用した有効レコード列と、correction 自体の違反を返す(LL-08)。

    correction は supersedes(物理行番号)が指す先行レコードを無効化する。
    訂正後の正しいレコードは通常イベントとして追記し直す。
    """
    errs: list[str] = []
    by_line = {ln: rec for ln, rec in parsed}
    voided: set[int] = set()
    for ln, rec in parsed:
        if rec.get("event") != "correction":
            continue
        target = rec.get("data", {}).get("supersedes")
        if not isinstance(target, int) or target not in by_line or target >= ln:
            errs.append(
                f"{fname}:{ln}: correction.supersedes={target!r} は同一ファイル内の先行レコードの行番号を指すこと(LL-08)"
            )
            continue
        if by_line[target].get("event") == "correction":
            errs.append(f"{fname}:{ln}: correction を correction で訂正することはできない(LL-08)")
            continue
        if target in voided:
            errs.append(f"{fname}:{ln}: 行 {target} は既に訂正済み(LL-08)")
            continue
        voided.add(target)
    effective = [
        (ln, rec)
        for ln, rec in parsed
        if rec.get("event") != "correction" and ln not in voided
    ]
    return effective, errs


# ---------------------------------------------------------------- validate

def validate_record(rec: dict, taxonomy: dict, lineno: int, fname: str) -> list[str]:
    errs: list[str] = []
    loc = f"{fname}:{lineno}"

    for field in ENVELOPE_REQUIRED:
        if field not in rec:
            errs.append(f"{loc}: エンベロープ必須フィールド欠落: {field}")
    if errs:
        return errs

    event = rec["event"]
    if event not in EVENT_SPECS:
        return [f"{loc}: 未知のイベント種別: {event}"]

    data = rec["data"]
    if not isinstance(data, dict):
        return [f"{loc}: data はオブジェクトであること"]

    for field, types in EVENT_SPECS[event].items():
        if field not in data:
            errs.append(f"{loc}: {event}.data 必須フィールド欠落: {field}")
        elif not isinstance(data[field], types):
            errs.append(f"{loc}: {event}.data.{field} の型が不正")

    for (ev, field), allowed in ENUMS.items():
        if event == ev and field in data and data[field] not in allowed:
            errs.append(f"{loc}: {event}.data.{field}={data[field]!r} は {sorted(allowed)} のいずれかであること")

    if event == "failure":
        code = data.get("code")
        if code is not None and code not in taxonomy["codes"]:
            errs.append(f"{loc}: 失敗コード {code!r} は taxonomy.json に存在しない")
        sev = data.get("severity")
        if sev is not None and sev not in taxonomy["severities"]:
            errs.append(f"{loc}: severity {sev!r} は {sorted(taxonomy['severities'])} のいずれかであること")
        res = data.get("resolution")
        if res is not None and res not in taxonomy["resolutions"]:
            errs.append(f"{loc}: resolution {res!r} は taxonomy.json の resolutions に存在しない")
        if res == "harness_fix" and not data.get("harness_ref"):
            errs.append(f"{loc}: resolution=harness_fix には harness_ref(HC-xxx)が必須(LL-04)")

    return errs


def validate_file(path: Path, taxonomy: dict) -> tuple[list[str], list[str]]:
    """(違反, 警告) を返す。警告は exit code に影響しない(旧版レコードの既知汚染など)。"""
    errs: list[str] = []
    warns: list[str] = []
    parsed: list[tuple[int, dict]] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                errs.append(f"{path.name}:{lineno}: JSON 解析エラー: {e}")
                continue
            errs.extend(validate_record(rec, taxonomy, lineno, path.name))
            parsed.append((lineno, rec))

    if not parsed:
        return (errs or [f"{path.name}: レコードがありません"]), warns

    expected_loop = path.stem
    for lineno, rec in parsed:
        if rec.get("loop_id") and rec["loop_id"] != expected_loop:
            errs.append(f"{path.name}:{lineno}: loop_id={rec['loop_id']!r} がファイル名と不一致(LL-00b)")

    # project 検査(LL-14 / HC-008): worktree 実行での cwd 由来汚染を検出する。
    # v1.2 以降のレコードは違反、旧版レコードは追記専用(LL-00a)の既知汚染として
    # ファイル単位に集約した警告に落とす
    # correction 適用後の有効レコード列(LL-08)。LL-14 の project 検査も有効列で行う —
    # 汚染レコードを correction で無効化し正しい project で再追記する回復経路を成立させる(HC-009)
    effective, cerrs = apply_corrections(parsed, path.name)
    errs.extend(cerrs)

    strict_any = False
    projects: set[str] = set()
    legacy_polluted: list[int] = []
    for lineno, rec in effective:
        proj = rec.get("project")
        if not isinstance(proj, str):
            continue
        strict = _v_tuple(rec.get("v", "0")) >= (1, 2)
        strict_any = strict_any or strict
        projects.add(proj)
        if proj == rec.get("loop_id"):
            if strict:
                errs.append(f"{path.name}:{lineno}: project={proj!r} が loop_id と一致 — "
                            f"worktree 実行での cwd 由来汚染の疑い(LL-14 / HC-008)")
            else:
                legacy_polluted.append(lineno)
    if legacy_polluted:
        warns.append(f"{path.name}: 旧版レコード {len(legacy_polluted)} 件で project が "
                     f"loop_id と一致(行 {legacy_polluted[0]}–{legacy_polluted[-1]})— "
                     f"worktree 実行での cwd 由来汚染(LL-14 / HC-008)")
    if len(projects) > 1:
        msg = (f"{path.name}: project が混在 {sorted(projects)} — "
               f"1 ループ 1 プロジェクトであること(LL-14)")
        (errs if strict_any else warns).append(msg)

    ts_list = [rec.get("ts", "") for _, rec in parsed]
    if ts_list != sorted(ts_list):
        errs.append(f"{path.name}: ts が時系列順でない(LL-00a)")

    # 構造検査(LL-01 / LL-07)も同じ有効レコード列に対して行う(LL-08)
    records = [rec for _, rec in effective]
    if not records:
        errs.append(f"{path.name}: 有効レコードがありません(全レコードが訂正で無効化)")
        return errs, warns

    if records[0].get("event") != "loop_start":
        errs.append(f"{path.name}: 先頭イベントが loop_start でない(LL-01)")

    ends = [r for r in records if r.get("event") == "loop_end"]
    if len(ends) > 1:
        errs.append(f"{path.name}: loop_end が複数ある")
    if ends:
        # loop_end の後に来てよいのは修復スロットの差し替えだけ(LL-09 / HC-017)。
        # append 側と同じ規則で判定しないと、追記は通るのに validate が落ちる
        end_index = next(
            i for i, r in enumerate(records) if r.get("event") == "loop_end"
        )
        trailing = records[end_index + 1 :]
        budget = voided_event_counts(parsed)
        for r in trailing:
            event = r.get("event")
            if budget.get(event, 0) > 0:
                budget[event] -= 1
            else:
                errs.append(f"{path.name}: loop_end の後にレコードがある(LL-07)")
                break
        actual = sum(1 for r in records if r.get("event") == "failure")
        declared = ends[0].get("data", {}).get("failure_count")
        if declared is not None and declared != actual:
            errs.append(
                f"{path.name}: loop_end.failure_count={declared} だが failure レコードは {actual} 件(LL-07)"
            )
    return errs, warns


def iter_log_files(log_dir: Path):
    yield from sorted(log_dir.glob("*.jsonl"))


def cmd_validate(args) -> int:
    taxonomy = load_taxonomy()
    log_dir = Path(args.log_dir)
    if not log_dir.is_dir():
        print(f"ログディレクトリがありません: {log_dir}(記録がなければ合格扱い)")
        return 0
    all_errs: list[str] = []
    all_warns: list[str] = []
    n = 0
    for path in iter_log_files(log_dir):
        n += 1
        errs, warns = validate_file(path, taxonomy)
        all_errs.extend(errs)
        all_warns.extend(warns)
    if all_warns:
        print(f"⚠ {len(all_warns)} 件の警告(旧版レコードの既知の問題 — exit code に影響しない):")
        for w in all_warns:
            print(f"  - {w}")
    if all_errs:
        print(f"NG — {n} ファイル中 {len(all_errs)} 件の違反:")
        for e in all_errs:
            print(f"  - {e}")
        return 1
    print(f"OK — {n} ファイル、違反なし")
    return 0


# ---------------------------------------------------------------- append

def parse_kv(pairs: list[str], str_fields: frozenset[str] = frozenset()) -> dict:
    """key=value 列を data オブジェクトに変換。値は JSON として解釈を試み、失敗時は文字列。

    str_fields に挙がったキーは JSON 解釈をせず常に文字列として扱う。
    指数表記に見える git 短縮 sha(72817e6 等)が float 化して記録拒否される
    問題への恒久対処(HC-005)。
    """
    data: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--data は key=value 形式で指定してください: {pair!r}")
        key, _, raw = pair.partition("=")
        if key in str_fields:
            data[key] = raw
            continue
        try:
            data[key] = json.loads(raw)
        except json.JSONDecodeError:
            data[key] = raw
    return data


def repair_slot_open(parsed: list[tuple[int, dict]], event: str) -> bool:
    """完了済みループでの差し替えを許すか(LL-09 / HC-017)。

    correction が無効化したレコードと同じ event に限り、**無効化 1 件につき
    1 件だけ**追記を通す。これが無いと、閉じたループの failure を訂正した瞬間に
    loop_end.failure_count と実レコード数がずれ、LL-07 に永久に落ちる。
    """
    end_lines = [ln for ln, rec in parsed if rec.get("event") == "loop_end"]
    if not end_lines:
        return False
    end_line = max(end_lines)

    voided = voided_event_counts(parsed).get(event, 0)
    if voided == 0:
        return False

    replaced = sum(
        1 for ln, rec in parsed if ln > end_line and rec.get("event") == event
    )
    return replaced < voided


def cmd_append(args) -> int:
    taxonomy = load_taxonomy()
    # スキーマ上 str 固定のフィールドは生文字列のまま受け取る(HC-005)
    str_fields = frozenset(
        f for f, types in EVENT_SPECS.get(args.event, {}).items() if types == (str,)
    )
    rec = {
        "v": SCHEMA_VERSION,
        "ts": args.ts or now_ts(),
        "project": args.project or detect_project(),
        "loop_id": args.loop,
        "event": args.event,
        "data": parse_kv(args.data or [], str_fields),
    }
    errs = validate_record(rec, taxonomy, 0, "(new)")
    if errs:
        print("記録拒否 — スキーマ違反:")
        for e in errs:
            print(f"  - {e}")
        return 1

    # 完了済みループへの追記ガード(LL-09)と correction の追記時検査(LL-08)
    path = Path(args.log_dir) / f"{args.loop}.jsonl"
    existing = read_parsed(path) if path.exists() else []
    effective, _ = apply_corrections(existing, path.name)

    # project 一貫性ガード(LL-14 / HC-008): 同一ループへ異なる project で追記しない。
    # correction は旧汚染ループの回復経路のため対象外
    if args.event != "correction" and effective:
        existing_proj = effective[0][1].get("project")
        if isinstance(existing_proj, str) and rec["project"] != existing_proj:
            print(
                f"記録拒否 — project={rec['project']!r} は既存レコードの {existing_proj!r} と"
                f"不一致です(LL-14 / HC-008)。worktree と main checkout で実行場所が"
                f"変わっていないか確認し、必要なら --project で明示してください"
            )
            return 1

    if args.event == "correction":
        target = rec["data"]["supersedes"]
        if target not in {ln for ln, _ in effective}:
            print(
                f"記録拒否 — supersedes={target} は訂正可能なレコード行を指していません"
                "(存在しない・correction・訂正済みのいずれか)(LL-08)"
            )
            return 1
    elif any(r.get("event") == "loop_end" for _, r in effective):
        # correction が無効化したレコードの差し替えだけは通す(LL-09 修復スロット / HC-017)
        if not repair_slot_open(existing, args.event):
            print(
                f"記録拒否 — {args.loop} は loop_end 記録済みです(LL-09)。"
                f"誤記の回復は correction(supersedes=対象行番号)で {args.event} を無効化してから、"
                f"同じ {args.event} を 1 件だけ追記し直してください"
            )
            return 1

    # ツーストライク規則(LL-10)の警告: 同一コードの既存件数を数える
    if args.event == "failure":
        code = rec["data"]["code"]
        prior = 0
        log_dir = Path(args.log_dir)
        if log_dir.is_dir():
            for p in iter_log_files(log_dir):
                eff, _ = apply_corrections(read_parsed(p), p.name)
                prior += sum(
                    1
                    for _, r in eff
                    if r.get("event") == "failure" and r.get("data", {}).get("code") == code
                )
        total = prior + 1
        if rec["data"].get("severity") == "S1" and not rec["data"].get("harness_ref"):
            print(f"⚠ LL-12: S1 失敗です。HARNESS_CHANGELOG への起票と harness_ref の追記が必要です。")
        elif total == 2:
            print(f"⚠ LL-10: 失敗コード {code} が累計 {total} 回目です。HARNESS_CHANGELOG への起票が必要です。")
        elif total > 2 and not rec["data"].get("harness_ref"):
            print(f"⚠ LL-10: {code} は累計 {total} 回目。起票済み HC への harness_ref を付けてください。")

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"記録 → {path}({args.event})")
    return 0


# ---------------------------------------------------------------- summary

def cmd_summary(args) -> int:
    log_dir = Path(args.log_dir)
    paths = [log_dir / f"{args.loop}.jsonl"] if args.loop else list(iter_log_files(log_dir))
    taxonomy = load_taxonomy()
    for path in paths:
        if not path.exists():
            print(f"見つかりません: {path}")
            continue
        effective, _ = apply_corrections(read_parsed(path), path.name)
        records = [r for _, r in effective]
        start = next((r for r in records if r["event"] == "loop_start"), None)
        end = next((r for r in records if r["event"] == "loop_end"), None)
        failures = [r for r in records if r["event"] == "failure"]
        tests = [r for r in records if r["event"] == "test_run"]
        commits = [r for r in records if r["event"] == "commit"]

        print(f"── {path.stem}" + (f"({start['project']})" if start else ""))
        if start:
            print(f"   目標: {start['data']['goal']}  [{', '.join(start['data']['spec_refs'])}]"
                  f"  scaffold v{start['data']['scaffold_version']}")
        if end:
            print(f"   結果: {end['data']['outcome']} — {end['data']['summary']}")
        else:
            print("   結果: (進行中 — loop_end 未記録)")
        if tests:
            last = tests[-1]["data"]
            print(f"   テスト: {len(tests)} 回実行、最終 {last['passed']} 合格 / {last['failed']} 不合格")
        print(f"   コミット: {len(commits)} 件 / 失敗: {len(failures)} 件")
        for f_ in failures:
            d = f_["data"]
            name = taxonomy["codes"].get(d["code"], {}).get("name", "?")
            ref = f" → {d['harness_ref']}" if d.get("harness_ref") else ""
            print(f"     [{d['severity']}] {d['code']}({name}): {d['summary']} → {d['resolution']}{ref}")
    return 0


# ---------------------------------------------------------------- export

def flatten(rec: dict) -> dict:
    row = {k: rec[k] for k in ("v", "ts", "project", "loop_id", "event")}
    for k, v in rec["data"].items():
        row[f"data_{k}"] = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
    return row


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM 付き: Power BI/Excel の日本語対策
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"出力 → {path}({len(rows)} 行)")


def cmd_export(args) -> int:
    taxonomy = load_taxonomy()
    log_dir = Path(args.log_dir)
    out = Path(args.out)

    events: list[dict] = []      # 生レコード(correction 含む・監査粒度)
    eff_events: list[dict] = []  # correction 適用後(集計用)
    for path in iter_log_files(log_dir) if log_dir.is_dir() else []:
        parsed = read_parsed(path)
        events.extend(r for _, r in parsed)
        eff, _ = apply_corrections(parsed, path.name)
        eff_events.extend(r for _, r in eff)

    # fact_events: 全イベント(明細粒度・訂正含む生レコード)
    write_csv(out / "fact_events.csv", [flatten(r) for r in events])

    # fact_loops: ループ粒度(correction 適用後)
    loops: dict[tuple, dict] = {}
    for r in eff_events:
        key = (r["project"], r["loop_id"])
        row = loops.setdefault(key, {
            "project": r["project"], "loop_id": r["loop_id"],
            "started_at": None, "ended_at": None, "goal": None,
            "scaffold_version": None, "agent": None, "outcome": None,
            "n_failures": 0, "n_commits": 0, "n_test_runs": 0,
            "last_tests_passed": None, "last_tests_failed": None,
        })
        d = r["data"]
        if r["event"] == "loop_start":
            row.update(started_at=r["ts"], goal=d["goal"],
                       scaffold_version=d["scaffold_version"], agent=d["agent"])
        elif r["event"] == "loop_end":
            row.update(ended_at=r["ts"], outcome=d["outcome"])
        elif r["event"] == "failure":
            row["n_failures"] += 1
        elif r["event"] == "commit":
            row["n_commits"] += 1
        elif r["event"] == "test_run":
            row["n_test_runs"] += 1
            row["last_tests_passed"] = d["passed"]
            row["last_tests_failed"] = d["failed"]
    write_csv(out / "fact_loops.csv", list(loops.values()))

    # fact_failures: 失敗粒度(correction 適用後)
    frows = []
    for r in eff_events:
        if r["event"] != "failure":
            continue
        d = r["data"]
        frows.append({
            "ts": r["ts"], "project": r["project"], "loop_id": r["loop_id"],
            "code": d["code"], "severity": d["severity"],
            "detected_stage": d["detected_stage"],
            "introduced_stage": d.get("introduced_stage"),
            "summary": d["summary"], "resolution": d["resolution"],
            "harness_ref": d.get("harness_ref"),
        })
    write_csv(out / "fact_failures.csv", frows)

    # dim_failure_taxonomy: taxonomy.json から生成
    drows = [
        {"code": code, "category": info["category"],
         "category_name": taxonomy["categories"][info["category"]],
         "name": info["name"], "definition": info["definition"]}
        for code, info in taxonomy["codes"].items()
    ]
    write_csv(out / "dim_failure_taxonomy.csv", drows)

    # ツーストライク監視ビュー: コード別累計と起票状況
    counts = Counter(f["code"] for f in frows)
    trows = [
        {"code": code, "total": n,
         "needs_hc": n >= 2,
         "has_hc_ref": any(f["harness_ref"] for f in frows if f["code"] == code)}
        for code, n in sorted(counts.items(), key=lambda x: -x[1])
    ]
    write_csv(out / "view_two_strike.csv", trows)
    return 0


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="構造化ループログ CLI")
    p.add_argument("--log-dir", default=LOG_DIR_DEFAULT, help=f"ログ置き場(既定: {LOG_DIR_DEFAULT})")
    sub = p.add_subparsers(dest="cmd", required=True)

    ap = sub.add_parser("append", help="イベントを 1 件記録する")
    ap.add_argument("--loop", required=True)
    ap.add_argument("--event", required=True, choices=sorted(EVENT_SPECS))
    ap.add_argument("--project", help="省略時は主リポジトリ名を自動検出(worktree 実行にも対応 — HC-008)")
    ap.add_argument("--ts", help="省略時は現在時刻(JST)")
    ap.add_argument("--data", nargs="*", metavar="key=value")
    ap.set_defaults(func=cmd_append)

    vp = sub.add_parser("validate", help="全ログをスキーマ・規則検証する(CI 用)")
    vp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("summary", help="人間向け要約を表示する")
    sp.add_argument("--loop", help="省略時は全ループ")
    sp.set_defaults(func=cmd_summary)

    ep = sub.add_parser("export", help="Power BI 取込用 CSV 群を出力する")
    ep.add_argument("--out", default="out")
    ep.set_defaults(func=cmd_export)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
