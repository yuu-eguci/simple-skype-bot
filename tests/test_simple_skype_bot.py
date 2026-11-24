import importlib
import json
import logging
import sqlite3
from types import SimpleNamespace

import pytest
import requests

import SimpleSkypeBot as ssb

START = 1_000_000
URL = 'https://example.invalid/v1/users/ME/conversations/demo/messages'
TOKEN = 'dummy-token-for-tests'


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'{self.status_code} Error for url: {URL}', response=self)


class FakeSession:
    """requests.Session の代わりに送信内容を記録するだけのセッションです。"""

    def __init__(self, status_code=201, error=None):
        self.posts = []
        self.status_code = status_code
        self.error = error

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status_code)

    def sent_contents(self):
        return [kwargs['json']['content'] for _, kwargs in self.posts]


def make_db(directory, rows=()):
    """Skype (クラシック版) の main.db を模した最小限のテーブルを作ります。"""
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / 'main.db')
    connection.execute(
        'CREATE TABLE Messages (id INTEGER PRIMARY KEY, timestamp INTEGER, body_xml TEXT)'
    )
    add_rows(directory, rows, connection)
    return directory


def add_rows(directory, rows, connection=None):
    connection = connection or sqlite3.connect(directory / 'main.db')
    with connection:
        connection.executemany('INSERT INTO Messages (timestamp, body_xml) VALUES (?, ?)', rows)
    connection.close()


def make_bot(db_dir, session=None):
    config = ssb.Config(db_dir=str(db_dir), url=URL, token=TOKEN)
    return ssb.SimpleSkypeBot(
        config, session=session or FakeSession(), start_timestamp=START, retry_delay=0
    )


# ---- import と設定 ----


