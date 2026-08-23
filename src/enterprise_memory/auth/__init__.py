"""P3 authentication/authorization. OIDC access-token verification (RS256/optional ES256, JWKS with
rotation + fail-closed), endpoint scope enforcement, and repository authorization. Identity and permissions
come ONLY from the verified token and the authorization provider — never from request-body claims."""
