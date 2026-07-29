# Reports and design documents

## The four reports

| # | Report | What it answers |
| --- | --- | --- |
| 1 | [System and Verification](report-1-system-and-verification.md) | What is built, what is actually verified and how, what the tests caught, known limitations |
| 2 | [Data and Models](report-2-data-and-models.md) | The training-data audit, why you cannot lawfully train this on internet data, what was trained instead, the real path to a working model |
| 3 | [Legal, Privacy and Evidentiary](report-3-legal-and-privacy.md) | Qatar data protection, the new drone law, enforcement authority, why the human-review architecture is legally required |
| 4 | [Market and Strategy](report-4-market-and-strategy.md) | Qatar already has this capability; where the real opening is; routes to market |

## Design documents

- [Sentinel Tower](sentinel-tower.md) — the full system vision
- [Radar + drone station](radar-drone-station.md) — roadside hardware design

---

## The five findings that matter most

1. **No public dataset is both roadside-viewpoint and commercially licensed.**
   Waymo's licence names "enforcement, even in part" as excluded. The datasets
   with the right viewpoint have the worst licences. *(Report 2)*

2. **Qatar already operates this capability.** The "Tala'a" network plus the
   unified radar system (live since Sept 2023) already does multi-lane speed,
   seatbelt and phone detection — including mounted phones — feeding a National
   Command Centre with human verification. You are not entering an underserved
   market. *(Report 4)*

3. **A drone law was enacted in Qatar on ~19 July 2026** (Law No. 10 of 2026)
   with a blanket licensing prohibition and penalties to 7 years' imprisonment.
   Autonomous docked operation may not be a recognised category at all. Do not
   commit capital assuming the drone concept is permitted. *(Report 3)*

4. **No metrology standard governs AI behaviour classification anywhere.** The
   evidentiary source is the human reviewer, not the algorithm — which is why
   NSW has never published a false-positive rate. This makes the Class A/B/C
   review-gated architecture legally required rather than merely prudent.
   *(Report 3)*

5. **Qatar's own fatal-crash data has no speeding line item** — it is 49.7%
   negligence/recklessness, 16.8% lane deviation, 12.1% insufficient distance.
   The differentiated product is behavioural and incident analytics, not another
   speed camera. *(Report 4)*

## Corrections made to earlier work

Recorded because the earlier versions were wrong and may have been read:

- **Biometric data is *not* special-category under Qatar's PDPPL.** An earlier
  code comment in `privacy.py` said it was. The special-nature list is ethnic
  origin, children, health, religious creeds, marital relations and criminal
  offences. Biometrics are special-category under the *QFC* regime, which
  applies only inside the Qatar Financial Centre. The recommendation to keep
  face recognition off the tower is unchanged — it rests on three other
  grounds.
- **The China pole-mounted drone precedent was overstated.** An earlier version
  of `radar-drone-station.md` asserted autonomous violation issuance as fact,
  sourced from a social-media clip. What is verifiable is evidence capture with
  humans in the loop. Do not put the autonomous-citation claim in front of MOI.
- **`BN` is the breakdown/recovery truck code and `FD` the flatbed tow** — an
  earlier version had them reversed.
