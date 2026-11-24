FROM python:3.15.2-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY SimpleSkypeBot.py ./

# root 以外のユーザーで実行します。
RUN useradd --create-home --uid 10001 bot
USER bot

CMD ["python", "SimpleSkypeBot.py"]

FROM runtime AS dev

USER root
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY pyproject.toml ./
COPY tests ./tests
RUN chown -R bot:bot /app
USER bot
