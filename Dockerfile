FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY matrix_jira_bot/ ./matrix_jira_bot/

# Mount your real config.yaml to /config/config.yaml, e.g.:
#   docker run -v $(pwd)/config.yaml:/config/config.yaml:ro matrix-jira-bot
ENTRYPOINT ["python", "-m", "matrix_jira_bot", "/config/config.yaml"]
