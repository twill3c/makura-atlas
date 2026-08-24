## 概要

<!-- 何を・なぜ。対象の要求 ID / ループ ID を明記 -->

- 要求: F-xx / 対象ループ: loop_xxx

## チェックリスト

- [ ] 全テスト合格(`pytest -x -q`)
- [ ] ループログ validate 合格
- [ ] SPEC/docs と実装の乖離なし(stage 6 実施済み)
- [ ] 差分 500 行以内(超える場合は分割 PR)
- [ ] 失敗があれば FAILURE_TAXONOMY コードで記録済み
