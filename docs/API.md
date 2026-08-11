# API

FastAPI serving layer (`enterprise_memory.serving.api:create_app`, factory). Endpoints are described in
the committed `openapi.json`. Each request carries a `request_id` and writes an `audit_id`. Cross-user
isolation and scope enforcement are applied server-side. Start locally:
`uvicorn enterprise_memory.serving.api:create_app --factory`.
