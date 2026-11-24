"""SimpleSkypeBot

最小構成の Skype Bot です。
WatchDog クラスが Skype の DB を監視し、更新があると SimpleSkypeBot を呼び出します。
SimpleSkypeBot クラスは発言の内容を調べ、対応する返答を Skype へ送信します。
設定値は環境変数 SKYPE_DB_DIR, SKYPE_URL, SKYPE_TOKEN から読み込みます。
"""

import logging
import os
import random
import signal
import sqlite3
import sys
import time
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

# key を含む発言に反応し、value を返答として送信します。
PATTERNS = {
    'how are you': 'BOT: so fine.',
    'who are you': 'BOT: i am bot.',
    'hello': 'BOT: hi.',
    'bye': 'BOT: take care.',
}

# Skype for Web へ送信するリクエストヘッダーです。
# Host / Content-Type / 接続関連のヘッダーは requests が URL と本文から設定します。
HEADERS = {
    'Accept': 'application/json, text/javascript',
    'Accept-Language': 'ja,en-US;q=0.8,en;q=0.6',
    'BehaviorOverride': 'redirectAs404',
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'ClientInfo': (
        'os=Windows; osVer=7; proc=Win32; lcid=en-us;'
        ' deviceType=1; country=n/a; clientName=skype.com;'
        ' clientVer=908/1.42.0.98//skype.com'
    ),
    'ContextId': 'tcid=146372019467711519',
    'Expires': '0',
    'Origin': 'https://web.skype.com',
    'Pragma': 'no-cache',
    'Referer': 'https://web.skype.com/ja/',
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 6.1)'
        ' AppleWebKit/537.36 (KHTML, like Gecko)'
        ' Chrome/50.0.2661.102 Safari/537.36'
    ),
}

# HTTP 送信のタイムアウト (秒) です。
REQUEST_TIMEOUT_SECONDS = 10
# main.db の読み込みに失敗した場合の試行回数と待機時間 (秒) です。
MAX_DB_ATTEMPTS = 3
DB_RETRY_DELAY_SECONDS = 0.5


class ConfigError(Exception):
    """設定値が不足している、または不正な場合の例外です。"""


@dataclass(frozen=True)
class Config:
    """Bot の設定値です。

    db_dir: Skype の main.db があるディレクトリのパスです。
    url: Skype for Web の送信先 URL です。
    token: 送信時に RegistrationToken ヘッダーへ付与するトークンです。
    """

    db_dir: str
    url: str
    token: str


def load_config(environ: Mapping[str, str]) -> Config:
    """環境変数から設定値を読み込みます。値は秘密情報を含むため、エラーには名前だけを含めます。"""
    names = {'db_dir': 'SKYPE_DB_DIR', 'url': 'SKYPE_URL', 'token': 'SKYPE_TOKEN'}
    missing = [name for name in names.values() if not environ.get(name)]
    if missing:
        raise ConfigError('環境変数が設定されていません: ' + ', '.join(missing))
    config = Config(**{field: environ[name] for field, name in names.items()})
    # トークンを平文で送信しないよう、http:// は明示的に許可された場合のみ受け付けます。
    allowed_schemes = {'https', 'http'} if environ.get('SKYPE_ALLOW_HTTP') == '1' else {'https'}
    if urlsplit(config.url).scheme not in allowed_schemes:
        raise ConfigError(
            'SKYPE_URL には https:// で始まる URL を指定してください'
            ' (ローカルでの検証時のみ SKYPE_ALLOW_HTTP=1 で http:// を許可できます)。'
        )
    return config


def validate_patterns(patterns: Mapping[str, str]) -> None:
    """返答がキーワードを含むと Bot が自分の返答に反応し続けるため、その設定を拒否します。"""
    for key in patterns:
        for reply in patterns.values():
            if key.casefold() in reply.casefold():
                raise ConfigError(
                    f'返答 {reply!r} がキーワード {key!r} を含むため、'
                    'Bot が自分の返答に反応し続けてしまいます。PATTERNS を見直してください。'
                )


