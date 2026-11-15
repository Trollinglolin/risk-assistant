"""Load secrets from AWS SSM Parameter Store at cold start (Lambda).

Set HKRISK_SSM_PREFIX=/hkrisk and store SecureString parameters named after the env vars they
fill, e.g. /hkrisk/GEMINI_API_KEY and /hkrisk/HKRISK_API_KEY. Secrets then never appear in the
image or in the Lambda environment configuration (which anyone with
lambda:GetFunctionConfiguration can read). Only allow-listed names are loaded, and a real
environment variable always wins.
"""

from __future__ import annotations

import logging
import os

ALLOWED = {"GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
           "HKRISK_API_KEY", "HKRISK_API_KEYS"}
log = logging.getLogger(__name__)


def load_ssm_env(prefix: str | None = None, client=None) -> list[str]:
    prefix = prefix or os.getenv("HKRISK_SSM_PREFIX")
    if not prefix:
        return []
    if client is None:
        import boto3

        client = boto3.client("ssm")
    loaded = []
    for page in client.get_paginator("get_parameters_by_path").paginate(
            Path=prefix.rstrip("/"), WithDecryption=True, Recursive=False):
        for p in page["Parameters"]:
            name = p["Name"].rsplit("/", 1)[-1]
            if name in ALLOWED and name not in os.environ:
                os.environ[name] = p["Value"]
                loaded.append(name)
    log.info("loaded %d secrets from SSM %s: %s", len(loaded), prefix, sorted(loaded))  # names only
    return loaded
