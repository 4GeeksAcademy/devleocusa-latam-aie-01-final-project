# Federated authentication (Microsoft)

TrackFlow federated login is Microsoft-only. Linking is available only to an authenticated TrackFlow user from **Mi usuario → Seguridad**. Microsoft login never provisions a user, tenant, or customer association. The account must already exist and its Microsoft `oid`/`sub` must have been explicitly linked.

## Configuration

Set these values in the deployment secret/environment manager (do not commit the client secret):

```dotenv
MICROSOFT_CLIENT_ID=...
MICROSOFT_CLIENT_SECRET=...
MICROSOFT_TENANT_ID=organizations
OAUTH_REDIRECT_URI=https://api.example.com/auth/federated/microsoft/callback
FEDERATED_AUTH_FRONTEND_URL=https://app.example.com
```

For local development, the callback may use `http://localhost`; all non-local deployments must use HTTPS. Register the exact same callback URL in the Microsoft Entra application. `MICROSOFT_TENANT_ID=organizations` permits organizational Microsoft accounts, but does not authorize automatic TrackFlow account creation.

OAuth state and nonce are short-lived and single-use. The callback URI used in both authorization and token exchange is pinned to `OAUTH_REDIRECT_URI`; a mismatching callback parameter is rejected. Microsoft provider tokens are never stored. Successful federated authentication issues the same TrackFlow JWT with the configured `ACCESS_TOKEN_EXPIRE_MINUTES` as password login.

Federated identity links and audit records are stored in TinyDB in this implementation. TinyDB is process-local and does not ensure atomic uniqueness across independent worker processes/replicas. Before horizontally scaling or productionizing this store, migrate these tables to the shared transactional database with a unique constraint on `(provider, provider_user_id)` and append-only audit controls.
