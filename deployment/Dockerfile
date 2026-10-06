FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .
COPY schemas ./schemas
COPY prompts ./prompts
COPY config ./config
COPY TOPIC.md ./
CMD ["max-agent", "serve", "--host", "0.0.0.0", "--port", "8080"]
