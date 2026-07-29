# Report 3 — Legal, Privacy and Evidentiary Framework

**Date:** 29 July 2026

> **Verification grading.** **[A]** = corroborated across multiple sources ·
> **[B]** = single reliable source · **[X]** = could not verify.
> Research ran behind an egress proxy that blocked `almeezan.qa` (Qatar's
> official legal portal), `assurance.ncsa.gov.qa`, `caa.gov.qa` and
> `eur-lex.europa.eu`, and the search budget was exhausted. **No primary legal
> text was read.** This is not legal advice; nothing here should enter a
> submission without verification against Arabic-authoritative primary text by
> Qatari counsel.

---

## 1. Two findings that change the plan

### 1.1 🔴 A drone law was enacted ten days ago, and it blocks the drone concept as designed

**Qatar Law No. (10) of 2026 on the Regulation of Unmanned Aircraft**, Official
Gazette issue 12/2026, published ~**19 July 2026** **[A — corroborated across
Gulf Times, The Peninsula, Zawya, Qatar Tribune]**. Path: Cabinet approval Jan
2025 → Shura Council Feb 2026 → published July 2026.

- **Blanket licensing prohibition [A]:** it is prohibited to design,
  manufacture, assemble, modify, maintain, inspect, import, export, trade,
  **operate**, rent or train on drones without licence. A drone-in-a-box
  deployment plausibly triggers *operate*, *maintain*, *import* and possibly
  *modify* — potentially several separate licence classes.
- **Penalties [A on magnitude]:** up to **7 years' imprisonment and/or
  QAR 300,000**; a second tier to QAR 200,000; licence suspension and entity
  closure as administrative sanctions.
- **BVLOS appears not permitted** for civil operators; daylight VLOS only
  **[C — consistently reported, low-grade sources, pre-dating this law]**.
- **Autonomous / docked / drone-in-a-box operation: no rule found at all [X].**
  QCAA's own terminology is **"RPAS" — Remotely *Piloted* Aircraft System** — a
  framework that may have no category for an unattended docked drone.
- **Implementing regulations almost certainly do not exist yet [X]** — the law
  is ten days old.
- **Overflight of public roads / populated areas: no rule found [X].**

**Forward signal [A]:** QCAA has tendered a national **UTM** system for the
Qatar Air Traffic Control Center, explicitly framed as feeding into "updating
and enhancing regulations." **BVLOS liberalisation is plausibly gated on UTM
go-live** — model your timeline against that procurement, not the law's
publication date.

**Also note the deconfliction risk.** QCAA's Jan 2025 UTM workshop included the
Ministry of Defense, MOI and Customs **[A]**. Qatar operates counter-UAS
capability. An improperly deconflicted autonomous drone faces kinetic risk, not
merely enforcement risk.

**Conclusion: do not commit capital assuming autonomous nest operation is
permitted in Qatar. On present evidence it is not, and the waiver pathway is
unverified.** Build the fixed tower; treat the drone as a phase gated on a
written QCAA answer. Three questions to `UAS@caa.gov.qa`, in order: (a) is
BVLOS approvable and by what pathway; (b) is autonomous/docked unattended
operation recognised at all; (c) which licence classes under Law 10/2026 apply
to an operator that imports, maintains and operates a fixed docked system.

### 1.2 🔴 Correction: biometric data is *not* a special category under Qatar's PDPPL

**I got this wrong earlier and have corrected the code comment in
`speeddet/privacy.py`.**

**PDPPL "personal data of special nature" [A]:** ethnic origin; children;
health / physical or psychological condition; religious creeds; marital
relations; criminal offences. **Biometric data does not appear.**

The special-category treatment of biometrics belongs to the **Qatar Financial
Centre Data Protection Regulations 2021** — a GDPR-aligned regime applying
**only inside the QFC**. Secondary sources conflate the two constantly, and I
repeated the error.

**What this changes:** face processing on Qatari public roads likely falls
**outside** the special-nature regime and its prior-permission gate — a
*lighter* statutory touch than GDPR.

**What it does not change:** the recommendation to keep face *recognition* off
the tower. That still rests on three independent grounds — it does not work at
that geometry, the plate already solves the problem more accurately, and a
roadside cabinet is a bad place for a biometric database. A gap in the law is
not a safe harbour; the regulator may fill it by guidance, and I could not read
the *Guidelines for Special Nature Processing* (v3.0, April 2025) to check
whether it already has **[X]**.

---

## 2. The evidentiary architecture — your strongest defensible position

**[A — the best-sourced conclusion in this report.]**

