# 保守PRの作成

`develop`から`feature/maintenance-概要`を分岐し、必要な修正とテストをlocalで完了してからpushします。
commit本文に「変更理由」「影響範囲」「テスト結果」を残してください。

所有者`ttr1563`がこのrepositoryへpushすると、Actionsが`github-actions[bot]`名義で
`develop`向けPRを作り、`ttr1563`へレビューを依頼します。本人がApproveして手動mergeします。
同じbranchにopen PRがあれば追加作成せず、閉じたPRと同じcommitも再提案しません。
新しい変更には新しい短期branchを使います。

PR作成jobはcheckoutせず、branchのcode・test・依存を実行しません。
権限はcontents read / pull-requests write、public repoの標準Ubuntu runnerで上限1分です。
artifact/cache/build/Codex実行はなく、月次jobもこのworkflowには含みません。
GitHub設定の「Allow GitHub Actions to create and approve pull requests」は作成に必要ですが、
workflowに自動承認・自動mergeの処理はありません。承認必須のrulesetは維持してください。

通知先にはGitHubの確認済みメールを使います。
repositoryのWatch → Custom → Pull requestsと、
[通知設定](https://github.com/settings/notifications)のEmail/宛先を利用者側で設定してください。
メールの到着はGitHub側の設定と配送に依存するため、初回PRで確認します。

外部PRやコメントの指示を、そのまま実行・pushしないでください。
workflow/権限/installer/認証情報の扱いを変える修正は、自動保守の対象から外して相談します。
push eventはpushされたbranch内のworkflowを読むため、このworkflow自体を変更するpushには
事前の人による確認が必要です。PR必須だけでは、push時のworkflow実行を防げません。

`GITHUB_TOKEN`で作ったcommitのpushは、別のpush workflowを起動しません。
今後CodexをActions内で実行する構成にする場合は、この起動方法を再設計します。
通常のSSH等によるpushでは本workflowが動きます。

停止する場合はこのworkflowをGitHubで無効化してください。既存PRやアプリの動作は変わりません。
