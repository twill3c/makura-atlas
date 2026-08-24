# T-011, T-012 — ページ骨格ゲート(TEST_SPEC.md にトレース)
#
# 期待値の出所(HC-016):
# - フッタの必須リンク文字列は SPEC F-08(saijiki-lens AppFooter と同書式)の条項
# - vertical-rl / 明朝は SPEC F-07 の条項

from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"


@pytest.fixture(scope="module")
def index_html():
    return (WEB / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def style_css():
    return (WEB / "style.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_js():
    return (WEB / "app.js").read_text(encoding="utf-8")


# ---- T-011: ページ骨格とフッタ(F-08 / N-01) ----
@pytest.mark.validation
def test_t011_footer_and_skeleton(index_html, app_js):
    assert 'class="app-footer"' in index_html, "下部固定フッタ帯が無い"
    for required in ("MIT License", "GitHub", "歩き方", "設計図", "App Menu", "坂田哲朗"):
        assert required in index_html, f"フッタ必須リンク文字列 {required} が無い"
    # 4 ビューのタブが存在する(F-02/F-04/F-05/F-06)
    for view in ("座標", "解体", "沈黙", "升目"):
        assert view in index_html, f"ビュー {view} のタブが無い"
    # データは JSON から読む(N-02: UI に集計済み定数を埋め込まない)
    for data_file in ("data/chapters.json", "data/items.json", "data/events.json", "data/emotion_tags.json"):
        assert data_file in app_js, f"{data_file} への参照が無い"


# ---- T-012: 縦書きと書体レイヤ(F-07) ----
@pytest.mark.validation
def test_t012_vertical_writing(style_css):
    assert "vertical-rl" in style_css, "原文の縦書き指定(writing-mode: vertical-rl)が無い"
    assert ("明朝" in style_css) or ("Mincho" in style_css) or ("Serif" in style_css), "原文の明朝系 font-family 指定が無い"
    assert "app-footer" in style_css, "フッタ帯のスタイルが無い"
    assert "position: fixed" in style_css, "フッタの固定指定が無い"
