FROM python:3.12-slim AS requirements

WORKDIR /app

RUN pip install --no-cache-dir poetry poetry-plugin-export

COPY pyproject.toml poetry.lock ./

RUN poetry export --only main --format requirements.txt --without-hashes --output /tmp/requirements.txt \
    && grep -Ev '^(torch|triton|nvidia-)' /tmp/requirements.txt > /tmp/requirements-container.txt

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MUGEN_CONFIG_FILE=conf/mugen.toml.sample
ENV PORT=8000

COPY --from=requirements /tmp/requirements-container.txt /tmp/requirements-container.txt

RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu 'torch==2.8.0+cpu' \
    && pip install --no-cache-dir -r /tmp/requirements-container.txt \
    && pip install --no-cache-dir 'psycopg[binary]==3.3.2' \
    && pip check \
    && rm -f /tmp/requirements-container.txt

COPY . .

EXPOSE 8000 8443

CMD ["sh", "scripts/container_start.sh"]
