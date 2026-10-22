FROM node:24-bookworm-slim AS frontend
WORKDIR /build
RUN npm install --global pnpm@11.25.0
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 JIRA_DATA_DIR=/app/resources/app JIRA_STATIC_DIR=/app/frontend/dist
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip==26.2.1 \
    && pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home app \
    && mkdir -p /app/resources/app \
    && chown -R app:app /app/resources
COPY --chown=app:app backend/app ./app
COPY --chown=app:app resources/demo ./resources/demo
COPY --from=frontend --chown=app:app /build/dist ./frontend/dist
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=12 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
