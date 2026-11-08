# Security report: MITRE ATT&CK and MITRE ATLAS analysis

Written 7 Nov 2026 from the code, not from the older docs. It reads with [SECURITY.md](SECURITY.md) (the threat list and the test behind each) and [KEYS.md](KEYS.md). `uv run brain redteam` was run for this report: 22 passed, 0 failed before the fixes of section 9; 24 of 24 after them.

The Brain is a cyber-physical decision layer with a language-model team inside it. So two frameworks apply. **ATT&CK for ICS** covers the path from sensors to actuators. **ATT&CK Enterprise** covers the web API, the hosts and the supply chain. **ATLAS** covers the AI parts: the agent team, the forward models, the learned rules, the self-tuning and the knowledge base.

Technique IDs were checked on 7 Nov against attack.mitre.org (ICS and Enterprise) and the ATLAS data file. The ICS matrix was renumbered recently: the old T0855 and T0856 are now **T1692** (Unauthorized Message), and Block Command and Reporting Message are **T1691**. ATLAS only lists what was checked; its newest agent techniques (after AML.T0070) are not used because they could not be read.

## 1. Assets and trust boundaries

| Asset | Why it matters |
| --- | --- |
| The actuator call to the Twin (valve, grid, dispatch) | The only thing that changes the city. Wrong calls cost safety. |
| The Guardian's trust verdict | Decides whether a reading may be acted on. |
| Sensor readings | The Brain's whole view of the city. |
| Signing keys, tokens, approval secret | Identity of every peer and every person. |
| The sealed event log and journal | The evidence of what the Brain did and why. |
| Learned rules, tuned parameters, knowledge base | What the Brain carries from one run to the next. |

```
 [Twin]  --B1-->  [Perception] --> [Guardian verdict] --B2--> [Workspace / rules / agent team]
 (partner)        sign, replay,     (partner)                      |        B4 [Groq model]
                  schema, drop                                     v
 [Operator] --B3-> [API edge: token, scope, size, rate]        [Gate: 11 checks] --B5--> [Twin actuator]
 [Partner browser]                                                 |                      (signed, nonce)
                                                       [sealed log + signed head]
```

| Boundary | Crosses it | Trust placed in the far side | What the Brain does about it |
| --- | --- | --- | --- |
| B1 Twin to Brain | Signed readings (HTTP, MCP or MQTT) | None until checked | Signature, key id, expiry, replay counter, schema, allowlisted value fields |
| B2 Guardian to Brain | Verdicts, quarantine answers, retractions | **High: a verdict is taken as given** (see R1) | Schema check; the gate asks for independent sources and a person on high-impact calls |
| B3 People and partners to API | Tokens, pushed events, approvals | Scoped by token | Scope per route, push namespace, size and rate limit, headers |
| B4 Brain to the language model | Briefs out, proposals back | **Untrusted output** | Read-only tools, zones not words, deterministic verifiers, then the gate |
| B5 Brain to Twin actuators | Signed calls | The Twin must verify | `issued_at` and one-time nonce signed with the call; Ed25519 available |
| B6 Brain to its own disk | Log, journal, state, learned rules | Mostly trusted | Hash chain, signed head, bounded tuning surface |

## 2. Attack vectors and protections: ATT&CK for ICS

