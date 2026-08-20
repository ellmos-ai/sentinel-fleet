FROM python:3.11.15-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HOST=0.0.0.0

COPY . .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock && \
    pip install --no-cache-dir --no-deps . && \
    groupadd --system sentinel && \
    useradd --system --gid sentinel --home-dir /app sentinel && \
    chown -R sentinel:sentinel /app

USER sentinel

EXPOSE 8080

CMD ["python", "app.py"]
