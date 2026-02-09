#!/bin/bash
set -e

# Start the FastAPI application with scheduler
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
