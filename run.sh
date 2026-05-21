#!/bin/bash
cd "$(dirname "$0")"
source .env
exec .venv/bin/python quote0_usage.py
