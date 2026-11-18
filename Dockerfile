FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# git is required by the workspace binder (git URL -> shallow clone) and the
# git_status/git_diff tools.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests

# Render's filesystem is ephemeral, so durable state goes to a mounted disk if
# one is attached. Without a disk these paths simply reset on redeploy.
ENV PORT=8080 \
    DATABASE_PATH=/tmp/bugcheck.db \
    UPLOAD_TMP_DIR=/tmp/uploads \
    REPORTS_DIR=/tmp/reports \
    WORKSPACE_DIR=/tmp/workspaces \
    AGENT_ASSETS_DIR=

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