class SimpleSkypeBot:
    """main.db から発言の内容を取得し、対応する返答を Skype へ送信します。"""

    def __init__(
        self, config, session=None, start_timestamp=None, retry_delay=DB_RETRY_DELAY_SECONDS
    ):
        self.config = config
        self.session = session if session is not None else requests.Session()
        # BOT 起動時のタイムスタンプです。これより後の発言にのみ反応します。
        self.start_timestamp = (
            start_timestamp if start_timestamp is not None else round(time.time())
        )
        self.retry_delay = retry_delay
        # 処理済みの発言 ID の最大値です。これより大きい ID の発言のみを取得します。
        self.last_id = 0

    def main(self):
        """新しい発言を取得し、キーワードを含む発言に返答します。"""
        records = self.selectRecordListWithRetry()
        for record in records:
            # 返答の有無にかかわらず処理済みとし、同じ発言を再度処理しないようにします。
            self.last_id = max(self.last_id, record['id'])
            reply = self.getReply(record['body_xml'])
            if reply is not None:
                self.sendSkype(reply)

    def selectRecordListWithRetry(self):
        """main.db の読み込みを、失敗時は回数を限って再試行します。"""
        # Skype の書き込み中などに sqlite3.OperationalError が発生することがあります。
        # 再試行しても失敗する場合は今回の処理を見送り、次の変更検知時に改めて読み込みます。
        for attempt in range(1, MAX_DB_ATTEMPTS + 1):
            try:
                return self.selectRecordList()
            except sqlite3.OperationalError as error:
                logger.warning(
                    'main.db の読み込みに失敗しました (%d/%d 回目): %s',
                    attempt,
                    MAX_DB_ATTEMPTS,
                    error,
                )
                if attempt < MAX_DB_ATTEMPTS:
                    time.sleep(self.retry_delay)
        return []

    def connect(self):
        """main.db を読み取り専用で開きます。"""
        uri = Path(self.config.db_dir, 'main.db').absolute().as_uri() + '?mode=ro'
        return sqlite3.connect(uri, uri=True)

    def selectRecordList(self):
        """BOT 起動後に追加された未処理の発言を ID 順に取得します。"""
        # connection を使い回すとスレッドをまたいでエラーになるため、毎回作ります。
        with closing(self.connect()) as connection:
            rows = connection.execute(
                'SELECT id, body_xml FROM Messages WHERE timestamp > ? AND id > ? ORDER BY id',
                (self.start_timestamp, self.last_id),
            ).fetchall()
        return [{'id': row[0], 'body_xml': row[1]} for row in rows]

    def getReply(self, body_xml):
        """body_xml の内容に対応する返答を返します。該当しない場合は None を返します。"""
        if not body_xml:
            return None
        body = body_xml.casefold()
        for key, value in PATTERNS.items():
            if key.casefold() in body:
                return value
        return None

    def sendSkype(self, reply):
        """Skype for Web へ返答を送信します。送信できた場合は True を返します。"""
        payload = {
            'content': reply,
            'clientmessageid': str(random.randint(1000000000000, 9999999999999)),  # noqa: S311
            'messagetype': 'RichText',
            'contenttype': 'text',
        }
        headers = {**HEADERS, 'RegistrationToken': self.config.token}
        try:
            response = self.session.post(
                self.config.url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
            )
            response.raise_for_status()
        except requests.RequestException as error:
            # 例外のメッセージには URL が含まれるため、種類とステータスコードのみを出力します。
            status = getattr(error.response, 'status_code', None)
            logger.error('返答の送信に失敗しました: %s (status=%s)', type(error).__name__, status)
            return False
        logger.info('返答を送信しました: %s', reply)
        return True


class WatchDog(FileSystemEventHandler):
    """main.db の変更を検知すると、SimpleSkypeBot の main メソッドを実行します。"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    def on_modified(self, event):
        """main.db が変更された (Skype で発言があった) 場合に Bot を動かします。"""
        if os.path.basename(event.src_path) == 'main.db':
            self.bot.main()


def main():
    """環境変数から設定を読み込み、main.db の監視を開始します。"""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        config = load_config(os.environ)
        validate_patterns(PATTERNS)
    except ConfigError as error:
        logger.error('%s', error)
        return 1
    bot = SimpleSkypeBot(config)
    observer = Observer()
    observer.schedule(WatchDog(bot), config.db_dir, recursive=True)
    # docker stop などで SIGTERM を受け取った場合も監視を正常に終了します。
    signal.signal(signal.SIGTERM, lambda signum, frame: observer.stop())
    observer.start()
    logger.info('main.db の監視を開始しました。')
    try:
        observer.join()
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
    logger.info('main.db の監視を終了しました。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
