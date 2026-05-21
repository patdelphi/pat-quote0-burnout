#!/bin/bash
cd "$(dirname "$0")"
source .env
exec .venv/bin/python display.py
