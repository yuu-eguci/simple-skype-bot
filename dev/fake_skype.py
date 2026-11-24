"""Skype 側を模したデモ・テスト用のツールです (標準ライブラリのみを使用します)。

使い方:
    python fake_skype.py serve        main.db を作成し、返答を受け取る HTTP サーバーを起動します。
    python fake_skype.py say TEXT     main.db の Messages テーブルに発言を 1 件追加します。
    python fake_skype.py received     HTTP サーバーが受信した返答を JSON の配列で表示します。

環境変数:
    FAKE_SKYPE_DB_DIR   main.db を作成するディレクトリです (既定値: /skype)。
    FAKE_SKYPE_TOKEN    受け付ける RegistrationToken の値です (既定値: dummy-token)。
    FAKE_SKYPE_PORT     HTTP サーバーのポート番号です (既定値: 8080)。
"""

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.request
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DB_DIR = Path(os.environ.get('FAKE_SKYPE_DB_DIR', '/skype'))
TOKEN = os.environ.get('FAKE_SKYPE_TOKEN', 'dummy-token')
PORT = int(os.environ.get('FAKE_SKYPE_PORT', '8080'))
MAX_BODY_BYTES = 64 * 1024

# 受信した返答です。HTTP サーバーのスレッド間で共有します。
RECEIVED = []
RECEIVED_LOCK = threading.Lock()


def connect():
    return sqlite3.connect(DB_DIR / 'main.db')


def init_db():
    """Skype (クラシック版) の main.db を模した最小限のテーブルを作成します。"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as connection, connection:
        connection.execute(
            'CREATE TABLE IF NOT EXISTS Messages'
            ' (id INTEGER PRIMARY KEY, timestamp INTEGER, body_xml TEXT)'
        )


def say(text):
    """発言を 1 件追加します。"""
    with closing(connect()) as connection, connection:
        connection.execute(
            'INSERT INTO Messages (timestamp, body_xml) VALUES (?, ?)', (int(time.time()), text)
        )


class Handler(BaseHTTPRequestHandler):
    """Bot からの返答を受け取り、メモリ上に記録します。"""

    def do_GET(self):
        if self.path == '/health':
            self.respond(200, {'status': 'ok'})
        elif self.path == '/received':
            with RECEIVED_LOCK:
                replies = list(RECEIVED)
            self.respond(200, replies)
        else:
            self.respond(404, {'error': 'not found'})

    def do_POST(self):
        if self.headers.get('RegistrationToken') != TOKEN:
            self.respond(401, {'error': 'invalid token'})
            return
        length = int(self.headers.get('Content-Length') or 0)
        if not 0 < length <= MAX_BODY_BYTES:
            self.respond(400, {'error': 'invalid body length'})
            return
        try:
            content = json.loads(self.rfile.read(length))['content']
        except ValueError, KeyError, TypeError:
            self.respond(400, {'error': 'invalid json'})
            return
        with RECEIVED_LOCK:
            RECEIVED.append(content)
        print(f'返答を受信しました: {content}', flush=True)
        self.respond(201, {'OriginalArrivalTime': int(time.time() * 1000)})

    def respond(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        # アクセスログは出力しません。
        pass


def serve():
    init_db()
    print(f'fake-skype を起動しました (port={PORT})。', flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()  # noqa: S104


def received():
    url = f'http://127.0.0.1:{PORT}/received'
    with urllib.request.urlopen(url, timeout=5) as response:
        print(json.dumps(json.load(response), ensure_ascii=False))


def main(argv):
    if argv[1:2] == ['serve']:
        serve()
    elif argv[1:2] == ['say'] and len(argv) == 3:
        say(argv[2])
    elif argv[1:2] == ['received']:
        received()
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
