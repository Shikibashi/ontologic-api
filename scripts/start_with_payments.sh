#!/bin/bash
# Start Ontologic API with payment processing enabled
# Usage: ./scripts/start_with_payments.sh [--port PORT] [--reload]

set -e

# Default values
PORT=8080
RELOAD_FLAG=""
ENV="dev"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --port)
      PORT="$2"
      shift 2
      ;;
    --reload)
      RELOAD_FLAG="--reload"
      shift
      ;;
    --env)
      ENV="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--port PORT] [--reload] [--env ENV]"
      exit 1
      ;;
  esac
done

# Check if .env file exists
if [ -f .env ]; then
  echo "Loading environment variables from .env file..."
  export $(cat .env | grep -v '^#' | xargs)
else
  echo "Warning: .env file not found. Using configuration from TOML files only."
  echo "To use Stripe, create a .env file with your API keys (see .env.example)"
fi

# Ensure payments are enabled
export APP_PAYMENTS_ENABLED=true

echo "Starting Ontologic API with payments enabled..."
echo "Environment: $ENV"
echo "Port: $PORT"
echo "Payments: ENABLED"

if [ -n "$APP_STRIPE_SECRET_KEY" ]; then
  echo "Stripe: CONFIGURED (secret key found)"
else
  echo "Stripe: NOT CONFIGURED (set APP_STRIPE_SECRET_KEY in .env)"
fi

echo ""
echo "Starting server..."
uv run app/main.py --env "$ENV" --host 0.0.0.0 --port "$PORT" $RELOAD_FLAG
