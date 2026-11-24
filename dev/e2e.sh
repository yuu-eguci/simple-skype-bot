#!/bin/sh
# Docker のデモ環境で、発言の追加から返答の受信までを確認します。
# 使い方: sh dev/e2e.sh (リポジトリ直下で実行します。終了時にコンテナとデモ用ボリュームを削除します)
set -eu

cleanup() {
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
  echo "E2E 失敗: $1" >&2
  docker compose logs >&2 || true
  exit 1
}

docker compose up --build -d --wait

# Bot が監視を開始するまで待ちます。
i=0
until docker compose logs bot | grep -q 'main.db の監視を開始しました。'; do
  i=$((i + 1))
  [ "$i" -le 30 ] || fail 'Bot が監視を開始しませんでした。'
  sleep 1
done
# 起動時刻と同じ秒の発言は対象外のため、1 秒以上待ってから発言します。
sleep 2

docker compose exec -T fake-skype python fake_skype.py say 'Hello, bot'
docker compose exec -T fake-skype python fake_skype.py say 'no keyword here'
docker compose exec -T fake-skype python fake_skype.py say 'BYE!'

expected='["BOT: hi.", "BOT: take care."]'
i=0
until [ "$(docker compose exec -T fake-skype python fake_skype.py received)" = "$expected" ]; do
  i=$((i + 1))
  [ "$i" -le 20 ] || fail "返答が期待どおりではありません: $(docker compose exec -T fake-skype python fake_skype.py received)"
  sleep 1
done

# Bot は main.db を読み取り専用でマウントしているため、書き込めないことを確認します。
if docker compose exec -T bot sh -c 'touch /skype/write-test' 2>/dev/null; then
  fail 'Bot のコンテナから main.db のディレクトリに書き込めてしまいます。'
fi

echo 'E2E 成功: 期待どおりの返答を受信しました。'
