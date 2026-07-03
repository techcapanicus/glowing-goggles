# Genesys Cloud Outbound / Agentless Dialing — Exploration Report

**Date:** 2026-07-03  
**Organization:** `globalalliancestests`  
**Region:** Americas (US East)  
**Login URL:** https://login.mypurecloud.com

---

## Executive Summary

| Item | Result |
|------|--------|
| Credential login | **Success** (email/password accepted) |
| MFA | **Configured** (new TOTP device enrolled) |
| Admin console access | **Not reached** (stopped at apps splash / org re-login) |
| Outbound campaign UI explored | **No** (session did not reach `apps.mypurecloud.com` admin) |
| Test call to +17149570044 | **Not initiated** |

Credentials are valid and MFA is now mandatory for this account. Outbound/agentless campaign configuration was **not completed** because the authenticated session never successfully entered the `globalalliancestests` org admin console before connectivity to Genesys was blocked from this environment.

---

## 1. Login

### Steps observed

1. Open https://login.mypurecloud.com
2. Enter email: `adam.zimmerman2@genesys.com`
3. Click **Next**
4. Enter password
5. Click **Sign in**
6. Redirected to MFA screen

### Screenshots

| Step | File |
|------|------|
| Login page | `artifacts/screenshots/01_login_page.png` |
| Email entered | `artifacts/screenshots/01b_email.png` |
| Password entered | `artifacts/screenshots/02_password_filled.png` |
| Post-password (MFA) | `artifacts/screenshots/20b_after_password.png` |

### Result

**Login credentials are valid.** After password submission the app consistently redirects to `#/authenticate-mfa`.

---

## 2. Two-Factor Authentication (2FA)

### Initial state

On first login, the account required **MFA enrollment** (not just verification). No existing usable MFA device was active (prior devices `CursorCloudAgent-TOTP` and `Test MFA Device` were listed as **Disabled** in My Account).

### Setup performed

| Field | Value |
|-------|-------|
| Device name | `CursorAgent-1783044250` |
| Type | Time-based Generator (TOTP / authenticator app) |
| Default | Yes (set as default device) |
| Validation | QR scanned programmatically; 6-digit code entered and accepted |

### Screenshots

| Step | File |
|------|------|
| MFA setup form | `artifacts/screenshots/02a_mfa_setup.png` |
| QR code + validation | `artifacts/screenshots/02b_mfa_qr.png` |
| Code entered | `artifacts/screenshots/02c_code_filled.png` |
| Post-validation splash | `artifacts/screenshots/02d_post_validate.png` |

### Subsequent logins

After enrollment, login shows **verification** (not setup):

- MFA device: `CursorAgent-1783044250 (Time-based Generator)`
- Prompt: **Enter One-time Code**
- Button: **Log In**

### 2FA status

| Status | Detail |
|--------|--------|
| **Configured** | TOTP device `CursorAgent-1783044250` enrolled and validated |
| **Required on every login** | Yes |
| **SMS option** | Not used / not offered on enrollment screen |
| **Passkey option** | Available but not configured |

### Important note for the account owner

A new authenticator enrollment was created during this session. To log in going forward you need the TOTP codes from the authenticator app that was paired with device **`CursorAgent-1783044250`**. If you do not have that authenticator saved, use **My Account → Multi-Factor Authentication** (from the apps splash page) to add a new device or re-enable an existing one.

---

## 3. Post-login navigation (Apps Splash)

After successful MFA validation, Genesys shows the **Genesys Cloud Apps** splash (`#/splash`) with three tiles:

| Tile | Description |
|------|-------------|
| **My Account** | Account settings, MFA device management |
| **Collaborate/Communicate** | Main contact center app (admin, queues, campaigns) |
| **Architect** | Call flow designer (outbound flows) |

**Correct path to admin:** Click **Collaborate/Communicate**, then use **Admin** in the left navigation.

**Organization context:** Org slug is `globalalliancestests` (seen on org login page at `#/authenticate-adv/org/globalalliancestests`).

### Screenshot

- Apps splash: `artifacts/screenshots/02d_post_validate.png`

### Blocker encountered

An automated navigation mistake clicked **My Account** instead of **Collaborate/Communicate**. Direct navigation to `https://apps.mypurecloud.com/directory/#/admin/...` then redirected back to the org login page (`globalalliancestests`), indicating the org-scoped session cookie was not established.

---

## 4. Navigation path to outbound / agentless campaigns

Could not confirm live UI labels in this org (admin not reached). Based on Genesys Cloud standard navigation and documentation:

### Primary UI path

```
Login → MFA → Collaborate/Communicate
  → Admin (left nav)
    → Outbound (or Campaign Management)
      → Campaigns
        → Create New
          → Dialing Mode: Agentless Dialing
```

### Direct admin URLs (after org session is active)

| Page | URL |
|------|-----|
| Admin home | `https://apps.mypurecloud.com/directory/#/admin/welcome` |
| Campaign Management | `https://apps.mypurecloud.com/directory/#/admin/campaignManagement/campaigns` |
| Contact lists | `https://apps.mypurecloud.com/directory/#/admin/campaignManagement/contactLists` |
| Outbound settings | `https://apps.mypurecloud.com/directory/#/admin/outbound/settings` |
| Call Analysis Responses | `https://apps.mypurecloud.com/directory/#/admin/outbound` (CARS section) |
| Phone trunks | `https://apps.mypurecloud.com/directory/#/admin/telephony/phoneTrunks` |
| Architect outbound flows | `https://apps.mypurecloud.com/architect/#/architect/flows` |

### Reference documentation

