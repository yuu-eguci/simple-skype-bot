from types import SimpleNamespace

import pytest

import SimpleSkypeBot as ssb


class FakeSession:
    """requests.Session の代わりに送信内容を記録するだけのセッションです。"""

    def __init__(self):
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return SimpleNamespace(status_code=201)


def make_config(tmp_path):
    return ssb.Config(db_dir=str(tmp_path), url='https://example.invalid/messages', token='t0ken')


def test_import_has_no_network_side_effect(monkeypatch):
    # import 時に送信処理が走らないことを確認します。
    import importlib

    import requests

    def fail(*args, **kwargs):
        raise AssertionError('import 時に HTTP 送信してはいけません。')

    monkeypatch.setattr(requests.Session, 'post', fail)
    importlib.reload(ssb)


def test_load_config_reads_environment():
    config = ssb.load_config(
        {'SKYPE_DB_DIR': '/skype', 'SKYPE_URL': 'https://example.invalid/m', 'SKYPE_TOKEN': 'x'}
    )
    assert config == ssb.Config(db_dir='/skype', url='https://example.invalid/m', token='x')


def test_load_config_reports_missing_names_without_values():
    with pytest.raises(ssb.ConfigError) as excinfo:
        ssb.load_config({'SKYPE_DB_DIR': '/skype', 'SKYPE_TOKEN': 'secret-value'})
    message = str(excinfo.value)
    assert 'SKYPE_URL' in message
    assert 'secret-value' not in message


def test_get_reply_returns_reply_for_matching_keyword(tmp_path):
    bot = ssb.SimpleSkypeBot(make_config(tmp_path), session=FakeSession())
    assert bot.getReply('well, hello there') == 'BOT: hi.'
    assert bot.getReply('nothing to see') is None


def test_send_skype_posts_reply_with_token_header(tmp_path):
    session = FakeSession()
    bot = ssb.SimpleSkypeBot(make_config(tmp_path), session=session)

    bot.sendSkype('BOT: hi.')

    [(url, kwargs)] = session.posts
    assert url == 'https://example.invalid/messages'
    assert kwargs['headers']['RegistrationToken'] == 't0ken'
    assert 'BOT: hi.' in kwargs['data']


def test_watchdog_calls_bot_only_for_main_db():
    calls = []
    dog = ssb.WatchDog(SimpleNamespace(main=lambda: calls.append(1)))

    dog.on_modified(SimpleNamespace(src_path='/skype/main.db-journal'))
    dog.on_modified(SimpleNamespace(src_path='/skype/other.db'))
    assert calls == []

    dog.on_modified(SimpleNamespace(src_path='/skype/main.db'))
    assert calls == [1]
