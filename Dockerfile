FROM python:3.12-slim AS requirements

WORKDIR /app

RUN pip install --no-cache-dir 'poetry==2.1.3' 'poetry-plugin-export==1.9.0'

COPY pyproject.toml poetry.lock README.md ./

RUN poetry check --lock \
    && poetry export --only main --format requirements.txt --output /tmp/requirements-container.txt

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MUGEN_CONFIG_FILE=conf/mugen.toml.sample
ENV PORT=8000

COPY --from=requirements /tmp/requirements-container.txt /app/container-requirements.txt

RUN pip install --no-cache-dir --require-hashes --no-deps -r /app/container-requirements.txt \
    && pip check \
    && pip inspect > /app/container-python-inventory.json

COPY . .

RUN python scripts/verify_container_inventory.py

EXPOSE 8000 8443

CMD ["sh", "scripts/container_start.sh"]