- [Create an agentless campaign](https://help.mypurecloud.com/articles/create-agentless-campaign/)
- [Dialing modes (Agentless)](https://help.genesys.cloud/articles/dialing-modes/)
- [Outbound flows overview](https://help.genesys.cloud/articles/outbound-call-flows/)

---

## 5. Agentless dialing configuration steps (from Genesys docs)

Agentless campaigns do **not** use agents. They dial a contact list and route live answers / voicemail per a **Call Analysis Response Set (CARS)** to an **Architect outbound flow**.

### Prerequisites (all required unless noted)

| # | Resource | Required | Notes |
|---|----------|----------|-------|
| 1 | **Architect outbound flow** | Yes | Handles live party / AM actions (play audio, transfer to queue, disconnect) |
| 2 | **Call Analysis Response Set (CARS)** | Yes | Must include **Transfer to Flow** action; cannot transfer directly to agents |
| 3 | **Contact list** | Yes | CSV with phone column(s); can create inline during campaign setup |
| 4 | **Edge Group or Site** (Dialing Group) | Yes | Provides outbound trunks/lines |
| 5 | **Wrap-up code** | Yes | Required by outbound flow defaults |
| 6 | DNC list | Optional | Numbers never to dial |
| 7 | Callable time set | Optional | Requires timezone column in contact list |
| 8 | Caller ID name/number | Optional | Compliance-dependent |
| 9 | Division / permissions | Optional | User needs Outbound Campaign admin permissions |

### Recommended setup order

#### Step A — Create outbound flow (Architect)

1. Admin → **Architect** (or apps splash → Architect)
2. Create **Outbound Flow**
3. Add tasks (e.g. **Play Audio on Silence** for voicemail, **Transfer to Queue** for live answer)
4. Set default contact list + wrap-up code in flow settings
5. **Publish** the flow

#### Step B — Create Call Analysis Response Set

1. Admin → **Outbound** → **Call Analysis Responses**
2. Create new response set
3. Configure actions:
   - **Live voice** → Transfer to Outbound Flow (select flow from Step A)
   - **Answering machine** → Transfer to Flow (same or different) or Hang Up
4. Save (cannot use response sets that transfer to agents for agentless campaigns)

#### Step C — Create contact list with test number

1. Admin → **Campaign Management** → **Contact Lists** → **Create**
2. Upload CSV or create list with column e.g. `Cell` or `Phone`
3. Include record: `+17149570044` (E.164 recommended)

Example minimal CSV:

```csv
FirstName,Phone
Test,+17149570044
```

#### Step D — Create agentless campaign

1. Admin → **Campaign Management** → **Campaigns** → **Create New**
2. **Campaign Name:** e.g. `Test-Agentless-7149570044`
3. **Dialing Mode:** `Agentless Dialing`
4. **Outbound Lines Distribution:** e.g. `1` for a single test call
5. **Dialing Group:** Edge Group or Site (must have outbound capacity)
6. **Call Response:** Select CARS from Step B
7. **Contact List:** Select list from Step C
8. **Caller ID** (optional): set compliant outbound caller ID
9. **No-answer timeout:** 15–60 seconds (default 30)
10. **Save**

#### Step E — Start campaign

1. On Campaign Management page, select campaign
2. Click **Start** / set status to running
3. Monitor campaign stats for dial attempts to +17149570044

---

## 6. Errors and missing prerequisites (observed + expected)

### Observed during this session

| Blocker | Detail |
|---------|--------|
| MFA enrollment required | Account had no active MFA; setup was mandatory before apps access |
| Org session not established | Direct admin URLs redirected to org login without completing Collaborate/Communicate entry |
| IP connectivity loss | After repeated automated logins, `login.mypurecloud.com` began returning `ERR_CONNECTION_RESET` / TLS reset — prevented completing admin exploration |
| Test call not placed | Never reached campaign management UI |

### Expected prerequisites to verify in `globalalliancestests` org

These could not be validated in the UI but commonly block agentless campaigns:

| Area | What to check |
|------|----------------|
| **Permissions** | Role includes Outbound Campaign configuration (e.g. Admin or Outbound Admin) |
| **Telephony / Edge** | Edge Group or Site with outbound trunk lines provisioned |
| **Outbound licenses** | Org licensed for Outbound Dialing |
| **Compliance** | Callable times, DNC, caller ID, abandonment rules for your use case |
| **Architect** | Published outbound flow exists |
| **CARS** | Response set with Transfer-to-Flow (not Transfer-to-Agent) |

---

## 7. Test call to +17149570044

| Item | Status |
|------|--------|
| Contact list created with number | **No** |
| Agentless campaign created | **No** |
| Campaign started | **No** |
| Call initiated | **No** |

**Conclusion:** A test call to **+17149570044 was not possible** in this session because the admin console was never accessed and the full outbound pipeline (flow → CARS → contact list → campaign → Edge trunks) was not configured.

---

## 8. Recommended next steps (manual)

1. Log in at https://login.mypurecloud.com with email/password.
2. Enter TOTP code from authenticator for device **`CursorAgent-1783044250`**.
3. On apps splash, click **Collaborate/Communicate** (not My Account).
4. If prompted, complete org login for **`globalalliancestests`**.
5. Open **Admin → Campaign Management → Campaigns** and verify permissions.
6. Confirm **Admin → Telephony → Phone Trunks** / Edge groups have outbound capacity.
7. Follow Steps A–E in Section 5 to build and start a one-line test campaign for +17149570044.

---

## Screenshot index

All screenshots: `/workspace/artifacts/screenshots/`

Key files:
- `01_login_page.png` — Login
- `02a_mfa_setup.png` — MFA enrollment
- `02b_mfa_qr.png` — QR / TOTP validation
- `02d_post_validate.png` — Apps splash (post-MFA success)
- `20b_after_password.png` — MFA verification on subsequent login
- `30_admin.png` — Org re-login page (admin URL without org session)
