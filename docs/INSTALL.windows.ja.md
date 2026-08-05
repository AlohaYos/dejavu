# Windows での dejavu インストール

dejavu は Windows でも動きます（コードは実質クロスプラットフォームな Python です）。ただし
[README](../README.ja.md) にある Homebrew の1行インストールは macOS/Linux 専用なので、Windows
ではソースから入れます。それ以外（Claude デスクトップから使えるようにする、案件フォルダに導入する、
Obsidian、意識して言ういくつかの言葉）は README のままで変わりません。

Windows 11 Pro / Python 3.10 以降で確認しています。

## 1. 事前準備

- **Python 3.10 以降。** <https://www.python.org/downloads/> から入れ、インストーラで
  *「Add python.exe to PATH」* にチェックを入れてください。`python --version`（または `py --version`）
  で確認できます。
- **git。** <https://git-scm.com/download/win> から、または `winget install Git.Git`。

## 2. dejavu を入れる

まずリポジトリを clone します。

```powershell
git clone https://github.com/AlohaYos/dejavu.git
cd dejavu
```

**推奨: pipx。** pipx は `dejavu` コマンドを隔離環境に入れ、そのランチャを PATH に載せてくれるので、
「command not found」の多くを未然に防げます。

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
pipx install .
```

`ensurepath` の後は、PATH を反映させるためにシェルを開き直してください。

**代替: pip（editable）。** 更新が楽（あとで `git pull` するだけ）ですが、console script が Python の
`Scripts` フォルダに入り、そこが全シェルの PATH に載っているとは限りません。`dejavu` が「見つからない」
場合は [§4](#4-dejavu-が見つからないとき) を参照してください。

```powershell
pip install -e .
```

動作確認:

```powershell
dejavu --help
```

続けて、Claude に使い方を教えます（README の2行目と同じ）。

```powershell
dejavu init --global
```

## 3. Claude デスクトップ / Cowork に MCP サーバーを登録する

macOS では `dejavu install-mcp` が Claude デスクトップの設定ファイルを自動で見つけます。Windows では
その場所が違うため、`--config` で明示的に指定してください。

```powershell
dejavu install-mcp --config "$env:APPDATA\Claude\claude_desktop_config.json"
```

このパスは通常 `C:\Users\<ユーザー名>\AppData\Roaming\Claude\claude_desktop_config.json` です。
登録後は Claude デスクトップを再起動すると読み込まれます。

> Claude Code（CLI）で使いたい場合は、そちらに登録します（設定パスは不要）。
>
> ```powershell
> claude mcp add --scope user dejavu -- dejavu mcp
> ```

## 4. `dejavu` が見つからないとき

`pip` 導入後の `dejavu: command not found` は、ほぼ必ず console script（`dejavu.exe`）が入った
`Scripts` フォルダが、今のシェルの PATH に含まれていないことが原因です。これが一番効いてくるのが
**Git Bash**、つまり **Claude Code** です（Claude Code はシェルコマンドを Git Bash 経由で実行します）。
**Git Bash の PATH は Windows の PATH とは別物**なので、Windows からは見える `Scripts` フォルダが
Git Bash からは見えないことがあります（PATH を編集しても、反映されるのはその後に起動したシェルだけ）。

次のどれか一つで直ります（確実な順）。

- **`py` ランチャを使う。** `py.exe` は `C:\Windows` にあり、どのシェルの PATH にも載っているので、
  PATH をいじらずどこからでも動きます。

  ```bash
  py -m dejavu resume
  ```

- **pipx で入れる**（§2）。シェルを開き直せば、ランチャが PATH に載った状態になります。

- **PATH 上のフォルダに薄いラッパーを置く。** エージェント（Git Bash 経由）で使うなら、これが最も
  堅牢です。短く同一のコマンド文字列にできます。`~/bin/dejavu` を作成（`~/bin` は Git Bash の PATH 上）:

  ```bash
  #!/usr/bin/env bash
  exec py -m dejavu "$@"
  ```

- **Scripts フォルダを PATH に追加する。** `pip show -f dejavu` で `dejavu.exe` の場所を調べ、その
  フォルダを PATH に足してシェルを再起動します。

> **Claude Code を使う場合。** `dejavu`（または `py -m dejavu`）が短く同一のコマンドに定まったら、
> 許可ルールを1本足しておくと毎回プロンプトが出ません。プロジェクトの `.claude/settings.json` に:
>
> ```json
> "Bash(dejavu:*)"
> ```
>
> 避けたいのは、毎回中身の違う `powershell -Command "..."` ワンライナーで包むこと。文字列が毎回違うと
> 前方一致の許可モデルで束ねられず、許可プロンプトが氾濫します。

> **「文字化け」について。** 見つからない `dejavu` を探している途中で日本語が化けて見えても、それは
> ほぼ **PowerShell や cmd 自身が返した cp932 のエラー文**を Git Bash が UTF-8 として読んだものであり、
> dejavu の出力ではありません。dejavu は自分のストリームを UTF-8 に強制する（§5）ので、cp932 コンソール
> でも出力は正しく出ます。

## 5. 補足と既知の制限

- **UTF-8 コンソール — 自動で対応済み。** 日本語版 Windows は cp932 コードページを使い、dejavu の
  `✓`/`⚠` を出力できず、ほぼ全コマンドが落ちてしまいます（`dejavu mcp` の JSON-RPC も壊れます）。
  dejavu は起動時に自分のストリームを UTF-8 に強制します（`cli.py` の `_force_utf8_streams`）ので、
  コンソールのコードページを自分で変える必要はなく、`PYTHONUTF8=1` も不要です。
- **Obsidian の同期判定。** 書き込みモードの自動判定は macOS の同期パス（iCloud / CloudStorage）を
  見ています。Windows で vault を同期フォルダ（OneDrive・Dropbox・iCloud など）に置いている場合は、
  同期の途中でファイルが書き換わらないよう append-only を明示してください。

  ```powershell
  dejavu config write_mode append-only
  ```

  実際に使われる書き込みモードは `dejavu obsidian doctor` で確認できます。
- **実機での検証。** UTF-8 出力は Windows 11 で実証済みです。残りの Windows 固有の経路はユニット
  テストで押さえています。日常的な利用はまだ検証中なので、おかしな挙動があれば報告してください。
