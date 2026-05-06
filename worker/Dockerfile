ARG DEBIAN_RELEASE=stable
FROM debian:${DEBIAN_RELEASE}

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update     && apt-get install -y --no-install-recommends        python3 python3-flask python3-redis python3-requests        ca-certificates gnupg xz-utils zip curl apt-utils     && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY worker.py /app/worker.py
COPY requirements.txt /app/requirements.txt

EXPOSE 9000
CMD ["python3", "/app/worker.py"]