| Technique | Vector against the Brain | Protection (where) | Proof | Residual |
| --- | --- | --- | --- | --- |
| **T1692.002** Unauthorized Message: Reporting Message | A fake sensor reading, forged or replayed | HMAC-SHA256 or Ed25519 over canonical JSON, then a per-sensor rising `sequence_no` that survives a restart (`perception/__init__.py`) | A1, A2, A3 | A stolen Twin secret forges readings (R8) |
| **T1692.001** Unauthorized Message: Command Message | A forged or replayed call to an actuator; a forged approval | Gate is the only caller; call signed with `issued_at` and nonce (`gate/__init__.py:274-281`); approvals bound to a hash of action, actuator, parameters and incident, expiring, single use (`approval.py`) | A17, A18; `test_signing_keys.py`, `test_approval.py` | Twin must enforce skew and nonce; only our mock does (R9) |
| **T0830** Adversary-in-the-Middle; **T0842** Network Sniffing | Reading or editing traffic between the layers | TLS and mutual TLS exist (`adapters/tls.py`, `--tls-cert`); signatures protect readings and calls even in clear | `test_tls.py` | Not on by default: Compose runs plain HTTP; **Guardian verdicts are not signed** (R1, R4) |
| **T0848** Rogue Master / **T0849** Masquerading | A partner speaks as another partner or as the Brain on the screen | Push tokens name the partner; the source comes from the token; `brain.*` is refused; the screen ignores pushed `brain.*` | A13, A14 | A Twin token could retract verdicts until 7 Nov (R2, fixed) |
| **T0832** Manipulation of View; **T0829** Loss of View | Fake readings that make the Brain see a calm or a flooded city | Guardian verdict, forward-model doubt, independent-source rule (`min_trusted_sources`, `independence: cause`), retraction rebuilds baselines | Scenario t13; gate check 6 | Two compromised witnesses of different type still pass for low impact |
| **T0831** Manipulation of Control; **T0836** Modify Parameter | A bad but well-formed proposal from a rule or the model | Schema, capability, department allowlist, closed-incident, trust ref, evidence, cooling-off, quarantine, budget (`gate/__init__.py:85-231`); valve and grid wait for a person | A19; `brain security-check` | Allowlist and policy are the control: review them before demo |
| **T0880** Loss of Safety; **T0879** Damage to Property | A runaway loop or a hostile agent floods or oscillates actuators | Action budget per incident and per minute, cooling-off gap per actuator, idempotency, stand-down never blocked | `tests/test_gate.py` | Budget is in memory; a restart restores it from the snapshot |
| **T1691** Block OT Message / **T0814** Denial of Service | Flood or oversize body on the API; Guardian or Twin silent | 413 above 256 KiB, 429 per caller, degraded mode (track, send nothing) when the Guardian is down | A15, A16; scenario t15 | Rate limit key is the caller, or the client address when no token |
| **T0878** Alarm Suppression / **T0872** Indicator Removal on Host | Editing or deleting the log to hide an action | Hash-chained events, signed head `<log>.head`, `brain audit verify` | `test_chain_anchor.py` | The head is signed by a key on the same host: copy it off the host |
| **T0859** Valid Accounts; **T1694.002** Hardcoded Credentials | Stolen or default tokens and secrets | Scoped bearer tokens in constant time; short-lived HS256 tokens with audience, expiry and revocation by id (`security.py:44-122`) | A8 to A12; `test_tokens.py` | Compose falls back to `dev-only-*` secrets (R4); one signing key for all minted tokens |
| **T0819** Exploit Public-Facing Application; **T0883** Internet Accessible Device | The API, the `/mcp` server, the screen | Every route classified, a test fails on an unclassified one; MCP read-only with DNS-rebinding protection; container runs as uid 10001; Compose publishes on 127.0.0.1 only | `test_security.py`, `test_mcpserver.py` | On loopback with `require: auto` nothing is required (by design for the demo) |
| **T0871** Execution through API; **T0869.002** Pub/Sub protocols | MQTT or MCP used to inject or act | The signed body is the only identity on MQTT; reorder buffer, replay still refused; no actuator tool can be registered | `test_twin_mqtt.py`, A19 | The demo broker allows anonymous access (`deploy/compose/mosquitto.conf`; optional `mqtt` profile, bound to 127.0.0.1) |
| **T0862** Supply Chain Compromise | A poisoned dependency or base image | Lockfile (`uv.lock`, `--frozen`), SBOM `docs/sbom.cdx.json`, `bandit -ll` clean, `pip-audit` | commands in SECURITY.md row 15 | `pillow` advisories accepted because no image is decoded (R7); base image tag not pinned by digest |
| **T0882** Theft of Operational Information; **T0811** Data from Information Repositories | Reading the city state, decisions or logs | Read scope off loopback; demographic fields dropped at perception; no secrets in the image | `test_perception.py` | Metrics and timeline are readable by any `read` token |

## 3. Attack vectors and protections: ATT&CK Enterprise