There is **no metrology standard anywhere that governs AI *behaviour*
classification.** OIML R91, UK Home Office Type Approval, NMi/PTB certification
and Australian pattern approval all govern **measurement of a physical
quantity** — speed, distance, time. None covers deciding whether a hand holds a
phone or a belt crosses a torso.

The consequence:

> **In every operating programme worldwide, the evidentiary source for a
> behaviour violation is the authorised human reviewer, not the algorithm.**
> The AI is a triage filter; what is tendered is the officer's assessment of
> the image.

This is why New South Wales — the world's most mature mobile-phone and seatbelt
camera programme — **has never published a false-positive rate and does not need
to.** The absence is architectural, not evasive.

**Three consequences:**

1. **Your Class A / Class B / Class C split is the legally required
   architecture, not a preference.** Class B (seatbelt, phone, littering)
   carries `requires_review=True` with no path to an automatic citation. That
   is what NSW does and what the absence of a behaviour metrology standard
   demands. Defend it on regulatory grounds.
2. **Keep speed strictly separate.** Speed *is* a measurable physical quantity
   with an established metrology regime. Calibrated instrument, surveyed
   homography, Doppler corroboration, documented re-verification. Contaminating
   the speed path with un-type-approved AI forfeits the one capability that can
   be certified.
3. **Any vendor claiming "99% accurate, so you can automate the citation" is
   misinformed or misleading you.** The claim is unverifiable and legally
   beside the point.

Qatar's own unified radar system is described as "fully automated **until human
verification**" **[B]** — the human step is already in the local model.

---

## 3. Qatar data protection — current state

- **Regulator has migrated [A]:** Compliance and Data Protection Department
  (CDP) under MOTC → **National Data Privacy Office (NDPO)** within the
  **National Cyber Security Agency (NCSA)**. Any material citing "CDP/MOTC" is
  dated.
- **Enforcement is now real [A]:** a compliance ruling against an ICT company
  (Dec 2024), an order against an e-commerce operator (Mar 2025), individuals'
  rights guidance (Apr 2026), a cloud privacy assessment tool (Apr 2026), and
  further personal-data frameworks (Jun 2026).
- **Penalties [B]:** up to **QAR 5,000,000** for the more serious tier
  (including failure to implement appropriate technical and organisational
  measures); up to **QAR 1,000,000** for others, including breach-notification
  failure. **Breach notification: 72 hours [A].**
- **Guidelines suite [A]** exists by document code, covering privacy by design,
  DPIAs, RoPA, privacy notices, breach notification and individuals' rights.

### 🔴 The decisive unresolved question **[X]**

**Does the PDPPL bind the Ministry of Interior?** Most Gulf data-protection
statutes carry a state-security or law-enforcement exemption. **If MOI is
exempt, the entire privacy analysis for a police-operated tower changes
character** — compliance becomes contractual and political rather than
statutory. This is the first question to answer and I could not answer it.

Also unresolved **[X]**: any PDPPL provision on automated decision-making or
profiling; any CCTV-specific NDPO guidance; retention rules.

---

## 4. Enforcement authority and the commercial structure

**[Partially researched — the search budget expired here.]**

- **MOI General Directorate of Traffic** operates enforcement, and **has used
  drones over public roads since October 2022** to detect violations **[A]** —
  peak-hour truck movements, unsecured loads, lane discipline. So MOI already
  flies drones for traffic purposes.
- **A new Qatari traffic law was before the Shura Council in February 2026
  [B]** — potentially highly material, not pursued.
- **Not established [X]:** the current traffic law number; the legal basis for
  automated citations; evidentiary rules; the contest procedure.

**Strategic read: MOI is not a neutral regulator here — it is an incumbent
operator of the exact capability being sold.** The realistic structure is
almost certainly **supplier-to-MOI**, not independent private operator. Whether
a private company may lawfully *operate* enforcement cameras (as opposed to
supply them) is unverified and is the commercially decisive question.

Saudi Arabia offers a directly relevant precedent **[A]**: its **Security
Surveillance Cameras Law (Royal Decree M/34)** requires **prior MoI approval to
manufacture, import, sell, install, operate or maintain** security cameras —
vendor market entry is gated at the ministry. Saher itself was financed and
operated on a **private finance initiative** model **[B]**, which is a useful
structural precedent for a vendor-operated deployment under ministry authority.

**[X] Not researched:** Qatar's CCTV/security-camera law (I could not confirm
that the commonly-cited "Law No. 9 of 2011" exists and will not repeat the
number as fact), and the **2022 FIFA World Cup facial-recognition deployment at
the Aspire Command and Control Centre** — your most directly relevant domestic
precedent, and the largest single gap in this report. I deliberately wrote
nothing from memory there.

