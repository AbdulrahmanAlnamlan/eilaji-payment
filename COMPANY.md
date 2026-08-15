# Eilaji — AI Company OS

A weekly operating doc, run department by department. **You are the owner and the
final decision-maker.** Nothing here is sent, spent, or shipped without you.

> Everything below is drawn from what is actually in this repository. Where a
> department needs information only you have, it says so instead of guessing.
> **No revenue, traffic, or performance figures appear in this document**,
> because none exist in the repo.

---

## What the repo actually tells us

| Fact | Source |
| ---- | ------ |
| Product: Eilaji (علاجي) — a medication reminder app | `index.html` copy |
| Features sold: alarm-style dose reminders, missed-dose follow-up, appointment alerts, unlimited medicines, Arabic+English, 30-day history | `index.html` feature list |
| Market: Qatar first, "Proudly Made in Qatar"; 50 country codes in the picker, GCC listed first | `index.html` `COUNTRIES` |
| Pricing: QAR 29/month, QAR 75/3 months, QAR 199/year | `PLANS` in `api/create-charge.js` |
| Positioning: 3-month plan is the "Most Popular" default | `index.html` |
| Payments: Tap Payments, QAR, 3-D Secure on, `src_all` (Visa, Mastercard, Apple Pay, KNET, mada) | `api/create-charge.js` |
| Hosting: Vercel, `eilaji-payment.vercel.app` | `vercel.json`, repo homepage |
| Contact: alnamlan013@gmail.com | `index.html` footer |
| App handoff: `eilaji://` deep link after payment | `index.html` |

**Unknowns you'd need to fill in:** subscriber count, revenue to date, refund/
chargeback rate, app-store status, marketing channels in use, whether the app
enforces the subscription at all (nothing in this repo tells the app who paid).

---

## 1. CEO — priorities

**This week's top 3, in order.**

**P1 — Rotate the exposed live Tap key. (Owner: you, today.)**
The live secret key `sk_live_Hc3XoBk1eLWip0j7OQRdEICA` was committed to this
**public** repository and sits in at least 8 commits of history. Code changes
alone do not fix this — the key is already public and must be revoked in the Tap
dashboard. Everything else waits behind this. *Department: Engineering advises,
you execute in the Tap dashboard.*

**P2 — Close the "free premium" hole. (Owner: Engineering — done in this branch,
pending your review.)**
The old success screen trusted `?success=1` in the URL, and the price came from
the browser. Both are fixed here; they need your review and deploy.

**P3 — Decide how the app learns who paid.**
This repo takes money but has no database and no webhook. Nothing connects a
captured charge to a user account in the Eilaji app. Until that exists, entitlement
is manual. *This is a product decision I need from you before Engineering builds it.*

**Risky / uncertain — flagged:**
- A medication reminder app touches health. Marketing copy must not drift into
  medical claims, and you may have health-data obligations in Qatar. **Get a real
  lawyer** — I am not one.
- Tap is a real payment processor with real merchant obligations. Refund and
  chargeback handling is not in this repo at all.
- The footer says "Cancel anytime," but nothing in this repo creates a recurring
  subscription or a way to cancel. See Support, below.

---

## 2. Engineering — what was built and fixed

Delivered in this branch (details in the commit and `README.md`):

| Fix | Before | After |
| --- | ------ | ----- |
| Secret key | Hardcoded `sk_live_...` in source | `process.env.TAP_SECRET_KEY` |
| Price | Sent by the browser (`amount: plan.price`) | Server-side `PLANS` table |
| Success screen | Shown on `?success=1` alone | Verified with Tap; only `CAPTURED` passes |
| Verify endpoint | `api/verify payment` — space in name, no `.js`, never deployed, unreachable, and using a *test* key against *live* charges | `api/verify-payment.js`, deployed, wired to the front end |
| CORS | `Access-Control-Allow-Origin: *` on a payment endpoint | Origin allowlist |
| Logging | Full name, email, phone, and charge object logged | PII no longer logged |
| Error responses | Raw Tap payload returned to the browser | Generic message; detail logged server-side |
| Redirect URL | Carried customer email in the query string | Carries only `success=1` |
| Missing plan metadata | `verify` read `metadata.plan`, `create` never set it | Set on charge creation |

**Verified, not assumed:** 15 checks run against mocked Tap responses — price
tampering blocked (yearly stays 199 even when the client claims 1), unknown plans
rejected, invalid email/phone rejected, foreign origins refused CORS, path-traversal
charge IDs rejected, `CAPTURED` vs `INITIATED` distinguished, and neither a missing
key nor a Tap error leaks anything key-shaped to the browser. All 15 pass.

**Not done — needs your decision (P3):**
- A Tap **webhook** endpoint. Redirect-based verification breaks if the customer
  closes the tab after paying. A webhook is the only reliable record.
- A datastore. Currently a successful payment is confirmed and then forgotten.
- Real recurring billing. Tap charges here are one-off.

---

## 3. Marketing — drafts for your review

**Audience (from the repo):** Arabic-speaking adults in Qatar and the GCC managing
daily medication — for themselves or for a parent.

**Voice observed in your own copy:** plain, warm, concrete, benefit-first. "Never
miss a dose again." No hype. Drafts below match it.

**5 content ideas (no fabricated stats — none of these cite numbers):**
1. The 30-second setup — screen recording of adding a medicine and its alarm.
2. "Silent mode won't silence it" — the one feature reminder apps usually get wrong.
3. Caregiver angle: setting up reminders for a parent who lives with you.
4. Ramadan / travel dose timing — how people actually shift their schedules.
5. What the 30-day history looks like, and why "did I take it?" is the real problem.

