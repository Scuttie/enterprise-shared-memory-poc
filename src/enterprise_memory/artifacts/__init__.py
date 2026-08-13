"""P4 artifact store. PostgreSQL holds authoritative artifact metadata + a durable lifecycle state machine;
the object store (local filesystem or S3/MinIO) holds content-addressed, tenant-prefixed, SHA-256-verified
objects. No credentials, host environment, or unrestricted private source dumps are ever stored."""
