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
from dataclasses import dataclass

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
HEADERS = {
    'Accept': 'application/json, text/javascript',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'ja,en-US;q=0.8,en;q=0.6',
    'BehaviorOverride': 'redirectAs404',
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'ClientInfo': (
        'os=Windows; osVer=7; proc=Win32; lcid=en-us;'
        ' deviceType=1; country=n/a; clientName=skype.com;'
        ' clientVer=908/1.42.0.98//skype.com'
    ),
    'Connection': 'keep-alive',
    'ContextId': 'tcid=146372019467711519',
    'Content-Type': 'application/json',
    'Expires': '0',
    'Host': 'client-s.gateway.messenger.live.com',
    'Origin': 'https://web.skype.com',
    'Pragma': 'no-cache',
    'Referer': 'https://web.skype.com/ja/',
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 6.1)'
        ' AppleWebKit/537.36 (KHTML, like Gecko)'
        ' Chrome/50.0.2661.102 Safari/537.36'
    ),
}


class ConfigError(Exception):
    """設定値が不足している場合の例外です。"""


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
    return Config(**{field: environ[name] for field, name in names.items()})


class SimpleSkypeBot:
    """main.db から発言の内容を取得し、対応する返答を Skype へ送信します。"""

    def __init__(self, config, session=None, start_timestamp=None):
        self.config = config
        self.session = session if session is not None else requests.Session()
        # BOT 起動時のタイムスタンプです。これより後の発言にのみ反応します。
        self.start_timestamp = (
            start_timestamp if start_timestamp is not None else round(time.time())
        )
        # 反応済みの発言 ID のリストです。
        self.done_ids = []

    def main(self):
        """トップレベルメソッドです。"""
        # まれに sqlite3.OperationalError: disk I/O error が発生するため、その場合はやり直します。
        while True:
            try:
                recordList = self.selectRecordList()
                break
            except sqlite3.OperationalError:
                logger.warning('sqlite3.OperationalError が発生しました。')
                continue
        if not recordList:
            return False
        for record in recordList:
            # 発言の内容に応じて返答を作ります。
            reply = self.getReply(record['body_xml'])
            if not reply:
                return None
            # 反応済みリストに ID を追加します。
            self.done_ids.append(record['id'])
            # 返答を Skype へ送信します。
            self.sendSkype(reply)
        return None

    def selectRecordList(self):
        """main.db からレコードを取得します。"""
        # connection をグローバルに作るとマルチスレッドのエラーになるため、ここで作ります。
        connection = sqlite3.connect(self.config.db_dir + '/main.db')
        cursor = connection.cursor()
        # SQL の「body_xml に PATTERNS の key を含む」部分を作ります。
        # AND (1=0 OR `body_xml` LIKE '%key%' OR `body_xml` LIKE '%key%') のような形です。
        likePart = ''
        if PATTERNS:
            likePart = 'AND (1=0 '
            for key in PATTERNS:
                likePart += f"OR `body_xml` LIKE '%{key}%' "
            likePart = likePart + ')'
        # SQL の「反応済みの ID を除く」部分を作ります。AND `id` NOT IN (**,**) のような形です。
        idPart = ''
        if self.done_ids:
            idPart = 'AND `id` NOT IN ('
            for doneId in self.done_ids:
                idPart += str(doneId) + ','
            idPart = idPart[0:-1] + ')'
        # 「BOT 起動後」「PATTERNS の key を含む」「反応済みの ID を除く」発言を取得します。
        sql = f'SELECT id,body_xml FROM `Messages` WHERE `timestamp`>? {likePart} {idPart}'  # noqa: S608
        bind = (self.start_timestamp,)
        cursor.execute(sql, bind)
        rows = cursor.fetchall()
        connection.close()
        if not rows:
            return False
        return [{'id': row[0], 'body_xml': row[1]} for row in rows]

    def getReply(self, body_xml):
        """body_xml の内容に対応する返答を返します。該当しない場合は None を返します。"""
        for key, value in PATTERNS.items():
            if key in body_xml:
                return value
        return None

    def sendSkype(self, reply):
        """Skype for Web へ返答を送信します。"""
        clientmessageid = random.randint(1000000000000, 9999999999999)  # noqa: S311
        postjson = (
            '{'
            + f'content        : "{reply}",'
            + f'clientmessageid: "{clientmessageid}",'
            + 'messagetype    : "RichText",'
            + 'contenttype    : "text",'
            + '}'
        )
        headers = {**HEADERS, 'RegistrationToken': self.config.token}
        self.session.post(self.config.url, data=postjson, headers=headers)
        return True


class WatchDog(FileSystemEventHandler):
    """main.db の変更を検知すると、SimpleSkypeBot の main メソッドを実行します。"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    def on_modified(self, event):
        """main.db が変更された (Skype で発言があった) 場合に Bot を動かします。"""
        if event.src_path.endswith('main.db'):
            self.bot.main()


def main():
    """環境変数から設定を読み込み、main.db の監視を開始します。"""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        config = load_config(os.environ)
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
