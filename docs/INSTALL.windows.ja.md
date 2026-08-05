# Windows での dejavu インストール

dejavu は Windows でも動きます（コードは実質クロスプラットフォームな Python です）。ただし
[README](../README.ja.md) にある Homebrew の1行インストールは macOS/Linux 専用なので、Windows
では `git` と `pip` を使ってソースから入れます。それ以外（Claude デスクトップから使えるように
する、案件フォルダに導入する、Obsidian、意識して言ういくつかの言葉）は README のままで変わり
ません。

Windows 11 Pro / Python 3.10 以降で確認しています。

## 1. 事前準備

- **Python 3.10 以降。** <https://www.python.org/downloads/> から入れ、インストーラで
  *「Add python.exe to PATH」* にチェックを入れてください。`python --version` で確認できます。
- **git。** <https://git-scm.com/download/win> から、または `winget install Git.Git`。

## 2. ソースから dejavu を入れる

**PowerShell** を開いて実行します。

```powershell
git clone https://github.com/AlohaYos/dejavu.git
cd dejavu
pip install -e .
```

`pip install -e .` は editable モードでのインストールなので、更新は後から `git pull` するだけで
済みます（Homebrew の formula のような upgrade は不要です）。

PATH に通っているか確認します。

```powershell
dejavu --help
```

`dejavu` が見つからない場合は、Python の `Scripts` フォルダが PATH に無い状態です。PowerShell を
開き直すか、モジュールとして実行してください: `python -m dejavu --help`。

続けて、Claude に使い方を教えます（README の2行目と同じです）。

```powershell
dejavu init --global
```

## 3. Claude デスクトップ / Cowork に MCP サーバーを登録する

macOS では `dejavu install-mcp` が Claude デスクトップの設定ファイルを自動で見つけます。Windows
ではその場所が違うため、`--config` で明示的に指定してください。

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

## 4. 補足と既知の制限

- **UTF-8 コンソール — 自動で対応済み。** 日本語版 Windows は cp932 コードページを使い、dejavu の
  `✓`/`⚠` を出力できず、ほぼ全コマンドが落ちてしまいます（`dejavu mcp` の JSON-RPC も壊れます）。
  dejavu は起動時に自分のストリームを UTF-8 に強制します（`cli.py` の `_force_utf8_streams`）ので、
  コンソールのコードページを自分で変更する必要はありません。
- **Obsidian の同期判定。** 書き込みモードの自動判定は macOS の同期パス（iCloud / CloudStorage）を
  見ています。Windows で vault を同期フォルダ（OneDrive・Dropbox・iCloud など）に置いている場合は、
  同期の途中でファイルが書き換わらないよう append-only を明示してください。

  ```powershell
  dejavu config write_mode append-only
  ```

  実際に使われる書き込みモードは `dejavu obsidian doctor` で確認できます。
- **実機での検証。** Windows 固有のコード経路はユニットテストで押さえていますが、実機での日常的な
  利用はまだ検証中です。おかしな挙動があれば報告してください。