| Technique | Vector | Protection | Residual |
| --- | --- | --- | --- |
| **T1190** Exploit Public-Facing Application | API routes, `/mcp` | Route classification test; pydantic validation on every body; no `eval`, `pickle`, `yaml.load` or `shell=True` in `src/` (grep, 7 Nov); the few `subprocess` calls take lists | Library CVEs are outside this review |
| **T1078** / **T1550.001** Valid Accounts, Application Access Token | A stolen token or cookie | Expiry, audience, revocation; cookie `HttpOnly`, `SameSite=Strict` | The cookie holds the raw static token when a static token logs in (`routes/control.py:64`) |
| **T1539** Steal Web Session Cookie; XSS | A partner event whose text runs in the operator's browser | The screen sets `textContent`; no `innerHTML` in `index.html`; the three in `canopy3d.js` hold fixed markup and text is set after; CSP, `nosniff`, no-referrer | CSP allows `'unsafe-inline'` scripts (R5) |
| **T1565.001 / .002 / .003** Data Manipulation | Stored, transmitted or runtime change of readings, state, approvals | Signatures; approvals signed; state files restored through typed parsing; log chain | Guardian verdicts in transit (R1) |
| **T1552.001** Credentials In Files | Keys in the repository | `.env` ignored; image holds no secret | none in this repository |
| **T1110** Brute Force; **T1606** Forge Web Credentials | Guessing tokens | Constant-time compare; high-entropy minted tokens; rate limit | A static token that is weak is weak: generate with `openssl rand -hex 32` |
| **T1498 / T1499** Network and Endpoint DoS | Flood, large bodies | Size and rate limits at the edge | Out of scope of this review's threat list; accepted |
| **T1195** Supply Chain Compromise | Dependencies, vendored three.js | Lockfile, SBOM, pinned vendored r160 with no CDN | Base image by tag, not digest |
| **T1553** Subvert Trust Controls; **T1098** Account Manipulation | Replacing a key; editing `partners.yaml` or `tuned/` | Key ids with validity dates; `alg: none` refused; tuned overlay only moves listed numbers inside their range, one step at a time; the gate, tactics, scoring, triage and learning sections are never tunable (`mind/surface.py`) | A host compromise defeats config: out of scope |

## 4. Attack vectors and protections: MITRE ATLAS

| Technique | Vector against our AI parts | Protection | Proof | Residual |
| --- | --- | --- | --- | --- |
| **AML.T0051.000 / .001** LLM Prompt Injection (direct, indirect) | Text in a sensor id, a value field, an id, or a pushed event that reaches the agent prompt | Ids and every free-looking field limited to `[A-Za-z0-9._:#-]{1,64}`; unknown value fields dropped before any prompt; 30 hostile strings mapped to OWASP LLM categories | A5, A6, A7; `test_llm_security.py` | Free text from partners (Twin tool descriptions) is not shown to agents: only capability names are read (`runtime.py:_recheck_capabilities`) |
| **AML.T0053** AI Agent Tool Invocation; **AML.T0054** LLM Jailbreak | A model talked into acting | Agents get read-only tools; the registry refuses an actuator's name; agents pick zones, never words; `verify_case`, `verify_plan`, `verify_desk`; then the gate | A19; AST tests | A jailbroken model can still pick a wrong zone: the gate's checks and approvals bound the harm, not the model |
| **AML.T0043 / T0015 / T0031** Craft Adversarial Data, Evade AI Model, Erode Integrity | Sensor values shaped to fool the forecast or the attention model | Range and type checks; forward model compares and reports an untrusted reading but never learns from it; independent-source rule; variants test (shifted, reseeded, decoyed) must decide as the base | `brain variants`, scenario t13 | A slow drift inside range by a signed Twin: depends on the Guardian |
| **AML.T0020 / T0059 / T0018** Poison Training Data, Erode Dataset Integrity, Manipulate AI Model | Teaching the Brain something false through sleep, episodes or the Academy | Sleep learns from trusted readings only, none retracted (`mind/sleep.py:176`); retraction makes sleep forget; a rule is confirmed only when the team plans the same way again and retired when it does not; self-tuning limited to a listed surface and works only when `tuned_dir` is set; score on stories never seen | `tests/test_sleep.py`, `mind/lifecycle.py` | A Guardian that trusts a bad reading feeds learning (R1) |
| **AML.T0070** RAG Poisoning; **T0066** Retrieval Content Crafting | Putting text in the knowledge base | The corpus is repository markdown cut by heading; it is not written from readings or API input | `knowledge/corpus.py` | A merged doc change is a corpus change: review docs like code |
| **AML.T0057 / T0056** LLM Data Leakage, Extract System Prompt | The model leaks city data or its prompt | Prompts carry ids and numbers only; demographic fields dropped at perception; the prompt holds no secret | `test_perception.py` | Briefs go to a hosted model (Groq): the data leaves the laptop; scripted team keeps it local |
| **AML.T0029 / T0034 / T0046** Denial of AI Service, Cost Harvesting, Chaff Data | Burning free-plan tokens or flooding the model | Scripted crew is the default and every scenario passes with no network; model health flips to scripted; per-model token limits | scenario `--llm` runs, `reliability` | A live demo on a hotspot can fall back mid-run: by design |
| **AML.T0010.001 / .003** AI Supply Chain: software, model | A bad package or a swapped model | Lockfile and SBOM; embedding model baked into the image at build | SBOM | Remote model weights at Groq are not ours to pin |
| **AML.T0055** Unsecured Credentials | The Groq key | `.env` ignored, never echoed | none | none |
| **AML.T0048** External Harms | The sum of the above reaching a person | Human approval on valve and grid, single use and bound to parameters | A17, A18 | Approver is a token label, not a named person (R3) |

