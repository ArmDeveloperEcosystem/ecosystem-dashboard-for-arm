# Python 3.12.14 multi-platform index; verified against registry-1.docker.io.
# Update this digest deliberately, rebuild, scan and repeat release validation.
FROM python:3.12.14-slim-trixie@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="Internal Linux Arm64 opportunity report" \
      org.opencontainers.image.source="https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm" \
      org.opencontainers.image.revision=$VCS_REF

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY poc/discovery/deploy/requirements.build.lock /tmp/requirements.build.lock
COPY poc/discovery/deploy/requirements.runtime.lock /tmp/requirements.runtime.lock
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.build.lock \
    && python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.runtime.lock \
    && python -m pip check \
    && python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip \
    && rm /tmp/requirements.runtime.lock /tmp/requirements.build.lock \
    && groupadd --gid 10001 discovery \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin discovery \
    && install -d -m 0700 -o 10001 -g 10001 /state \
    && install -d -m 0755 /config /app/poc/discovery/deploy

WORKDIR /app
COPY poc/__init__.py /app/poc/__init__.py
COPY poc/discovery/__init__.py poc/discovery/__main__.py \
     poc/discovery/ai_review.py poc/discovery/evidence.py \
     poc/discovery/http.py poc/discovery/identity.py poc/discovery/text.py \
     poc/discovery/pipeline.py \
     poc/discovery/report.py poc/discovery/sources.py /app/poc/discovery/
COPY poc/discovery/deploy/__init__.py poc/discovery/deploy/run.py /app/poc/discovery/deploy/
COPY content/linux/ /app/content/linux/

USER 10001:10001
ENTRYPOINT ["python", "-m", "poc.discovery.deploy.run"]
CMD ["--config", "/config/config.yaml", "--output-dir", "/state", "--catalog", "/app/content/linux", "--fail-on-errors"]
