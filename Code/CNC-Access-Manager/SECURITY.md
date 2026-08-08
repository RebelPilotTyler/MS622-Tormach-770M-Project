# Security notes — CNC Access Manager

Written after the cybersecurity review Tyler brought back from **Dr. Pacote**
(class of 30 July 2026). This file records *which* protection each stored field
gets and *why*, so the next person to touch the code does not have to guess.

---

## The rule we are applying

> Encryption is two-way. Hashing is one-way.
> Hash the things you only ever need to **compare**.
> Encrypt the things you need to **read back**.

Getting this backwards is the common mistake in both directions: hashing a card
UID would make it impossible to match a tap, and encrypting a PIN would mean a
stolen key hands over every PIN in the building.

---

## What each field gets

| Field | Protection | Why |
|---|---|---|
| User PIN | **Hashed** — PBKDF2-HMAC-SHA256, 100,000 rounds, random 16-byte salt per user | We only ever ask "does the PIN they typed match?" A 4-digit PIN has 10,000 possibilities, so a plain SHA-256 would be reversible with a lookup table in under a second. The salt makes each user's hash unique and the 100k rounds make bulk guessing expensive. |
| Admin password | **Hashed** — PBKDF2-HMAC-SHA256, 100,000 rounds | Same reason. Until v1.4 this was a bare unsalted SHA-256, which is exactly the weakness v1.3 fixed for PINs but left in place here. |
| Offline verifier | **Hashed** — single HMAC-SHA256 keyed by `OFFLINE_KEY` | The Pico cannot run 100k PBKDF2 rounds; that is minutes per card tap. This is a deliberately cheaper, deliberately weaker second verifier, consulted **only** when the server is unreachable. See "Known trade-offs" below. |
| **Card UID** (`rfid_hex`) | **Encrypted** — Fernet (AES-128-CBC + HMAC-SHA256) | The server has to recover the real UID to match a tapped card, so a hash is the wrong tool. It is encrypted because RFID cards are clonable by design — the card answers any reader that asks — so a list of authorised UIDs is the most damaging thing in the database. |
| **User name** | **Encrypted** — Fernet | Personal data that has to be displayed on the Logs page, so again it must be recoverable. |
| Card lookup index | **Hashed** — keyed HMAC-SHA256 (a "blind index") | Encrypted values cannot be searched, so each card also stores a deterministic keyed hash in `rfid_hex`. `WHERE rfid_hex = ?` is still one indexed query, but the index itself reveals nothing. |
| Access / event log timestamps and notes | Plaintext | Not sensitive on their own, and they are the audit trail — the whole point is that they are readable. |

---

## Key management

The Fernet key is read, in order, from:

1. the `CNC_SECRET_KEY` environment variable, or
2. `secret.key` sitting next to `cnc.db`.

It is created automatically **only** on a database with nothing encrypted in it
yet. The server refuses to start, rather than damaging data, if:

- the database has encrypted rows and no key can be found,
- the key that *is* found does not decrypt the database (wrong install's key),
- the database has encrypted rows but `cryptography` is not installed.

Back the key up somewhere other than beside `cnc.db` — a backup that contains
both is a backup with no encryption.

---

## Encryption is an optional dependency, on purpose

`cryptography` is not in the Python standard library, and one of this project's
real advantages is that `server.py` runs on any machine with Python and nothing
else. So encryption degrades instead of breaking: without the package installed
the server starts, prints a clear warning, and behaves exactly as v1.3 did.
PINs and the admin password are still hashed either way, because those use
`hashlib`, which *is* standard library.

Turn it on with:

```
pip install cryptography
```

---

## Known trade-offs, stated plainly

- **The offline verifier is weaker than the online one.** One HMAC round instead
  of 100,000. It is only reachable when the server is unreachable, and it exists
  so that a sleeping laptop does not take a $30,000 mill out of service. Accepted
  and documented rather than hidden.
- **The reader still gets enough to authorise offline.** `/api/roster` no longer
  sends real card UIDs or names — only a hashed card id and the offline verifier
  — so a stolen Pico gives up a list of hashes, not a list of clonable cards.
  But anyone holding the Pico also holds `OFFLINE_KEY`, so they could test
  guesses against that list offline. Rotating `OFFLINE_KEY` off its default is
  still an open task.
- **The API is HTTP, not HTTPS.** Everything runs on the shop LAN. On a network
  where someone can sniff traffic, a PIN is visible in the `/api/verify` request.
  This is the largest remaining gap and the next thing worth fixing.
- **`DEVICE_KEY` and `OFFLINE_KEY` still ship with default values.** They must be
  changed before the lab demo. `DEVICE_KEY` can already be set through the
  `CNC_DEVICE_KEY` environment variable.

---

## Not claimed

This is a student project protecting a machine in a monitored lab, not a bank.
The realistic threat is a student who wants to run the mill without being
recorded, not a determined attacker. As the professor put it in class: the goal
is to make it more effort than it is worth, and no security effort is ever
foolproof.