## 5. Residual risks, ranked

Likelihood and impact are for a stage demo and a Phase 1 review, on a scale of low, medium, high.

| # | Gap | Evidence | L | I | Risk |
| --- | --- | --- | --- | --- | --- |
| **R1** | **Guardian verdicts are not authenticated.** The REST adapter checks the schema of the answer and nothing else, so anyone who can answer on that connection can mark a reading `trusted`. | `adapters/guardian_rest.py:27-35`; `TrustVerdict` has no signature check; Guardian link is plain HTTP unless `guardian.tls` is set | M | H | **High** |
| **R2** | **Any push token can retract a verdict.** `/api/retractions` needs only the `push` scope, which the Twin's token holds. A compromised Twin can retract Guardian-trusted readings and stop later actions that cite them, or make sleep forget what it taught. | `security.py:56`; handler in `routes/control.py` reads no caller label | M | M | **Fixed 7 Nov** (section 9) |
| **R3** | **Approvals name a token, not a person.** With a static `approve` token every approver is `approve`. Accountability for a valve call is weak. | `routes/control.py:46-47` takes `caller.label` | M | M | **Medium** |
| **R4** | **Dev defaults and no transport security in Compose.** `dev-only-*` secrets are public in the repository and apply when the variables are unset; Compose runs plain HTTP. | `docker-compose.yml:17-19`; SECURITY.md row 14 | M | H if the stack leaves the laptop | **Medium** |
| **R5** | CSP allows inline scripts, so it would not stop an injected inline script. The code has no known injection point. | `security.py:30`; no `innerHTML` in `index.html` | L | M | Low |
| **R7** | `pillow` carries advisories; it cannot move because `fastembed` pins it. No image is decoded. | SECURITY.md row 15 | L | L | Low |
| **R8** | Shared HMAC secrets: whoever holds the Twin secret forges readings; the Twin also holds the secret that verifies the Brain's calls. Ed25519 is built but the mocks use HS256. | `docs/KEYS.md` "What is not done" | L | H | Medium |
| **R9** | **Nothing has run against the Twin team's real Twin**; against the Guardian team's Guardian only the fake and real flood and T16 (8 Nov). Skew, nonce and `kid` checks on the Twin's side are proposals, so those defences are proven only against our mocks. | KEYS.md | H | M | **Medium** |
| **R10** | The signed log head sits next to the log, signed by a key on the same host. | `timeline.py:109-114` | L | M | Low |
| **R11** | **No freshness check on readings.** Perception checks only that `sequence_no` rises. A signed reading with an old timestamp is accepted, and so is a captured reading that was held back and delivered late. | PoC `P-B`: a 2020 timestamp and a withheld sequence 50 were both accepted; no staleness check exists outside saved state (`runtime.py:496`) | M | M | **Fixed, off by default** (section 9) |
| **R12** | **The size limit reads only `Content-Length`.** A chunked body has none, so it is not stopped at 256 KiB. | PoC `P-H`: 800 KB with no length reached the handler (422, not 413) | M | L | Low (memory only) |
| **R13** | The `trust` field of a reading is not signed (`signing.py` leaves it out). It is used only when `guardian.mode: inline`; the default `sidecar` ignores it. | `signing.py:UNSIGNED_FIELDS`; `runtime.py:732`; PoC `P-A` | L | H if inline is turned on | Low as shipped |