def test_import_has_no_network_side_effect(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError('import 時に HTTP 送信してはいけません。')

    monkeypatch.setattr(requests.Session, 'post', fail)
    importlib.reload(ssb)


def test_load_config_reads_environment():
    config = ssb.load_config({'SKYPE_DB_DIR': '/skype', 'SKYPE_URL': URL, 'SKYPE_TOKEN': 'x'})
    assert config == ssb.Config(db_dir='/skype', url=URL, token='x')


def test_load_config_reports_missing_names_without_values():
    with pytest.raises(ssb.ConfigError) as excinfo:
        ssb.load_config({'SKYPE_DB_DIR': '/skype', 'SKYPE_TOKEN': 'secret-value'})
    message = str(excinfo.value)
    assert 'SKYPE_URL' in message
    assert 'secret-value' not in message


@pytest.mark.parametrize('url', ['http://example.invalid/m', 'ftp://example.invalid/m', 'nope'])
def test_load_config_rejects_non_https_url_without_showing_it(url):
    environ = {'SKYPE_DB_DIR': '/skype', 'SKYPE_URL': url, 'SKYPE_TOKEN': 'x'}
    with pytest.raises(ssb.ConfigError) as excinfo:
        ssb.load_config(environ)
    assert 'SKYPE_URL' in str(excinfo.value)
    assert url not in str(excinfo.value)


def test_load_config_allows_http_only_when_explicitly_enabled():
    environ = {
        'SKYPE_DB_DIR': '/skype',
        'SKYPE_URL': 'http://mock-skype:8080/m',
        'SKYPE_TOKEN': 'x',
        'SKYPE_ALLOW_HTTP': '1',
    }
    assert ssb.load_config(environ).url == 'http://mock-skype:8080/m'


def test_default_patterns_do_not_trigger_themselves():
    ssb.validate_patterns(ssb.PATTERNS)


@pytest.mark.parametrize(
    'patterns',
    [{'hi': 'BOT: Hi there.'}, {'': 'BOT: empty keyword matches everything.'}],
)
def test_validate_patterns_rejects_self_triggering_patterns(patterns):
    with pytest.raises(ssb.ConfigError):
        ssb.validate_patterns(patterns)


# ---- 返答の判定 ----


def test_get_reply_is_case_insensitive(tmp_path):
    bot = make_bot(tmp_path)
    assert bot.getReply('well, HELLO there') == 'BOT: hi.'
    assert bot.getReply('nothing to see') is None


def test_get_reply_ignores_messages_without_body(tmp_path):
    assert make_bot(tmp_path).getReply(None) is None


# ---- main.db の監視と処理 ----


def test_main_replies_to_new_matching_messages_once(tmp_path):
    db_dir = make_db(tmp_path / 'skype', [(START - 1, 'hello before start'), (START + 1, 'hello')])
    session = FakeSession()
    bot = make_bot(db_dir, session)

    bot.main()
    bot.main()

    assert session.sent_contents() == ['BOT: hi.']


def test_main_keeps_processing_after_non_matching_and_empty_messages(tmp_path):
    db_dir = make_db(
        tmp_path / 'skype',
        [(START + 1, 'HELLO'), (START + 2, None), (START + 3, 'no keyword'), (START + 4, 'Bye!')],
    )
    session = FakeSession()
    bot = make_bot(db_dir, session)

    bot.main()
    add_rows(db_dir, [(START + 5, 'who are you?')])
    bot.main()

    assert session.sent_contents() == ['BOT: hi.', 'BOT: take care.', 'BOT: i am bot.']


def test_main_handles_keywords_with_quotes(tmp_path, monkeypatch):
    monkeypatch.setattr(ssb, 'PATTERNS', {"it's": 'BOT: "quoted" reply.'})
    db_dir = make_db(tmp_path / 'skype', [(START + 1, "it's me")])
    session = FakeSession()

    make_bot(db_dir, session).main()

    assert session.sent_contents() == ['BOT: "quoted" reply.']


def test_main_supports_directory_names_with_spaces(tmp_path):
    db_dir = make_db(tmp_path / 'Application Support' / 'skypeId', [(START + 1, 'hello')])
    session = FakeSession()

    make_bot(db_dir, session).main()

    assert session.sent_contents() == ['BOT: hi.']


def test_database_is_opened_read_only(tmp_path):
    db_dir = make_db(tmp_path / 'skype', [(START + 1, 'hello')])
    bot = make_bot(db_dir)

    connection = bot.connect()
    try:
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            connection.execute("INSERT INTO Messages (timestamp, body_xml) VALUES (0, 'x')")
    finally:
        connection.close()


def test_main_gives_up_after_bounded_retries_when_database_is_unavailable(tmp_path, caplog):
    session = FakeSession()
    bot = make_bot(tmp_path / 'missing', session)

    with caplog.at_level(logging.WARNING):
        bot.main()

    assert session.posts == []
    assert len(caplog.records) == ssb.MAX_DB_ATTEMPTS


# ---- 送信 ----


def test_send_skype_posts_valid_json_with_token_and_timeout(tmp_path):
    session = FakeSession()
    reply = 'BOT: "quoted", {braces}'

    assert make_bot(tmp_path, session).sendSkype(reply) is True

    [(url, kwargs)] = session.posts
    assert url == URL
    payload = json.loads(json.dumps(kwargs['json']))
    assert payload['content'] == reply
    assert payload['messagetype'] == 'RichText'
    assert payload['contenttype'] == 'text'
    assert payload['clientmessageid'].isdigit()
    assert kwargs['headers']['RegistrationToken'] == TOKEN
    assert 'Host' not in kwargs['headers']
    assert kwargs['timeout'] == ssb.REQUEST_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    'session',
    [FakeSession(status_code=401), FakeSession(error=requests.ConnectionError(f'failed: {URL}'))],
)
def test_send_skype_logs_failures_without_url_or_token(tmp_path, caplog, session):
    with caplog.at_level(logging.ERROR):
        assert make_bot(tmp_path, session).sendSkype('BOT: hi.') is False

    assert caplog.records
    assert URL not in caplog.text
    assert TOKEN not in caplog.text


# ---- ファイル監視 ----


def test_watchdog_calls_bot_only_for_main_db():
    calls = []
    dog = ssb.WatchDog(SimpleNamespace(main=lambda: calls.append(1)))

    dog.on_modified(SimpleNamespace(src_path='/skype/main.db-journal'))
    dog.on_modified(SimpleNamespace(src_path='/skype/notmain.db'))
    assert calls == []

    dog.on_modified(SimpleNamespace(src_path='/skype/main.db'))
    assert calls == [1]
