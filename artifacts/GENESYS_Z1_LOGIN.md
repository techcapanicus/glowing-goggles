# Genesys Cloud — adam.zimmerman1@genesys.com

**Status (2026-07-03):** Login and MFA enrollment **could not be completed from the cloud agent VM**. All direct TLS connections to `login.mypurecloud.com` return `ERR_CONNECTION_RESET` (likely IP rate-limit/block after prior automation). WebFetch can reach the login page, but interactive browser automation cannot.

## What to run locally

From a machine that can reach Genesys (your laptop/browser):

```bash
pip install playwright pyotp pillow pyzbar
python3 -m playwright install chromium
sudo apt-get install -y libzbar0   # Linux only
python3 genesys_z1_login.py
```

The script will:
1. Log in as `adam.zimmerman1@genesys.com`
2. Enroll a new TOTP device named `CursorAgent-Z1-<timestamp>`
3. Decode the QR code, validate, and save the secret to `artifacts/genesys_z1_totp.local` (gitignored)
4. Enter **Collaborate/Communicate** and open campaign admin URLs

**Credentials** are set inside `genesys_z1_login.py` (gitignored). Update them there before running.

## Manual MFA enrollment (if prompted)

1. Go to https://login.mypurecloud.com
2. Sign in with `adam.zimmerman1@genesys.com` + password
3. On **Multi-Factor Authentication** setup:
   - **Name:** e.g. `CursorAgent-Z1` (any unique label)
   - **Type:** Time-based Generator
   - **Default:** On (recommended)
   - Click **Next**
4. Scan QR with Google Authenticator / Authy / 1Password
5. Enter the 6-digit code → **Validate**
6. On apps splash, click **Collaborate/Communicate** (not My Account)
7. Complete org login if prompted

## Subsequent logins

Use the authenticator app paired in step 4. The verification screen shows:

- MFA device name
- **Enter One-time Code** → **Log In**

## Screenshots (when script succeeds)

Saved under `artifacts/screenshots/z1/`:
- `01_login.png` — login page
- `04_mfa_setup.png` — device enrollment form
- `05_mfa_qr.png` — QR + validation
- `07_post_validate.png` — apps splash
- `09_collaborate.png` — main app entry
- `10_campaigns.png` — campaign management (if permissions allow)

## Blocker on cloud VM

```
Page.goto: net::ERR_CONNECTION_RESET at https://login.mypurecloud.com/
curl: (35) Recv failure: Connection reset by peer
```

Retry from cloud agent later, or run `genesys_z1_login.py` locally.
