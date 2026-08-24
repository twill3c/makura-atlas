# TEST_SPEC.md — makura-atlas

<!-- scaffold template v1.12.0 から展開(2026-08-24) -->

## 実行規約

- `pytest -x -q` を stage 3–5 の判定に使用。マーカー: `unit` / `integration` / `validation`
- 本プロジェクトの実装は静的サイト(JS)だが、データ層(web/data/*.json)とページ骨格の
  検証は pytest で行う(フリート共通のゲート経路を保つため)
- フィクスチャ更新は専用コミット(`test: update fixtures`)で行い、理由をループログに記す

## 期待値の出所(HC-016)

| 出所 | 書き方 |
|---|---|
| SPEC の条項 | 条項 ID を書く。**SPEC の保証粒度を超える期待値を書かない** |
| 外部権威(公表値・規格・検証データ) | 出典と取得日をフィクスチャの先頭に書く |
| 実測 | **実測日と実測値**をコメントに残す |

件数・行数は原則定数で書かず、**集合の一致・取りこぼしの不在**という不変量で書く。
例外は SPEC が仕様定数として明記する値のみ(章段数 44 = F-01)。

## オラクルの出所

| フィクスチャ | 出所 | 性格 |
|---|---|---|
| web/data/chapters.json | 『枕草子』本文(編者採録)。v/a は編者の解釈値 | 解釈データ。範囲・enum・構造の不変量のみ検証し、値の当否は検証しない(SPEC §5) |
| web/data/items.json | 類聚章段の項目(編者採録・現代語訳) | 同上。被覆集合の一致を不変量で検証 |
| web/data/events.json | 中関白家関連の史実(道隆薨去・長徳の変・定子崩御 等の通説年) | 外部権威(概説書の通説年)。年昇順とアンカー事件の存在のみ検証 |
| 初段の koyomi 4 タグ | 「春はあけぼの…夏は夜…秋は夕暮…冬はつとめて」という原文の構造 | 原文そのものがオラクル |

## ケース一覧

| ID | 対応要求 | ケース | 期待 |
|---|---|---|---|
| T-001 | F-01 | chapters.json の章段数 | ちょうど 44(SPEC F-01 の仕様定数) |
| T-002 | F-01 | 章段の必須フィールドと id 一意性 | id/title/type/v/a/excerpt/tags が全件存在し、id に重複が無い |
| T-003 | F-01 | v/a の範囲と型 enum | v,a ∈ [-1,1]、type ∈ {zuiso, ruiju, nikki} |
| T-004 | F-04 | 項目の参照整合 | 全 item の chapId が実在し、その章段は type=ruiju。item の id 一意・v/a 範囲内 |
| T-005 | F-04 | 解体対象の被覆(不変量) | declared 集合 = 項目が実在する章段集合(差集合が両方向とも空) |
| T-006 | F-05 | 日記章段の年次フィールド | type=nikki ⇔ year を持つ。year ∈ [990,1001]、year_label/dating_basis 非空、dating_conf ∈ {high,mid,low} |
| T-007 | F-05 | 史実年表の構造 | events.json が年昇順、tone ∈ {bright,neutral,dark}。長徳の変(996)と定子崩御(1000)を含む(SPEC §4 アンカー) |
| T-008 | F-06 | koyomi タグの語彙と根拠 | season ∈ {haru,natsu,aki,fuyu,tsuji}、time ∈ {akatsuki,akebono,tsutomete,hiru,yugure,yoru}、evidence 非空。初段は四季 4 タグ(原文構造が出所) |
| T-009 | F-01/F-04 | 本文の非空 | 全章段の excerpt、全項目の text/modern が非空 |
| T-010 | F-03 | タグ語彙の整合 | 章段 tags はすべて語彙表 emotion_tags.json に含まれる |
| T-011 | F-08/N-01 | ページ骨格 | index.html に .app-footer 帯、MIT/GitHub/歩き方/設計図/App Menu のリンク文字列、data/*.json への参照が存在 |
| T-012 | F-07 | 縦書き指定 | style.css に writing-mode: vertical-rl と明朝系 font-family 指定が存在 |
| T-013 | N-02 | 段番号の非保持 | 章段レコードに dan/番号系フィールドが存在しない |