Added by section 8: R11 to R13. Two suspected gaps were checked and do not hold: the Guardian's free-text `reasons` never reach a prompt (they go to the graph as a bound parameter and to an explanation), and `department_code` never builds a file path (it comes from the shipped manifests, not from a reading).

## 6. Hardening, in order

Before the 14 Nov demo, cheapest first:

1. ~~**R11.**~~ Done 7 Nov: `twin.max_age_s` (section 9). Still to do: set it on the live Twin.
2. ~~**R2.**~~ Done 7 Nov: only the Guardian's push token may retract (section 9).
3. **R4.** Refuse to start off loopback when a secret is still a `dev-only-*` value; run the demo stack with `openssl rand -hex 32` secrets and real tokens.
4. **R1.** Have the Guardian sign each verdict with the same key ring as readings (`kid`, `alg`) and verify it in `RestGuardianAdapter`; until the Guardian team adopts it, switch on `guardian.tls` with a client certificate. This needs the partner.
5. **R3.** Give each operator a minted token (`brain token --sub ana --scope read,approve --ttl 8h`) so the approver in the log is a name.
6. **R10.** Copy the `.head` file off the host at the end of a demo run.

Later: nonce-based CSP (R5), mutual TLS inside Compose, Ed25519 for both directions, digest-pinned base image, broker access control for MQTT.

## 7. What this review did not do

- It read `security.py`, `approval.py`, `redteam.py`, `gate/`, `perception/`, `adapters/guardian_rest.py`, `mcpserver.py`, `timeline.py`, the Dockerfile and Compose, and parts of `mind/` and `knowledge/`. It did not read the department prompts, the solvers or the Twin adapters line by line.
- It ran `brain redteam` and the proofs of concept in section 8. The test suite, `security-check`, `bandit` and `pip-audit` were not re-run; their results here are as recorded in SECURITY.md.
- It did not test the live stack, TLS or the screen in a browser.
- The mapping to techniques is judgment: a technique listed here is relevant, not proved to be exploitable.

## 8. Is each technique exploitable? Verdicts

How to read the verdict:

- **Exploitable**: shown by a proof of concept (`uv run python scripts/security_poc.py`, in process, 13 checks). The id after it (`P-B`) names the check.
- **Exploitable if**: the code leaves it open, but only with the precondition named; not run end to end.
- **Not exploitable**: attacked and refused, or the code path does not exist.
- **Not tested**: reasoned from the code only.

"Exploitable" is about the Brain as shipped, from the position an attacker would need. It says nothing about how likely that position is.

### 8.1 ATT&CK for ICS

