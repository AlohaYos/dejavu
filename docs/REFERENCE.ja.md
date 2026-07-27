# リファレンス

[README.ja.md](../README.ja.md) から外した細かい話をまとめてあります。
普段使う分には読まなくて構いません。

---

## 目次

1. [コマンド一覧](#コマンド一覧)
2. [知識の置き場（スコープ）](#知識の置き場スコープ)
3. [設定ファイル](#設定ファイル)
4. [書き込みモードの判定](#書き込みモードの判定)
5. [ノートの形式](#ノートの形式)
6. [メモ同士の自動リンク（Ollama）](#メモ同士の自動リンクollama)
7. [カテゴリ](#カテゴリ)
8. [知識が古くなったら](#知識が古くなったら)
9. [認証情報は保存されない](#認証情報は保存されない)
10. [チームで共有する](#チームで共有する)
11. [MCP サーバー](#mcp-サーバー)
12. [Claude 自身の記憶機能との共存](#claude-自身の記憶機能との共存)
13. [Xcode で使う](#xcode-で使う)
14. [困ったとき](#困ったとき)

---

## コマンド一覧

Claude がほとんど代わりに実行するので、自分で打つ場面はまれです。

### 導入

| コマンド | 説明 |
| --- | --- |
| `dejavu init` | いまのプロジェクトに導入する |
| `dejavu init --global` | 全プロジェクト共通の指示を `~/.claude/` に入れる（1度きり） |
| `dejavu install-mcp` | MCP サーバーを Claude デスクトップ / Cowork に登録する |
| `dejavu install-mcp --config <path>` | 別のホストの設定ファイルに登録する |

`dejavu init` は何度実行しても安全です。ソースには触れず、`CLAUDE.md` と `.gitignore`
には無い行だけを追記します。

> **バージョンを上げたら `dejavu init` を実行し直してください。**
> `dejavu-triggers.md` は `init` のときに各プロジェクトへコピーされるので、
> 指示が更新されてもプロジェクト側は古いままです。全体版は `dejavu init --global` です。

### 思い出す

| コマンド | 説明 |
| --- | --- |
| `dejavu resume` | 前回の引き継ぎメモを表示する |
| `dejavu recent` | 最近の作業を日付ごとに表示（既定は2日分） |
| `dejavu recent --since today` | 今日の分だけ |
| `dejavu search "<query>"` | プロジェクト → 共有 → vault を横断検索 |
| `dejavu search "<query>" --full` | 本文を省略せずに表示 |
| `dejavu search "<query>" --json` | 機械可読な出力（スコアと検索段も含む） |
| `dejavu list --stale` | 見直しが必要なものを一覧 |
| `dejavu show <uid>` | 1件を全文表示 |
| `dejavu stats` | 件数・カテゴリ内訳・古くなった件数 |

`search` が結果を返さなかったときの終了コードは **2** です。

### 保存する

| コマンド | 説明 |
| --- | --- |
| `dejavu add "<title>" --body -` | 知識を保存（本文は標準入力から） |
| `dejavu add ... --category <cat>` | カテゴリを指定（後述） |
| `dejavu add ... --keywords "a,b,c"` | キーワードを手で選ぶ（5〜10個推奨） |
| `dejavu add ... --status proposed` | 状態を付ける（`proposed` `accepted` `done` `superseded`） |
| `dejavu add ... --scope user` | プロジェクトではなく個人の記憶に保存 |
| `dejavu edit <uid> --append -` | 既存エントリに追記する |
| `dejavu touch <uid>` | 「確認したがまだ正しい」と印を付ける |
| `dejavu rm <uid>` | 削除する |

似たタイトルのエントリがあると `add` は止まります。`--force` で強行できますが、
たいていは `edit --append` のほうが正解です。

### Obsidian

| コマンド | 説明 |
| --- | --- |
| `dejavu obsidian init <vault>` | vault を登録し、フォルダを作り、初回インデックス |
| `dejavu obsidian init <vault> --preset dev` | `Knowledge/` に `API/` `Architecture/` `Patterns/` `Tools/` も作る |
| `dejavu obsidian sync` | 自分でノートを編集したあとに読み直す |
| `dejavu obsidian doctor` | vault のパス・書き込みモードと理由・ノート数 |
| `dejavu obsidian doctor --vault <path>` | 設定を変えずに別の vault を調べる |
| `dejavu obsidian add "<title>" --body -` | `Knowledge/` にノートを作る |
| `dejavu obsidian add ... --category <name>` | `Knowledge/<name>/` に入れる（**そのフォルダが既にある場合のみ**） |
| `dejavu obsidian add ... --tags "a,b"` | frontmatter の `tags` に書く |
| `dejavu obsidian add ... --replace` | 既存ノートの本文を差し替える（同期 vault では拒否） |
| `dejavu research "<title>" --body -` | `Research/<project>/<日付>-<題>.md` に記録する |
| `dejavu research ... --project <name>` | プロジェクト名を明示（既定はカレントのディレクトリ名） |

同じ題のノートが既にあると、`obsidian add` は**複製せずに追記**します。

### 設定

| コマンド | 説明 |
| --- | --- |
| `dejavu config` | いまの設定を全部表示 |
| `dejavu config <key>` | 1つだけ表示 |
| `dejavu config <key> <value>` | 変更して保存する |

どのコマンドにも `--help` が付きます。

---

## 知識の置き場（スコープ）

| スコープ | 実体 | 何が入るか |
| --- | --- | --- |
| **project** | `<repo>/.dejavu/knowledge.db` | このリポジトリ限定の話。ほとんどはここ |
| **user** | `~/.config/dejavu/knowledge.db` | 全プロジェクト共通。vault が無いときの受け皿 |
| **shared** | `<repo>/.dejavu/shared.db` | `docs/knowledge/*.md` のインデックス（読み取り専用） |
| **obsidian** | `~/.config/dejavu/obsidian.db` | vault のインデックス（読み取り専用） |

`shared` と `obsidian` は**インデックスであってデータの置き場ではありません。**
本体は Markdown ファイルで、データベースは消しても `dejavu obsidian sync` で作り直せます。

### どこを検索するか

- `dejavu search` — 4つ全部を横断します
- `dejavu list` / `recent` / `resume` — **project と user だけ**

`resume` は「何をやっていたか」を答えるコマンドなので、vault の数百件を混ぜると
答えが埋もれます。だから意図的に外してあります。

### git worktree

worktree を複数作っても、データベースは**メインの worktree のものが共有されます。**
設定は要りません。worktree ごとに別の記憶ができてしまうと、
「全 worktree で1つの知識ベース」という前提が壊れるためです。

---

## 設定ファイル

プロジェクト側は `<repo>/.dejavu/config.toml`、個人側は `~/.config/dejavu/config.toml` です。
`[obsidian]` は**個人側**にあります。vault はマシンの持ち物で、リポジトリの持ち物ではないからです。

```toml
[stale_days]
context    = 7
plan       = 14
decision   = 30
feature    = 7
convention = 30
note       = 14

[obsidian]
vault         = "~/Documents/MyVault"
include       = ["Knowledge", "UserInfo", "Research"]
knowledge_dir = "Knowledge"
userinfo_dir  = "UserInfo"
research_dir  = "Research"
write_mode    = "auto"       # auto | full | append-only
research      = "findings"   # all | findings | manual
promote       = "ask"        # ask | always | never
```

| キー | 意味 |
| --- | --- |
| `vault` | vault のパス。**未設定なら Obsidian 連携は完全に無効** |
| `include` | インデックスと書き込みの対象フォルダ。ここに無いフォルダは見えません |
| `knowledge_dir` | 汎用知識の置き場 |
| `userinfo_dir` | あなた自身の情報の置き場 |
| `research_dir` | 調査履歴の置き場（この下にプロジェクト別のフォルダができます） |
| `write_mode` | 後述 |
| `research` | 調査履歴をどれだけ残すか |
| `promote` | プロジェクトの知識を vault に上げるか聞くかどうか |

### `research` — 調査履歴の粒度

| 値 | 挙動 |
| --- | --- |
| `all` | 引き継ぎメモも含めて全部 `Research/` に残す |
| `findings` | **再利用できる発見だけ**（既定）。その日の状態だけのメモは残さない |
| `manual` | 頼んだときだけ |

その場かぎりで変えたいときは、サブコマンドの前に付けます：

```bash
dejavu --research all resume
```

### `promote` — vault に上げるか聞くか

| 値 | 挙動 |
| --- | --- |
| `ask` | 汎用的な知識に見えたら4択で聞く（既定） |
| `always` | 聞かずに保存してよい |
| `never` | 提案しない |

`dejavu config promote always` で永続化されます。`ask` に戻すのも同じ形です。

---

## 書き込みモードの判定

同期される vault は、dejavu が書いている最中に別のデバイスから編集されることがあります。
負けたほうは競合コピーになります。追記なら内容は残りますが、本文の書き換えは消えます。

`write_mode = "auto"`（既定）のとき、こう判定します。

| 条件 | 結果 |
| --- | --- |
| vault が `~/Library/Mobile Documents/` の下 | `append-only`（iCloud Drive） |
| vault が `~/Library/CloudStorage/` の下 | `append-only`（Google Drive / OneDrive / Box など） |
| vault が `~/Dropbox` の下 | `append-only` |
| `<vault>/.obsidian/sync.json` がある | `append-only`（Obsidian Sync） |
| どれにも当てはまらない | `full` |

`full` でも、本文を書き換える直前にファイルの更新時刻を確認します。
読んだときから変わっていれば中断します。他のデバイスの編集を踏み潰さないためです。

判定結果と理由は `dejavu obsidian doctor` が表示します。
`write_mode = "full"` または `"append-only"` を書けば自動判定を上書きできます。

---

## ノートの形式

dejavu が作るノートはこうなります。

```markdown
---
category: pattern
tags: [swiftui, layout]
source: dejavu
project: MyApp
created: 2026-07-27
---

# ignoresSafeArea の落とし穴

safeAreaInsets.bottom が 0 になる。
```

| キー | 役割 |
| --- | --- |
| `source: dejavu` | **これが無いノートに dejavu は書き込みません。** 手書きのノートを守る印 |
| `category` | 分類。フォルダに依存しないので、後から組み替えても壊れません |
| `tags` | Obsidian のタグペインと Bases がそのまま拾います |
| `project` | どの案件で得た知識か |
| `created` | 作成日 |

**知らないキーには触りません。** 埋め込みスクリプトが書いた `autolink:` のようなものも、
dejavu がノートに追記したあと、そのまま残ります。frontmatter を作り直すのではなく、
必要な行だけを差し替えているからです。

### フォルダの扱い

`Knowledge/` は最初フラットです。サブフォルダを作れば dejavu はそこに入れますが、
**自分でフォルダを作ることはありません。** vault の構成は人それぞれなので、
dejavu の分類を押し付けない設計です。

コード作業向けの叩き台が欲しければ：

```bash
dejavu obsidian init <vault> --preset dev
# → Knowledge/ に API/ Architecture/ Patterns/ Tools/ を作る
```

---

## メモ同士の自動リンク（Ollama）

**dejavu のコアに AI モデルもネットワーク接続も必要ありません。** 検索は SQLite の
全文検索機能（FTS5）だけで動いています。依存ゼロという性質は、Homebrew の formula に
追加の取得物が一切要らないことに直結しているので、これは意図的に守っている線です。

例外は、**メモ同士を意味の近さで自動リンクする機能**だけです。これは文章の埋め込み
（ベクトル化）を必要とするため、[Ollama](https://ollama.com) のようなローカル AI が要ります。

この機能は**コアには含めず、独立したコマンドとして分離します。** Ollama が入っていなければ
その機能だけが使えず、他には一切影響しません。**入っていなくても、このリファレンスに
書かれている内容はすべて動きます。**

なお Obsidian 自身も手動の `[[リンク]]` とグラフビューを持っているので、
自動リンクが無くても運用は成立します。

---

## カテゴリ

知識は6つのカテゴリのどれかに入ります。Claude が選ぶので、意識する場面はほぼありません。

| カテゴリ | 何が入るか | 例 |
| --- | --- | --- |
| `context` | セッションの引き継ぎメモ | 「移行はマージ済み。次はロールバックのテスト」 |
| `plan` | 後回しにした作業 | 「AppDelegate の警告を直す」 |
| `decision` | 設計判断と**却下した案** | 「SwiftUI ではなく UIKit を選んだ理由は…」 |
| `feature` | コードの動きの理解 | 「`Migration.swift` は3段階で動く」 |
| `convention` | チームの決まりごと | 「ビューモデルは必ず `ViewModel` で終える」 |
| `note` | それ以外 | |

---

## 知識が古くなったら

コードは変わります。コードについてのメモは変わりません。dejavu はそれを前提にしています。

各エントリは「最後に**実際のコードと突き合わせた**のはいつか」を記録しています。
それが古くなると、検索結果に印が付きます。

```
⚠ [a3f01c8b] Migration は3段階で動く (feature) [STALE: 12 days since last check]
```

**古いエントリも結果からは消しません。** 古い知識でも手がかりにはなるので、
捨てるより印を付けるほうが害が少ないからです。Claude は印の付いたものを
現在のコードと突き合わせてから使うように指示されています。

まとめて棚卸ししたいときは「**古くなった知識を見直して**」と言えば、
1件ずつコードと照合して、直すもの・捨てるもの・そのままでよいものを仕分けます。

閾値は `.dejavu/config.toml` の `[stale_days]` で変えられます。

> vault と `docs/knowledge/` のノートには印が付きません。
> ファイルそのものが本体なので、「古くなる」という概念が当てはまらないからです。

---

## 認証情報は保存されない

API キー・トークン・秘密鍵らしき文字列を含むテキストは、保存が拒否されます。
CLI からでも MCP からでも同じ検出器が動きます。

対象：OpenAI / Anthropic の API キー、GitHub トークン、AWS アクセスキー、
Google API キー、Slack トークン、秘密鍵ブロック、Bearer トークン、
URL に埋め込まれた Basic 認証、`api_key = "..."` 形式の代入。

誤検出のときだけ `--force` で通せます。

---

## チームで共有する

`docs/knowledge/*.md` に Markdown を置いてください。git で管理されるので、
プルリクエストでレビューでき、クローンした人にもそのまま届きます。

dejavu は同じ仕組みでこれをインデックスするので、`dejavu search` の結果に
`[shared]` という印で出てきます。

```
    [5eb6c3c6f85a] チーム共通ルール (note) [shared]
       File: docs/knowledge/team-rule.md
```

インデックス（`.dejavu/shared.db`）は `.gitignore` に入ります。
元の Markdown が管理されているので、バイナリをコミットする意味がないからです。

**データベースそのものの共有はまだ実装していません。**
`dejavu export` でエントリを Markdown に書き出す設計はありますが、未実装です
（[BACKLOG.md](BACKLOG.md)）。

---

## MCP サーバー

ターミナルと Xcode のエージェントはデータベースと同じファイルシステムにいるので CLI が使えます。
**Claude デスクトップと Cowork は使えません。** シェルがサンドボックスの中で動いていて、
`~/.config/dejavu/` が見えないからです。それらのホストは MCP サーバーをローカルの
サブプロセスとして起動できるので、そこが唯一の入口になります。

```bash
dejavu install-mcp
```

登録先は `~/Library/Application Support/Claude/claude_desktop_config.json` です。
アプリを再起動すると使えるようになります。

### 提供しているツール

| ツール | 用途 |
| --- | --- |
| `search_knowledge` | 横断検索。`source` でどこから来たか分かる |
| `resume_knowledge` | 前回の引き継ぎメモ |
| `recent_knowledge` | 最近の作業 |
| `add_knowledge` | 保存 |
| `update_knowledge` | 更新・追記 |
| `get_knowledge` | 1件を全文取得 |
| `obsidian_status` | vault が繋がっているか、書き込みモード、設定 |
| `add_obsidian_knowledge` | vault の `Knowledge/` に保存 |
| `add_research` | vault の `Research/<project>/` に記録 |

### どの案件の話か

MCP サーバーはデスクトップアプリから起動されるので、**カレントディレクトリがありません。**
プロジェクトは推測できず、言ってもらうしかありません。案件名を出せば Claude がパスを渡します。

案件を言わなかった場合は、個人の記憶と vault だけが使われます。

### 答えが2つ出たとき

プロジェクト側と vault 側の両方が同じ問いに答えた場合、
`conflict_candidates` として両方が返り、Claude はこう表示します。

```
  ⚠ CONFLICT RISK — the project and the vault both answer this query:
    project   [48f7921e75f4] 認証まわりの設計判断
    obsidian  [0c0cac2bbacf] 認証の共通方針
```

dejavu はどちらが正しいか判定しません。vault 側を間違えると、
その間違いが他の全案件に付いて回るからです。

---

## Claude 自身の記憶機能との共存

Claude Code には、dejavu とは別に2つの記憶の仕組みがあります。
役割が違うので競合しません。ここでは技術的な違いだけを整理します。

| | CLAUDE.md | 自動メモリ | dejavu |
| --- | --- | --- | --- |
| 誰が書くか | あなた | Claude | Claude |
| 置き場所 | 案件内 / `~/.claude/` | `~/.claude/projects/<案件>/memory/` | `.dejavu/` / `~/.config/dejavu/` |
| 読み込み | 毎セッション全文 | `MEMORY.md` の**先頭200行または25KB** | **検索したときだけ** |
| 検索 | なし | なし（Claude がファイルを読む） | FTS5 全文検索＋キーワード |
| 分類 | なし | 自由記述 | カテゴリ・状態・キーワード |
| 鮮度 | なし | なし | `checked_at` と ⚠ STALE |
| 到達範囲 | Claude Code | Claude Code のみ（マシンローカル） | Claude Code / Xcode / チャット / Cowork |
| 認証情報 | 保護なし | 保護なし | 検出して保存を拒否 |

### なぜ dejavu が別に要るのか

自動メモリの `MEMORY.md` は毎セッション読み込まれますが、**先頭200行（または25KB）まで**です。
超えた分は起動時に読まれません。溢れた内容は `debugging.md` のようなトピックファイルに分かれ、
そちらは Claude が必要と判断したときだけ読まれます。

つまり **蓄積量が増えるほど「毎回読まれる枠」の取り合いになり、検索の手段がありません。**
dejavu は逆に、普段は載せず、必要になったときに検索して数件だけ取り出します。
常時消費するのは指示書の数十行だけなので、件数が増えても効き続けます。

### 3つの使い分け

- **CLAUDE.md** — Claude に守らせたいルール。あなたが書く
- **自動メモリ** — Claude が作業中に気づいたこと。放っておけば溜まる
- **dejavu** — 検索して引き出す長期記憶。複数の入り口から使う

`~/.claude/projects/` の自動メモリは `/memory` コマンドで確認・編集できます。

> claude.ai のチャットにも「メモリ」機能がありますが、あれはサーバー側に保存される別物で、
> Claude Code からは見えません。逆に自動メモリも claude.ai からは見えません。

---

## Xcode で使う

Xcode 26.3 以降には Claude Code そのものがエージェントとして組み込まれているので、
`dejavu` を実行できます。プロジェクトの `CLAUDE.md` は普通に読まれるので、
`dejavu init` さえ済んでいれば設定は不要です。

**2つだけ注意点があります。**

**`.dejavu/` を Xcode 16 の synchronized group に入れないでください。**
「buildable folder」はフォルダ内の全ファイルを自動でターゲットに追加します。
リポジトリのルートに置いてある限り安全です。

**`PATH` が引き継がれません。** Xcode はログインシェルの設定（`.zshrc` など）を
読まない環境でエージェントを起動します。`dejavu: command not found` になる場合は、
エージェントに次を実行させて確認してください。

```
echo $PATH
which dejavu
```

`install-mcp` が絶対パス（`/usr/local/bin/dejavu`）を書き込むのはこのためです。

なお `dejavu init --global` が入れる指示は `~/.claude/` にありますが、Xcode は
自前の設定ディレクトリを読みます：

```
~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig/
```

スラッシュコマンドはシンボリックリンクで届きます：

```bash
ln -s ~/.claude/commands ~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig/commands
```

---

## 困ったとき

**指示を更新したのに何も変わらない**
`dejavu init` を各プロジェクトで実行し直してください。`dejavu-triggers.md` は
`init` のときにコピーされるので、バイナリを上げただけでは古いままです。
全体版は `dejavu init --global` です。

**`dejavu obsidian sync` が「何も変わっていない」と言うが、ノートは直したはず**
ファイルの更新時刻とサイズが同じだと変更なしと判断されます。
Obsidian で保存し直してから再実行してください。

**vault のノートが検索に出てこない**
`dejavu obsidian doctor` でフォルダごとの件数を見てください。
0件なら、そのフォルダが `include` に入っていない可能性があります。

```bash
dejavu config include      # 対象フォルダを確認
```

**「このノートは dejavu が書いたものではない」と拒否される**
仕様です。frontmatter に `source: dejavu` が無いノートは保護されています。
どうしても dejavu に管理させたいなら、その行を自分で足してください。

**本文の書き換えが拒否される**
vault が同期フォルダにあります。`dejavu obsidian doctor` が理由を表示します。
追記なら通ります。それでも書き換えたい場合のみ `dejavu config write_mode full` です。

**2文字の日本語で検索できない**
できるはずです。できない場合は不具合なので報告してください。
SQLite の trigram トークナイザは3文字未満にマッチしないので、
dejavu は LIKE による第3段の検索を必ず併用しています。

**プロジェクトから外したい**
`.dejavu/` を消して、`CLAUDE.md` から取り込みの1行を削るだけです。
他には何も触っていません。