One incidental signal **[C]**: Qatar operates a **separate MOI approval regime
for CCTV installation**, which an enforcement tower would likely trigger *in
addition to* the QCAA aviation track.

---

## 5. If you ever sell into the EU

**[A — heavily corroborated, and it inverts the expected timeline.]**

**Regulation (EU) 2026/1744** ("Digital Omnibus on AI") amended the AI Act;
published in the OJ 24 July 2026, **in force 27 July 2026 — two days ago.**

| Obligation | Original | **New** |
| --- | --- | --- |
| High-risk, stand-alone Annex III | 2 Aug 2026 | **2 December 2027** |
| High-risk, AI in Annex I products | 2 Aug 2027 | **2 August 2028** |
| Art. 50 transparency | 2 Aug 2026 | unchanged |

**The critical nuance: the Article 5 prohibitions were NOT deferred.** They have
applied since 2 February 2025. So the constraint that actually bites a biometric
surveillance tower — the **real-time remote biometric identification
prohibition** — is **live now**, while the high-risk compliance machinery is
~17 months away. It is easy to get this exactly backwards.

**[X] Not researched:** Art. 5(1)(h) scope and exceptions; Annex III points
1/2/6 and the road-traffic safety-component wording; the **Art. 6(3)
non-significant-risk filter** (pivotal to whether a speed camera is high-risk at
all); provider vs deployer duties; Art. 27 FRIA; GDPR Arts. 6/9/22/35; and the
**Law Enforcement Directive 2016/680**, including the administrative-vs-criminal
traffic-offence question, which is the most consequential open scoping issue.

---

## 6. Training-data provenance — the exposure most vendors ignore

**[A — see Report 2 for the full audit.]**

- **Copyright.** The public traffic/accident corpus is overwhelmingly
  research-only, unlicensed, or scraped from YouTube by authors who never owned
  the footage. Government contracts routinely carry IP-indemnity clauses; a
  model trained on VeRi-776, BoxCars, 100-Driver or AUC breaches both the
  dataset terms and your customer contract.
- **The consent-scope problem, which survives a negotiated licence.** The
  100-Driver paper states its subjects "signed a GDPR informed consent to allow
  the data to be publicly available for **research study**." Buying a commercial
  licence from the university would not cure that — *the subjects* did not
  consent to commercial deployment. Copyright permission and data-protection
  permission are separate gates.
- **Anonymisation.** Essentially none of the corpus is anonymised. VeRi-776
  ships transcribed plate strings; Open Images annotates a plate class.

**Mitigation: maintain a data bill of materials** — per source: origin, licence
text, date obtained, commercial-use determination, anonymisation status, consent
scope. When a procurement officer asks where the training data came from, that
document is the answer. Most vendors cannot produce one.

Note also an **export-control** angle: the AI City Challenge dataset licence
carries an explicit US BIS/sanctions clause, directly relevant to a Gulf
customer.

---

## 7. What the build already does

| Control | Implementation |
| --- | --- |
| Data minimisation | Events leave the tower, not raw video; `retention_days_raw = 0` |
| Redaction by default | Faces and pedestrians blurred in stored evidence |
| Retention clock | 30d unactioned / 365d actioned, enforced by sweep |
| Identity boundary | No face database, no embeddings; default resolver **refuses** |
| Audit | Hash-chained log; `verify()` fails on any edit or deletion |
| Access control | CCTV sessions named, justified, expiring in 10 minutes |
| Drone restraint | Auto-response **off** by default; hard mission time cap; interlocks re-checked in flight; every launch audited |
| Review gate | Class B events carry `requires_review`; no auto-citation path |

---

## 8. Priority checklist

1. **Does the PDPPL bind MOI?** Answer this first — it determines everything.
2. **Obtain the Arabic text of Law No. 10 of 2026** (Gazette 12/2026) and have
   it professionally translated. Qatari legal texts are Arabic-authoritative;
   English press summaries are not citable.
3. **Write to QCAA** with the three drone questions in §1.1. Do not assume
   autonomous or BVLOS operation is available.
4. **Research the 2022 World Cup FRT precedent** — the largest gap here.
5. **Confirm whether a private company may operate, versus supply,** enforcement
   cameras in Qatar.
6. **Confirm the CCTV/security-camera regime** and its MOI approval track.
7. **Drop the optional microphone array** from the sensing head unless counsel
   identifies a clear basis — audio is treated far more strictly than video in
   most regimes.
8. **Read the NDPO Special Nature Processing guideline** to check whether the
   regulator has extended the biometric category by interpretation.
