FROM python:3.15.2-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

# root 以外のユーザーで実行します。
RUN groupadd --gid 10001 bot && useradd --create-home --uid 10001 --gid 10001 bot

WORKDIR /app

# Bot の実行用イメージです。
FROM base AS runtime

COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY SimpleSkypeBot.py ./

USER 10001:10001
CMD ["python", "SimpleSkypeBot.py"]

# テストと lint 用のイメージです。
FROM runtime AS dev

USER 0
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY pyproject.toml ./
COPY tests ./tests
COPY dev ./dev
RUN chown -R 10001:10001 /app
USER 10001:10001

# デモ・E2E テスト用に Skype 側を模すイメージです (標準ライブラリのみを使用します)。
FROM base AS fake-skype

COPY dev/fake_skype.py ./
# 共有ボリュームの初期の所有者を実行ユーザーにするため、マウント先を作成しておきます。
RUN mkdir /skype && chown 10001:10001 /skype
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=2s --timeout=3s --retries=15 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]
CMD ["python", "fake_skype.py", "serve"]