| Technique | Verdict | Evidence | Why, or what the attacker needs |
| --- | --- | --- | --- |
| **T1692.002** Reporting Message: forged reading | **Not exploitable** | `P-A`: changing `sensor_id`, `type`, `zone_id`, `timestamp`, `sequence_no`, `value`, `department_code` or adding a field after signing is refused; A1 to A3, A20 to A22 | Needs the Twin's secret |
| **T1692.002**: held back, then replayed or delayed reading | **Exploitable by default; refused with `twin.max_age_s` set** | `P-B`: a 2020 timestamp and a withheld sequence 50 are both accepted by default, and refused as `reading_stale` with the limit on; A24 | Needs a position on the Twin link and the ability to drop readings. A reading delayed by less than the limit still passes, so set the limit to a few times the reporting interval. The effect on decisions was not run (R11) |
| **T1692.001** Command Message: forged call to the Twin | **Exploitable if** | Calls are signed with a nonce and `issued_at` (`gate/__init__.py:274-281`); the Brain has no route that actuates | Needs the Brain's secret, **or** a Twin that does not check. Compose's fallback `dev-only-brain-secret` is public, so on a stack with unset secrets anyone who reaches the Twin's port can sign. The real Twin's checks are untested (R9) |
| **T0830** Adversary-in-the-Middle: readings and calls | **Not exploitable** to change; **exploitable** to read | Signed bodies fail on any edit (`P-A`); plain HTTP in Compose | Reading needs a network position; there is no TLS by default (R4) |
| **T0830**: verdicts | **Exploitable** | `P-D`: an adapter fed a made-up answer returns `trusted` with no key involved | Needs a position on the Guardian link, or to be the thing that answers the URL (R1) |
| **T0842** Network Sniffing | **Exploitable if** | Plain HTTP, MQTT and MCP by default | Same network. Only confidentiality is lost; nothing there signs for the attacker |
| **T0848** Rogue Master; **T0849** Masquerading (partner as partner) | **Not exploitable** | `P-I`: Twin token pushing `guardian.*` 403, `brain.*` 403, a body claiming source `guardian` is stored as `twin` | None |
| **T0849**: Twin acting as the Guardian on retractions | **Not exploitable** (fixed 7 Nov) | `P-E`: the Twin's token now gets 403; the Guardian's gets past the check; A23 | Before the fix the Twin's push token could retract (R2) |
| **T0832** Manipulation of View | **Exploitable if** | Paths: a forged verdict (`P-D`), a delayed reading (`P-B`), a stolen Twin secret | One of those preconditions; no path found from the API |
| **T0829** Loss of View | **Not exploitable** by retraction since 7 Nov | `P-E`, A23 | Other paths to a lost view (a forged verdict, `P-D`) remain |
| **T0831** Manipulation of Control; **T0836** Modify Parameter | **Not exploitable** from outside | `P-F`: no route answers an unauthenticated call; routes list has no actuator route; A19 | An insider (a bad rule, a bad model, a stolen `approve` token) is bounded by the gate's 11 checks, not stopped by them |
| **T0880** Loss of Safety; **T0879** Damage to Property | **Not tested** | Gate budget and cooling-off exist | A race in the gate is possible: `check` awaits the Guardian between finding an approval and consuming it (`gate/__init__.py:167` to `217`), and no lock is held. The one caller found (`graph/actuation.py:130`) runs proposals one at a time, so no concurrent path was found; unproven either way |
| **T1691** Block OT Message; **T0814** Denial of Service | **Exploitable** | `P-H`: a chunked body bypasses the 256 KiB limit | Needs a push token or loopback. A flood is refused (A16). Availability only |
| **T0878** Alarm Suppression; **T0872** Indicator Removal | **Not exploitable** from outside; **exploitable if** host access | Chain and head tests; the head is signed by a key the Brain's own process holds | Needs write access to the log and the Brain's key (R10) |
| **T0859** Valid Accounts | **Not exploitable** | `P-G`: alg none, a wrong-key signature and a static token with dots appended are all 401; `P-J`: a made-up cookie is 401 | A stolen real token works, as any bearer token does |
| **T1694.002** Hardcoded Credentials (and default credentials, T1694.001) | **Exploitable if** | `docker-compose.yml:17-19` falls back to `dev-only-*` | The stack runs with those variables unset and the attacker can reach it (R4) |
| **T0819** Exploit Public-Facing Application; **T0883** Internet Accessible Device | **Not exploitable** on what was tried | `P-F`: 28 path spellings (trailing and double slash, case, encoded and dot segments, prefix tricks) by 7 methods, none unauthenticated; `P-K` and `P-L`: no traversal in the schema or scenario routes | A library flaw is out of scope. **Not tested:** the MCP host-header guard (`P-M` could not start the MCP task group in process) |
| **T0871** Execution through API; **T0869.002** MQTT | **Exploitable if** | Anonymous Mosquitto in the demo stack (`mosquitto.conf`) | The `mqtt` profile is on and the attacker is on the host or the network. A reading must still verify, so only replay or delay (`P-B`) works, or forgery when the secret is the dev default |
| **T0862** Supply Chain Compromise | **Not tested** | Lockfile, SBOM; `pillow` advisories accepted | The image never decodes an image, so `pillow` is not reachable; the base image is a tag, not a digest |
| **T0882** Theft of Operational Information; **T0811** | **Exploitable if** | `P-F`: no read without a token off loopback | On loopback with `require: auto`, anything on the host reads everything. Any `read` token reads everything (no per-incident scope) |

