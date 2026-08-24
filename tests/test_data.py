# T-001..T-010, T-013 — データ層ゲート(TEST_SPEC.md にトレース)
#
# 期待値の出所(HC-016):
# - 44 という数は SPEC F-01 の仕様定数(採録数の実測ではない)
# - enum・範囲は SPEC F-01/F-05/F-06 の条項
# - 初段の koyomi 4 タグは原文「春はあけぼの…夏は夜…秋は夕暮…冬はつとめて」の構造が出所
# - 長徳の変(996)・定子崩御(1000)は概説書の通説年(SPEC §4 アンカー)
# - それ以外の件数は定数で書かず、集合の一致(取りこぼし・余分の不在)で書く

import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "web" / "data"


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def chapters():
    return load("chapters.json")


@pytest.fixture(scope="module")
def items_doc():
    return load("items.json")


@pytest.fixture(scope="module")
def events():
    return load("events.json")


@pytest.fixture(scope="module")
def emotion_tags():
    return load("emotion_tags.json")


# ---- T-001: 章段数は仕様定数 44(SPEC F-01) ----
@pytest.mark.unit
def test_t001_chapter_count(chapters):
    assert len(chapters) == 44  # SPEC F-01 の仕様定数


# ---- T-002: 必須フィールドと id 一意性 ----
@pytest.mark.unit
def test_t002_required_fields_and_unique_ids(chapters):
    ids = [c["id"] for c in chapters]
    assert len(ids) == len(set(ids)), "id が重複している"
    for c in chapters:
        for key in ("id", "title", "type", "v", "a", "excerpt", "tags"):
            assert key in c, f"{c.get('id', '?')}: {key} 欠落"
        assert isinstance(c["tags"], list)


# ---- T-003: v/a 範囲と型 enum ----
@pytest.mark.unit
def test_t003_ranges_and_type_enum(chapters):
    for c in chapters:
        assert -1.0 <= c["v"] <= 1.0, f"{c['id']}: v 範囲外"
        assert -1.0 <= c["a"] <= 1.0, f"{c['id']}: a 範囲外"
        assert c["type"] in ("zuiso", "ruiju", "nikki"), f"{c['id']}: type 不正"


# ---- T-004: 項目の参照整合 ----
@pytest.mark.integration
def test_t004_item_references(chapters, items_doc):
    by_id = {c["id"]: c for c in chapters}
    item_ids = [i["id"] for i in items_doc["items"]]
    assert len(item_ids) == len(set(item_ids)), "item id が重複している"
    for i in items_doc["items"]:
        assert i["chapId"] in by_id, f"{i['id']}: chapId {i['chapId']} が存在しない"
        assert by_id[i["chapId"]]["type"] == "ruiju", f"{i['id']}: 参照先が類聚章段でない"
        assert -1.0 <= i["v"] <= 1.0 and -1.0 <= i["a"] <= 1.0, f"{i['id']}: v/a 範囲外"


# ---- T-005: 解体対象の被覆(不変量: declared 集合 = 実在集合) ----
@pytest.mark.integration
def test_t005_coverage_invariant(items_doc):
    declared = set(items_doc["declared"])
    observed = {i["chapId"] for i in items_doc["items"]}
    assert declared - observed == set(), f"宣言されたが項目が無い: {declared - observed}"
    assert observed - declared == set(), f"項目があるのに未宣言: {observed - declared}"


# ---- T-006: 日記章段の年次フィールド(type=nikki ⇔ year を持つ) ----
@pytest.mark.unit
def test_t006_nikki_dating(chapters):
    for c in chapters:
        if c["type"] == "nikki":
            assert "year" in c, f"{c['id']}: 日記章段に year が無い"
            assert 990.0 <= c["year"] <= 1001.0, f"{c['id']}: year 範囲外"
            assert c.get("year_label"), f"{c['id']}: year_label 空"
            assert c.get("dating_basis"), f"{c['id']}: dating_basis 空"
            assert c.get("dating_conf") in ("high", "mid", "low"), f"{c['id']}: dating_conf 不正"
        else:
            assert "year" not in c, f"{c['id']}: 非日記章段が year を持つ"


# ---- T-007: 史実年表の構造とアンカー(SPEC §4) ----
@pytest.mark.unit
def test_t007_events(events):
    years = [e["year"] for e in events]
    assert years == sorted(years), "events が年昇順でない"
    for e in events:
        assert e["tone"] in ("bright", "neutral", "dark"), f"{e['id']}: tone 不正"
        assert e.get("label") and e.get("detail")
    labels = "".join(e["label"] + e["detail"] for e in events)
    # アンカー事件: 長徳の変(996)と定子崩御(1000)。通説年は概説書レベルで安定
    assert any(e["year"] == 996 and "長徳の変" in e["label"] for e in events)
    assert any(e["year"] == 1000 and "崩御" in labels and "定子" in e["label"] + e["detail"] for e in events if e["year"] == 1000)


# ---- T-008: koyomi タグの語彙と根拠 ----
@pytest.mark.unit
def test_t008_koyomi_vocab(chapters):
    seasons = {"haru", "natsu", "aki", "fuyu", "tsuji"}
    times = {"akatsuki", "akebono", "tsutomete", "hiru", "yugure", "yoru"}
    for c in chapters:
        for k in c.get("koyomi", []):
            assert k["season"] in seasons, f"{c['id']}: season {k['season']} 語彙外"
            assert k["time"] in times, f"{c['id']}: time {k['time']} 語彙外"
            assert k.get("evidence"), f"{c['id']}: koyomi evidence 空"
    # 初段は四季 4 タグ(原文の構造が出所)
    shodan = next(c for c in chapters if c["id"] == "haru-akebono")
    assert {k["season"] for k in shodan["koyomi"]} == {"haru", "natsu", "aki", "fuyu"}


# ---- T-009: 本文の非空 ----
@pytest.mark.unit
def test_t009_texts_nonempty(chapters, items_doc):
    for c in chapters:
        assert c["excerpt"].strip(), f"{c['id']}: excerpt 空"
    for i in items_doc["items"]:
        assert i["text"].strip(), f"{i['id']}: text 空"
        assert i["modern"].strip(), f"{i['id']}: modern 空"


# ---- T-010: タグ語彙の整合 ----
@pytest.mark.integration
def test_t010_tag_vocab(chapters, emotion_tags):
    vocab = set(emotion_tags)
    for c in chapters:
        for t in c["tags"]:
            assert t in vocab, f"{c['id']}: タグ {t} が emotion_tags.json に無い"


# ---- T-013: 段番号の非保持(N-02) ----
@pytest.mark.unit
def test_t013_no_dan_number(chapters):
    for c in chapters:
        for key in c:
            assert key not in ("dan", "dan_no", "number", "段"), f"{c['id']}: 段番号系フィールド {key} を保持している"
