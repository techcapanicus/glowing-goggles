# Outbound Stuck Interaction Diagnosis

## Symptom
Agentless campaign dials `+17149570044` but contact gets `ININ-OUTBOUND-STUCK-INTERACTION` instead of a clean completion (`ININ-OUTBOUND-TRANSFERRED-TO-FLOW` or `ININ-OUTBOUND-DISCONNECT`).

## Root Causes Found

### 1. Outbound flow configuration (FIXED)
- Original flow waited for DTMF ("press 9") or speech ("hello/hi/yes") before disconnecting.
- Flow was bound to wrong contact list (`Richards March Campaign`) while campaign used a different list.
- Agentless requires `transfer_flow` on person in CARS; plain `transfer` is invalid.

### 2. Contact list ownership (FIXED)
- Re-dialing same number within 4 hours from another campaign returns `OUTBOUND-SKIPPED-CONTACT-NO-OWNERSHIP`.
- Fix: use a fresh contact list per test run.

### 3. Telephony / timing (LIKELY REMAINING BLOCKER)
- No outbound conversation records appear in analytics despite `lastAttempt` on contacts.
- Attempts run ~2 minutes then disposition as STUCK; `outstandingCalls` briefly = 1.
- `+17149570044` is area code **714 (Pacific)**. Org automatic timezone mapping restricts calling to roughly **8:00–21:00 local**. Tests ran around **05:00–06:00 UTC (~10–11 PM Pacific)**, outside callable hours.
- If the callee does not answer or the edge cannot complete AMD→flow transfer, the dialer may never receive a final wrap-up → STUCK.

## Fixes Applied

| Component | Before | After |
|-----------|--------|-------|
| **Flow** `CursorOutboundPub-20260703-0435` | Menu waits for speech/DTMF; wrong contact list | **v8.0** task: Play message → Set wrapup `Best` → Disconnect |
| **Flow contact list** | Richards March Campaign | Matches campaign list (e.g. `CursorDial-*`) |
| **CARS** | `callable.person` = `transfer` | `disposition.classification.callable.person` = `transfer_flow` |
| **Campaign** | Single-use stuck contacts | Fresh contact list + force-stop between runs |

## Current Published Resources

- **Flow:** `CursorOutboundPub-20260703-0435` (`b05d6954-e241-4364-b39e-65dda2e3a9fe`) — published **v8.0**
- **Latest test campaign:** `CursorDial-20260703-060436` (`6dfe7712-656b-4d6a-8b0d-cfabc6a9e938`) — stopped
- **Latest contact list:** `CursorDial-20260703-060436` (`9ea21ff5-14ee-4e79-9cc3-fac4a392b597`)
- **Test number:** `+17149570044` — last result still `ININ-OUTBOUND-STUCK-INTERACTION`

## Resolution (2026-07-03)

**Working configuration found** after exhaustive testing (~30+ variants).

| Setting | Failing configs | **Working config** |
|---------|-----------------|-------------------|
| **Telephony** | `edgeGroup: PureCloud Voice - AWS` | **`site: PureCloud Voice - AWS`** (`5168bf49-a042-449b-8cdf-290b0d6e9fdd`) |
| **noAnswerTimeout** | 90 (invalid) | **30** |
| **alwaysRunning** | true (many tests) | **false** |
| **CARS person** | transfer_flow → flow v8 | transfer_flow (same) |
| **Result** | `ININ-OUTBOUND-STUCK-INTERACTION` | **`ININ-OUTBOUND-DISCONNECT`** |

### Successful run

- **Campaign:** `WinReplay-f76da4` (`086ec21d-fd64-4589-830f-befd3ddcc0fb`)
- **Contact list:** `WinReplay-f76da4` (`732100f9-d221-4ba1-9ccf-436764283822`)
- **Number:** `+17149570044`
- **Result:** `ININ-OUTBOUND-DISCONNECT` on poll 1 (~14s), campaign `complete`
- **Script:** `/workspace/genesys_replay_winner.py`

### Why edge group failed but site worked

Campaigns bound to the **edge group** placed calls that stayed `outstanding=1` for ~2 minutes then dispositioned as **STUCK**. Campaigns bound to the **PureCloud Voice - AWS site** complete in seconds with clean disconnect. The org's BYOC outbound route is on the **Branch** site, but agentless dialing succeeds via the **managed PCV site**, not the edge group reference.

### Direct API dial (alternate path)

`POST /api/v2/conversations/calls` accepts the request (HTTP 202) and targets `tel:+17149570044`, but terminates with `error.ininedgecontrol.connection.timeout` after ~60s. Agentless via PCV site is the reliable path.

## Recommended Next Steps

1. **Use site `PureCloud Voice - AWS`** for agentless campaigns (not edge group).
2. Re-run `/workspace/genesys_replay_winner.py` for confirmation with a fresh contact list.
3. For live-answer / flow-transfer testing, answer the phone when it rings during Pacific callable hours.
4. If `TRANSFERRED-TO-FLOW` is required (not just DISCONNECT), ensure callee answers so AMD classifies as **person**.

## Working YAML Pattern (flow v8)

See `/workspace/artifacts/flow_task_seq.yaml` — task startup with sequential `playAudio` → `setWrapupCode` → `disconnect`, contact list name substituted per campaign.