### 8.2 ATT&CK Enterprise

| Technique | Verdict | Evidence | Why, or what the attacker needs |
| --- | --- | --- | --- |
| **T1190** Exploit Public-Facing Application | **Not exploitable** | `P-F`, `P-K`, `P-L`; no `eval`, `pickle`, `shell=True` or `yaml.load` in `src/`; Cypher built from literals, values bound | New code can change this |
| **T1078** Valid Accounts; **T1550.001** Application Access Token | **Not exploitable** | `P-G`, `P-J` | A stolen valid token |
| **T1539** Steal Web Session Cookie; XSS | **Not exploitable** on what was read | No `innerHTML`, `eval` or `document.write` in `index.html`; the three `innerHTML` in `canopy3d.js` hold fixed markup and text is set after; cookie `HttpOnly`, `SameSite=Strict`; no CORS | Not run in a browser. CSP does not stop inline script (R5) |
| **T1565.002** Transmitted Data Manipulation | **Not exploitable** for readings and calls; **exploitable** for verdicts | `P-A`; `P-D` | As T0830 |
| **T1565.001 / .003** Stored and Runtime Data Manipulation | **Exploitable if** host access | State, approvals and learned rules are files and SQLite | Needs the host |
| **T1110** Brute Force; **T1606** Forge Web Credentials | **Not exploitable** with a strong token | `P-G`; constant-time compare | A short static token could be guessed at the 600 calls a minute the limit allows; a 32-hex token cannot |
| **T1498 / T1499** Denial of Service | **Exploitable** (memory) | `P-H` | Availability only |
| **T1195** Supply Chain Compromise | **Not tested** | As T0862 | |
| **T1553** Subvert Trust Controls; **T1098** Account Manipulation | **Not exploitable** from outside | Key-id checks (`P-C`: an Ed25519 key is not fooled by HS256 with its public key, or by `alg: none`) | Needs the host or the config |

### 8.3 ATLAS

| Technique | Verdict | Evidence | Why, or what the attacker needs |
| --- | --- | --- | --- |
| **AML.T0051.000 / .001** LLM Prompt Injection | **Not exploitable** on the paths found | A5 to A7; `P-A` (a changed or added field is refused); ids and values are allowlisted before any prompt | Zone names from the Twin's topology are not checked against the id pattern. They go into a public-alert message, and no path from them to a prompt was found. Not tested |
| **AML.T0053** AI Agent Tool Invocation | **Not exploitable** | A19: no actuator-named tool can be registered | |
| **AML.T0054** LLM Jailbreak | **Not exploitable** to act; **exploitable if** the input is hostile, to mislead | Agents pick zones, not words; the gate decides | The model has nothing untrusted to read, so there is nothing to jailbreak it with; a wrong zone choice is bounded by the gate |
| **AML.T0043 / T0015 / T0031** Adversarial data, evasion, eroding integrity | **Exploitable if** | Values are checked for type and range only; forward-model doubt and the independence rule are the defences | A compromised signer sending in-range values that drift. Not tested with an adversarial run; only decoys and shifts in `brain variants` |
| **AML.T0020 / T0059 / T0018** Poisoning what the Brain learns | **Not exploitable** as shipped; **exploitable if** a verdict is forged | Sleep needs `episodes` and `learned` folders, which the shipped `partners.yaml` keeps null; sleep learns only from `trusted` readings (`mind/sleep.py:176`) | Chain: forge a verdict (`P-D`), then sleep teaches from it. Bounded by the lifecycle checks and the tunable surface |
| **AML.T0070 / T0066** RAG Poisoning, Retrieval Content Crafting | **Not exploitable** | The corpus is repository markdown; no route or reading writes to it | A merged change to the docs |
| **AML.T0057** LLM Data Leakage | **By design** | Briefs go to Groq: ids, numbers, zone ids; demographics dropped at perception | The data leaves the laptop when `--llm` is on |
| **AML.T0056** Extract LLM System Prompt | **Not exploitable** (nothing to gain) | The prompt holds no secret | |
| **AML.T0029 / T0034 / T0046** Denial of AI service, cost harvesting, chaff | **Exploitable if** | Free plan, 8,000 tokens a minute; scripted crew is the fallback | A signer driving many incidents. Availability and cost only |
| **AML.T0010.001 / .003** AI Supply Chain | **Not tested** | | |
| **AML.T0048** External Harms | **Exploitable if** a chain completes | Forged verdict (`P-D`) plus a stolen `approve` token plus a policy that allows the call | Three preconditions together |

