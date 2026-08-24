# makura-atlas — 枕草子アトラス

『枕草子』44 章段を「快‐不快 × 心の動き」の二軸平面に置く散布図アプリを土台に、
三つの拡張を一体化した静的サイト。

| ビュー | 内容 |
|---|---|
| 座標 | 44 章段の散布図。型(随想/類聚/日記)で色分け、情緒語 20 語で横断検索、縦書き原文パネル |
| 解体 | 類聚章段 10 を項目単位(63 項目・現代語訳つき)に分解し、同じ平面に散らす |
| 沈黙 | 日記章段 12 を推定年に置き、中関白家の史実(990–1001)の明暗帯に重ねる。暗転後も点は快側に留まる——書かれなかったことの可視化 |
| 升目 | 季節(春夏秋冬+通季)× 時刻(暁〜夜)の言及を根拠語つきで集計 |

- 本番: https://makura-atlas.vercel.app
- 解説: [枕草子アトラスの歩き方](https://claude.ai/code/artifact/0ec23b1e-9542-4975-a0ac-87e9d2ca0f35) / [枕草子アトラス設計図](https://claude.ai/code/artifact/b17aa0bf-ac26-476d-bd7c-041719a23263)

## 構成

```
web/            配信物(ビルド不要の静的サイト)
  index.html    4 ビュー + 下部固定フッタ(saijiki-lens 準拠)
  app.js        fetch → state → SVG/DOM 描画。集計値はすべて実行時に導出
  style.css     和紙×弁柄の基調。原文は vertical-rl + 明朝、UI はゴシック
  data/         chapters.json(44)/ items.json(63)/ events.json(9)/ emotion_tags.json(20)
tests/          pytest ゲート T-001〜T-013(構造・参照整合・被覆不変量・ページ骨格)
harness/        looplog.py / labelcheck.js(SVG ラベル重なり数検査、HC-M001)/ smoke.js
```

## 設計上の約束

- **座標・比定・升目タグは編者の解釈値。** 根拠をデータのフィールドに明示し、JSON を書き換えれば図全体が追随する
- **段番号は持たせない。** 三巻本・能因本・堺本で振り方が異なるため。章段は諸本で安定な題で呼ぶ
- **件数を決め打ちしない。** テストは集合の一致・取りこぼしの不在という不変量で書く(例外は仕様定数の 44 のみ)

## 開発

```bash
pytest -q                                   # データ・骨格ゲート
python -m http.server 8123 --directory web  # ローカル配信
NODE_PATH=../karakuri-hako/node_modules node harness/smoke.js       # Playwright スモーク
NODE_PATH=../karakuri-hako/node_modules node harness/labelcheck.js  # ラベル重なり数 = 0 検査
```

MIT License © 2026 坂田哲朗