**Draft post (Instagram/X, Arabic + English):**

> **AR:** نسيت جرعتك؟ علاجي ينبّهك بصوت إنذار حقيقي — حتى لو جوالك على الصامت.
> وإذا فاتتك الجرعة، يذكّرك مرة ثانية بعد ٣٠ دقيقة.
> تنبيهات للمواعيد الطبية، أدوية غير محدودة، وسجل ٣٠ يوم. عربي بالكامل.
>
> **EN:** Missed a dose? Eilaji alerts you with a real alarm — even on silent.
> Miss it anyway, and it follows up 30 minutes later. Appointment alerts,
> unlimited medicines, 30-day history. Fully bilingual.

*Every claim above is a feature listed on your own page. Nothing is invented.*
**Do not** add "doctor recommended," "clinically proven," or adherence statistics
unless you have a real source — that is a medical claim.

---

## 4. Sales — draft outreach (you approve before sending)

Given the price point, individual outreach is inefficient. The likelier channel is
**pharmacies, clinics, and elderly-care providers in Qatar** who serve patients on
multi-drug regimens.

**Draft — initial message:**

> Subject: A bilingual medication reminder app for your patients
>
> Hello [Name],
> I built Eilaji, an Arabic/English medication reminder app made in Qatar. It uses
> alarm-style alerts that work on silent, follows up on missed doses, and keeps a
> 30-day history patients can show at a follow-up visit.
> I'm looking for a small number of clinics to try it with patients and tell me
> honestly what's missing. No cost to you, and I'm not asking you to endorse it.
> Would a 15-minute call be useful? [your link]
> — Abdulrahman

**Follow-up 1 (day 4):** one line, reference the specific clinic, re-offer the call.
**Follow-up 2 (day 10):** "Closing the loop — should I stop here?" Then stop.
**Stop immediately on any "no."** Two follow-ups maximum.

*Placeholders `[Name]` and `[your link]` are yours to fill — I don't have a booking
link or a prospect list, and I won't invent either.*

---

## 5. Support — the gap you should look at first

I have no customer messages to reply to. But the repo surfaces a support issue
worth pre-empting:

**Your page says "يمكنك الإلغاء في أي وقت / Cancel anytime," but this repo creates
one-off Tap charges — there is no recurring subscription and no cancel flow.**
Either (a) the wording should change, or (b) recurring billing needs building.
Right now a customer asking "how do I cancel?" has no answer, and a customer
expecting auto-renewal won't get it. **Which is it? I need you to tell me.**

**Reply template once you decide (fill the bracket):**

> شكراً لتواصلك. اشتراكك الحالي [ لمدة X ] ولا يتجدد تلقائياً — لن يُخصم منك أي
> مبلغ إضافي. إذا احتجت تمديد الاشتراك، تقدر تجدده من نفس الصفحة.
>
> Thanks for reaching out. Your current plan runs for [X] and does not auto-renew,
> so nothing further will be charged. You can renew any time from the same page.

*Do not send this until you've confirmed which billing model is actually live.*

---

## 6. Finance — what I can and cannot say

**I have no revenue or cost data. None is in this repo, and I will not estimate it.**

What is factually established from the code:

| Plan | Price | Per month | vs monthly |
| ---- | ----- | --------- | ---------- |
| Monthly | QAR 29 | QAR 29.00 | — |
| 3 months | QAR 75 | QAR 25.00 | 14% less |
| Yearly | QAR 199 | QAR 16.58 | 43% less |

The 14%/43% savings badges on your page are arithmetically correct.

**To do a real finance review, paste me:** Tap settlement totals, Tap's per-transaction
fee, Vercel cost, app-store fees if any, and any ad spend. Then I'll summarize it
using only those numbers.

**Two costs already visible in the code that you should confirm are budgeted:**
3-D Secure is enabled (good for chargebacks, sometimes priced differently), and
`src_all` accepts KNET/mada/Apple Pay — check Tap's rate for each, they usually differ.

*Not financial advice.*

---

## 7. Operations — SOP for the thing that just broke

### SOP: Changing a Tap API key (never commit one again)

1. Open the Tap dashboard → API keys.
2. Copy the key. **Do not paste it into any file in this repo.**
3. Go to Vercel → Project → Settings → Environment Variables.
4. Set `TAP_SECRET_KEY`. Use `sk_test_...` for Preview/Development and
   `sk_live_...` for **Production only**.
5. Redeploy.
6. Test a real QAR 29 charge on production, then refund yourself in the Tap dashboard.
7. Confirm the success screen appears **only** after the charge shows `CAPTURED`.
8. Manually check: open `https://eilaji-payment.vercel.app/?success=1` with no
   `tap_id`. It must show the failure state, not the success screen.

### One thing to automate safely (with a human check)

**Turn on GitHub secret scanning + push protection** on this repository
(Settings → Code security). It blocks a commit containing a key before it is
pushed, which is exactly the failure that happened here. The human check stays:
you still decide what to do when it fires.

*Candidate for later, not now: a Tap webhook writing confirmed charges to a sheet
or database, so Finance and Support both work from real records instead of memory.*

---

## Standing rules for this document

- Real information only. No invented revenue, subscribers, or performance.
- Everything is a draft for your review.
- Nothing is sent, spent, or shipped without your approval.
- Legal and financial questions go to a real professional.
- **You are the final decision-maker.**
