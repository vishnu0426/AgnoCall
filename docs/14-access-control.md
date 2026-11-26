# Access control

Every API route needs a signed-in user, except the few listed here.

| Route | Who may call it |
|---|---|
| `POST /auth/login` | Anyone (throttled: 8 failed attempts per 5 minutes per address and username) |
| `GET /health` | Anyone (returns only `ok`) |
| GraphQL `getEvaluationForm`, `saveEvaluationResponse` | Anyone: the public form-fill page `/forms/f/<id>` |
| `POST /internal/*` | The `INTERNAL_API_KEY` (MinIO webhook `auth_token`), not a user |
| `POST /auth/register` | Administrators only |
| Everything else | A valid sign-in token |

The token is sent as `Authorization: Bearer <token>`. For plain GET requests the `forms_session` cookie is also
accepted (a browser download link, such as the CSV export, cannot send a header). A cookie is never accepted
for requests that change data.

The web app also gates its pages: without a valid session `/` redirects to `/login`. The gate asks the API
(`GET /auth/me`) whether the token is genuine, so a forged cookie does not pass.

## Set these in `.env` before going live
- `FORMS_JWT_SECRET`: 32+ random characters. The API **refuses to start** with the public default.
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- `INTERNAL_API_KEY`: set the same value as the MinIO webhook `auth_token`, or the webhook is refused (the periodic
  sync still picks new files up).
- `API_DOCS_ENABLED=false` (default): `/docs`, `/redoc`, `/openapi.json` and GraphiQL are off.
- Change the default `admin` / `admin123` password (Settings > Account).

## Keeping it closed
`tests/test_api_auth.py` fails when a route is added without a sign-in check. A new public route must be added to
its `PUBLIC` list, with a reason.

## Known limits
- Tokens last 24 hours and cannot be revoked before they expire (changing `FORMS_JWT_SECRET` signs everyone out).
- There is one role check (`admin`). Any signed-in user can read every call; per-team scoping is not built.
- Form image uploads under `/api/v1/uploads` are served without a sign-in (they belong to form content).
- Serve the app over HTTPS in production, or tokens and recordings travel in clear text.