### 8.4 What the proofs of concept showed

| Check | Result |
| --- | --- |
| `P-A` Field changed after signing | Every field but `trust` is covered. `contract_version` and `trust` were accepted: the first only because the test set the same value; the second is unsigned (R13) |
| `P-B` Old and withheld readings | Accepted by default; refused as `reading_stale` with `twin.max_age_s` set (R11) |
| `P-C` Ed25519 key against HS256 and `none` | Refused |
| `P-D` Unsigned verdict | Accepted (R1) |
| `P-E` Retraction by token | The Twin's token is refused (403) since 7 Nov; the Guardian's passes; read and no token are refused (R2) |
| `P-F` Route sweep | No unauthenticated answer |
| `P-G` Forged tokens | All refused |
| `P-H` Chunked body | Limit bypassed (R12) |
| `P-I` Timeline push spoofing | Namespace and source enforced |
| `P-J` Made-up cookie | Refused |
| `P-K`, `P-L` Traversal | None |
| `P-M` MCP host header | Not run: the MCP task group does not start without the server's own lifespan |

Net result: of the 42 rows in 8.1 to 8.3, the proofs of concept confirmed four gaps (R1, R2, R11, R12). R2 and R11 are fixed (section 9); R1 and R12 are open. The forgery, token, traversal and algorithm-confusion attacks were refused, and most of the rest is "exploitable if" a named precondition holds. Four rows are "not tested" (T0880 and T0879, T0862, T1195, AML.T0010) and three have a part that was not run (the MCP host guard, the screen in a browser, zone names from the topology).

## 9. Fixes made on 7 Nov

| Gap | Change | Where | Proof |
| --- | --- | --- | --- |
| **R2** a Twin token could retract a verdict | `/api/retractions` now answers 403 unless the caller is the Guardian's push token. On loopback with no tokens it is open, as before | `src/brain/api/routes/control.py` | A23; `tests/test_security.py::test_only_the_guardians_push_token_may_retract_a_verdict`; `P-E` |
| **R11** no freshness check | `twin.max_age_s` (seconds, `null` by default): a signed reading stamped further than that from the Brain's clock, in the past or the future, is refused as `reading_stale`. The check runs before the sequence counter moves, so a stale reading does not use up a number | `src/brain/perception/__init__.py`, `config.py`, `config/partners.yaml` | A24; three tests in `tests/test_perception.py`; `P-B` |

Both are checked in `brain redteam`: 24 attacks, all refused. `brain security-check` holds, `brain scenario b2 --inproc` passes, and lint is clean.

What these fixes do not do:

- **R11 is off by default.** The scenarios replay readings stamped in the past, so turning it on would change their decisions and break the frozen baselines. The shipped setting protects nothing until `twin.max_age_s` is set on the live Twin: do that before 14 Nov, to a few times its reporting interval. A delay shorter than the limit still passes.
- **R2 removes the Twin's access, not the operator's.** Admin cannot retract either: the edge needs the `push` scope for that route and admin does not carry it. The Guardian's token is the only way in, as the interface already said ("for the Guardian").
- **A24 shows the check works when set,** not that the Brain is protected as shipped.
- The Guardian's real push token is a secret the Guardian team must hold; a retraction from a minted token needs `sub: guardian`.

