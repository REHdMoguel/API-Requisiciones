# Procurement Approval API

Sanitized FastAPI reference project for a two-level quotation approval workflow backed by Firebird. It demonstrates multi-branch database routing, API-key authentication, transactional updates, audit events, rejection handling and conversion of approved quotations into purchase orders.

## Why this repository exists

This public edition preserves the engineering patterns of an operational integration while replacing company names, network addresses, credentials and proprietary identifiers with synthetic examples. The SQL uses a fictional `DEMO_*` schema and must be adapted to a database you own.

## Stack

- Python 3.11+
- FastAPI and Uvicorn
- Firebird (`fdb`)
- Pydantic

## Safe setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Export variables with your preferred secret manager; do not commit .env.
uvicorn main:app --host 127.0.0.1 --port 8000
```

Interactive API documentation is available at `/docs`. Set a strong `API_KEY` and place the service behind TLS before exposing it to a network.

## Security design

- No embedded database passwords or internal IP addresses.
- API keys are read from the environment.
- Parameterized SQL for request values.
- Database writes execute inside commit/rollback context managers.
- Debug request-body logging is disabled by default.
- Multi-branch configuration is injected through `DB_BRANCHES_JSON`.

## Verification

```bash
python -m compileall -q .
pytest -q
```

## Disclaimer

Independent portfolio demonstration using a synthetic schema. It is not affiliated with any ERP vendor. Confirm ownership and publication rights before assigning an open-source license.
