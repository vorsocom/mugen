#!/bin/sh
set -eu

bind_port="${PORT:-8000}"

if [ -n "${TLS_CERT_FILE:-}" ] || [ -n "${TLS_KEY_FILE:-}" ]; then
    if [ -z "${TLS_CERT_FILE:-}" ] || [ -z "${TLS_KEY_FILE:-}" ]; then
        echo "TLS_CERT_FILE and TLS_KEY_FILE must both be set for HTTPS." >&2
        exit 64
    fi
    if [ ! -r "${TLS_CERT_FILE}" ]; then
        echo "TLS_CERT_FILE is not readable: ${TLS_CERT_FILE}" >&2
        exit 66
    fi
    if [ ! -r "${TLS_KEY_FILE}" ]; then
        echo "TLS_KEY_FILE is not readable: ${TLS_KEY_FILE}" >&2
        exit 66
    fi

    exec python -m hypercorn \
        --bind "0.0.0.0:${bind_port}" \
        --certfile "${TLS_CERT_FILE}" \
        --keyfile "${TLS_KEY_FILE}" \
        quartman
fi

exec python -m hypercorn --bind "0.0.0.0:${bind_port}" quartman
