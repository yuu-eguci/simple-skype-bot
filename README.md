SimpleSkypeBot
===

最小構成の Skype Bot です。

## 概要

`WatchDog` クラスが Skype (クラシック版) のデータベース `main.db` を監視し、更新があると `SimpleSkypeBot` を呼び出します。
`SimpleSkypeBot` クラスは新しい発言の内容を調べ、設定したキーワードを含む発言に対応する返答を Skype for Web の HTTP エンドポイントへ送信します。

- キーワードと返答の組み合わせは `SimpleSkypeBot.py` の `PATTERNS` で設定します。
- キーワードは大文字と小文字を区別せずに判定します。
- 反応するのは Bot の起動後に追加された発言のみで、同じ発言には一度だけ反応します。
- `main.db` は読み取り専用で開き、変更しません。
- 返答がいずれかのキーワードを含む設定の場合は、Bot が自分の返答に反応し続けてしまうため、起動時にエラーとして終了します。
- 送信に失敗した場合はエラーをログに出力し、監視を続けます。ログに URL やトークンは出力しません。

## 現在の状況

- Microsoft の一般向け Skype は 2025 年 5 月 5 日に提供を終了しました ([Microsoft サポート](https://support.microsoft.com/en-us/skype/skype-is-retiring-in-may-2025-what-you-need-to-know))。
  そのため、実際の Skype との接続は現在確認できません。
- このリポジトリで再現・検証できるのは、手元の SQLite データベースと HTTP エンドポイントを使った動作のみです。

## 必要なもの

- Docker (Docker Compose を含みます)

ホストに Python などの言語ランタイムをインストールする必要はありません。

## 設定

設定はすべて環境変数で行います。トークンなどの秘密情報をソースコードやリポジトリに書かないでください。

| 環境変数 | 説明 |
| --- | --- |
| `SKYPE_DB_DIR` | `main.db` があるディレクトリのパスです (コンテナ内のパス)。 |
| `SKYPE_URL` | 返答の送信先 URL です。 |
| `SKYPE_TOKEN` | 送信時に `RegistrationToken` ヘッダーへ付与するトークンです。 |
| `SKYPE_ALLOW_HTTP` | 省略可能です。`1` を指定した場合のみ `http://` の `SKYPE_URL` を許可します。トークンが平文で送信されるため、ローカルでの検証以外では使用しないでください。 |

`SKYPE_URL` は通常 `https://` で始まる URL のみ受け付けます。

## 起動方法

`docker compose` の `bot` サービスは、ホストの `SKYPE_HOST_DB_DIR` を読み取り専用で `/skype` にマウントして起動します。

```sh
export SKYPE_HOST_DB_DIR="/path/to/skype/skypeId"
export SKYPE_URL="https://..."
export SKYPE_TOKEN="..."
docker compose up --build bot
```

必要な環境変数が設定されていない場合や値が不正な場合は、環境変数名と理由を表示して終了します (値そのものは表示しません)。

## 開発

テストと lint は Docker 上で実行します。

```sh
docker compose run --build --rm dev pytest
docker compose run --build --rm dev ruff check .
docker compose run --build --rm dev ruff format --check .
```

GitHub Actions でも同じコマンドを実行しています。

## 参考: 実 Skype 環境での設定値の取得方法

Skype の提供終了前に使用していた手順です。現在は Skype for Web が利用できないため、この手順は実行できません。

### `SKYPE_DB_DIR` に対応するホスト側のディレクトリ

    Windows - C:/Users/username/AppData/Roaming/Skype/skypeId
    Mac     - /Users/username/Library/Application Support/Skype/skypeId

### `SKYPE_URL`

Chrome で Skype for Web を開き、F12 キーで開発者ツールを開いて Network タブを表示します。
Bot を使用したいチャットで何か発言すると Message という項目が 2 つ表示されますので、画像の赤い印の付いた方を選択します。

![2](media/SKYPEBOT_2.jpg)

Request URL の値を `SKYPE_URL` に設定します。

![3](media/SKYPEBOT_3.jpg)

### `SKYPE_TOKEN`

Request URL から下へスクロールし、`RegistrationToken` の値を `SKYPE_TOKEN` に設定します。

![4](media/SKYPEBOT_4.jpg)
