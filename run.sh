#!/bin/bash
export PATH="/opt/homebrew/bin:$PATH"
cd "$(dirname "$0")"
source .env
exec .venv/bin/python display.py
