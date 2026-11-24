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

`docker compose up` で、Bot と Skype 側を模した `fake-skype` サービスが起動します。
`fake-skype` は共有ボリューム上の `main.db` への発言の追加と、Bot からの返答の受信を担当します。
外部のサービスには接続しません。

```sh
docker compose up --build -d --wait
```

別の発言を追加して、Bot の返答を確認します。

```sh
# 発言を追加します (main.db の Messages テーブルに 1 行追加されます)。
docker compose exec fake-skype python fake_skype.py say "Hello, bot"

# fake-skype が受信した返答を表示します。["BOT: hi."] と表示されます。
docker compose exec fake-skype python fake_skype.py received

# Bot のログを確認します。
docker compose logs bot
```

終了するときは、次のコマンドでコンテナとデモ用のボリュームを削除します。

```sh
docker compose down -v
```

上記の一連の動作は `sh dev/e2e.sh` で自動的に確認できます (CI でも実行しています)。

### 実際の Skype 環境で起動する場合 (参考)

Skype の提供終了により、現在は動作を確認できません。
ホストの Skype データディレクトリを読み取り専用でマウントし、環境変数を指定して起動します。

```sh
docker build --target runtime -t simple-skype-bot:runtime .
docker run --rm \
  -e SKYPE_DB_DIR=/skype -e SKYPE_URL -e SKYPE_TOKEN \
  -v "/path/to/skype/skypeId:/skype:ro" \
  simple-skype-bot:runtime
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
