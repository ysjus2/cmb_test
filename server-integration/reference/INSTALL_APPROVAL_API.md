# CMB DXF Viewer - Installation Approval API Contract

## Purpose
The Windows installer must verify a pre-registered company account with the Ubuntu server before installation is allowed. The server is the authority for account approval status. The installer must not contain an offline bypass for normal interactive installation.

## 1. Approval check

`POST /api/cmb/installer/authorize`

Request JSON:
```json
{
  "account_id": "user supplied login ID",
  "password": "user supplied password",
  "installer_name": "user supplied real name",
  "department": "user supplied department",
  "computer_name": "Windows computer name",
  "windows_user": "Windows user name",
  "app_version": "3.20",
  "notice_version": "CMB-INTERNAL-USE-2026-10-05-v1"
}
```

Success response:
```json
{
  "approved": true,
  "user_id": "stable-server-user-id",
  "display_name": "approved user display name",
  "department": "approved department",
  "authorization_id": "one-time-or-short-lived-install-authorization-id",
  "expires_at": "ISO-8601 timestamp"
}
```

Denied response:
```json
{
  "approved": false,
  "reason": "pending|disabled|not_found|invalid_credentials|not_authorized"
}
```

Rules:
- HTTPS only.
- Passwords are never logged by installer or server.
- Server stores password hashes only (Argon2id or bcrypt), never plaintext.
- Account state must be one of: pending, approved, suspended, revoked.
- Only `approved` may install.
- `authorization_id` should be short-lived and single-use if practical.

## 2. Record consent and completed install

`POST /api/cmb/installer/acknowledge`

Request JSON:
```json
{
  "authorization_id": "server-issued-id",
  "installer_name": "user supplied real name",
  "department": "user supplied department",
  "computer_name": "Windows computer name",
  "windows_user": "Windows user name",
  "installed_at": "ISO-8601 timestamp",
  "app_version": "3.20",
  "notice_version": "CMB-INTERNAL-USE-2026-10-05-v1",
  "consent": true,
  "installer_sha256": "setup exe sha256"
}
```

Success response:
```json
{
  "recorded": true,
  "receipt_id": "immutable-server-receipt-id"
}
```

The server should additionally record request time and client IP independently.

## 3. Recommended database tables

### installer_users
- id
- account_id (unique)
- password_hash
- display_name
- department
- status (pending/approved/suspended/revoked)
- approved_by
- approved_at
- created_at
- updated_at

### installer_authorizations
- id
- user_id
- issued_at
- expires_at
- used_at
- computer_name
- windows_user
- app_version
- status

### installer_acknowledgements
- id
- authorization_id
- user_id
- installer_name
- department
- computer_name
- windows_user
- installed_at
- app_version
- notice_version
- consent
- installer_sha256
- client_ip
- server_received_at
- receipt_id

## 4. Installer behavior

Interactive install sequence:
1. User enters account ID/password, name, department.
2. Installer calls `/authorize`.
3. If not approved, installation stops with the server reason.
4. If approved, installer shows the internal-use / no-external-transfer notice.
5. User must explicitly agree.
6. Installer checks/installs Microsoft VC++ Runtime if required.
7. Application is installed and shortcuts/uninstall registration are created.
8. Installer calls `/acknowledge` and stores the returned receipt ID locally.
9. The application starts.

Normal interactive installation must fail closed when the approval server cannot be reached. CI silent validation may use a dedicated test-only bypass compiled only in CI and never distributed.
