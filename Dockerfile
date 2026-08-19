FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[mcp]"
COPY . .
EXPOSE 8000
CMD ["python", "-m", "data_agent.entrypoints.run_api"]
