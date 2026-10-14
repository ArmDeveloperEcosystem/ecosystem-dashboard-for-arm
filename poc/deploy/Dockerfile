# Runtime image for the API only. The same commit's Hugo output is deployed by
# the existing static-site process; do not copy source content or tokens here.
# Official multi-platform manifest resolved on 2026-09-23. Review and rescan when
# updating this digest; --build-arg permits an organization-approved mirror.
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ARM_SEARCH_SITE_DIR=/app/site \
    ARM_SEARCH_SERVE_STATIC=false \
    ARM_SEARCH_DOCS_ENABLED=false
WORKDIR /app
COPY poc/requirements.runtime.lock.txt /app/requirements.lock.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r /app/requirements.lock.txt \
    && python -m pip check \
    && groupadd --gid 10001 search \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin search
COPY poc/*.py /app/poc/
COPY .poc/public/poc-catalog.json /app/site/poc-catalog.json
USER 10001:10001
EXPOSE 8080
# Health probes send the configured public Host because the listener intentionally
# rejects arbitrary Host headers. No KB request is made by this probe.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c 'import os,urllib.request,urllib.parse; host=urllib.parse.urlsplit(os.environ["ARM_SEARCH_PUBLIC_ORIGIN"]).netloc; urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/api/ready",headers={"Host":host}),timeout=2).read()'
CMD ["python", "-m", "poc.serve", "--host", "0.0.0.0", "--port", "8080"]
