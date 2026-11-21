FROM python:3.11.15-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3
WORKDIR /archive
ENV PYTHONUNBUFFERED=1 PORT=8080 HOST=0.0.0.0
COPY --chown=65532:65532 archive/server.py ./server.py
COPY --chown=65532:65532 archive/public ./public
USER 65532:65532
EXPOSE 8080
CMD ["python", "-B", "server.py"]
