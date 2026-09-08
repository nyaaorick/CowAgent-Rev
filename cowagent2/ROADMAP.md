# CowAgent 2 — Dedicated Roadmap

> Scope: the `cowagent2/` subsystem only. The workspace-wide authority is
> [`../ROADMAP.md`](../ROADMAP.md); where the two disagree, the workspace
> roadmap wins.

## 1. Vision

CowAgent 2 is a minimalist personal WeChat agent rebuilt from zero on
WeChatFerry and native Windows 11. Against the large multi-channel CowAgent 1
it optimises for a different set of properties — minimum weight, zero
interference with the operator's own account, clean context isolation, and
convincing human simulation — so the two can be compared head to head on the
same host.

The destination is a **digital twin of the account owner**: an agent that
carries one continuously consolidated picture of who the owner is across every
conversation, while keeping a separate, private record for each contact.

---

## 2. Core directives

1. **Minimalism and pure WCF binding.** No channel adapters, no inheritance
   chains. One robust singleton runtime for WeChat 3.9.12.56 on Windows.
2. **Strict session isolation.** Every `wxid` and every `roomid` owns a sealed
   context and sliding window. Nothing crosses between contacts or rooms.
3. **Three-field session identity.** Bind `wxid` (system id), `Alias` (the
   user-chosen WeChat ID) and `Remark`/`NickName` (display name) from
   `MicroMsg.db`.
4. **Default-deny access control.** Unauthorised contacts are dropped
   silently. An empty or malformed allow list means nobody.
5. **Localhost console on 127.0.0.1:9900.** Contact filtering, live whitelist
   toggles, session inspection, and read-only SSE chat monitoring.
6. **Reuse CowAgent 1 for anything proven.** Where CowAgent 1 has an
   implementation already validated on real hardware — WCF transport
   (`send_text(msg, receiver, aters)`, `status == 0`, `is_login()`), contact
   filtering semantics, web-console auth, the memory subsystem — port it
   rather than inventing a parallel one. Section 6 tracks this ledger.
7. **English throughout the codebase.** Comments, docstrings, log messages and
   documentation are English. Chinese remains only where it *is* the product:
   the persona prompt, WeChat-facing reply text, the `#清除记忆` command, and
   the regexes that strip Chinese model boilerplate.

---

## 3. Status

```
Phase 1: Minimalist architecture and core breakthroughs        [COMPLETE]
  ├─ [x] M1. Scaffold and seamless CowAgent 1 config reuse
  ├─ [x] M2. WCF repair + sub-second full contact scan
  ├─ [x] M3. Sealed per-session memory engine and reset command
  ├─ [x] M4. Human-simulation engine and non-mechanical pacing
  └─ [x] M5. Localhost console with SSE live monitoring

Phase 2: Correctness, standardisation and durable memory       [IN PROGRESS]
  ├─ [x] M6. Code review remediation and English standardisation
  ├─ [ ] M7. Memory system port — global + per-contact memory
  ├─ [ ] M8. Interaction depth (message splitting, multimodal, presence)
  └─ [ ] M9. Hardening (watchdog, console auth, UI translation)

Phase 3: Evaluation                                            [PLANNED]
  └─ [ ] M10. CowAgent 1 vs CowAgent 2 A/B assessment
```

---

## 4. Completed milestones

### M1 — Minimal core and seamless config reuse
- [x] **1.1** Independent `cowagent2/` package with no redundant dependencies.
- [x] **1.2** Transparent reuse of the GLM key, base URL and model parameters
  from `CowAgent/config.json`.
- [x] **1.3** Anti-wedge singleton: Release `spy.dll` via `debug=False`, stale
  `.wcf.lock` cleared at startup, `wcferry`'s `atexit` cleanup unregistered so
  a restart cannot unhook WeChat.

### M2 — WCF repair and full contact resolution
- [x] **2.1** Reversed and patched the `AccountStorageMgr` offset change
  (`0x34` → `0x38`) at file offset `0x20dd4` in `wcferry/spy.dll`, unlocking
  `MicroMsg.db`.
- [x] **2.2** Rewrote `scanner.py` as a batched in-memory scan: 6,476 contacts
  and rooms indexed in ~0.8 s, one cache write per scan.
- [x] **2.3** Three-field binding: `wxid` + `Alias` + `Remark`/`NickName`.

### M3 — Sealed session memory
- [x] **3.1** Independent context container per `wxid` and per `roomid`.
- [x] **3.2** Sliding-window trimming inside the token budget.
- [x] **3.3** Scoped reset (`#清除记忆`) affecting only the calling session.

### M4 — Human-simulation engine
- [x] **4.1** Persona prompt banning assistant disclosures and service-desk
  boilerplate.
- [x] **4.2** Length-derived reading (0.6–2.5 s) and typing (1.0–5.0 s) delays.
- [x] **4.3** Reply cleaner that strips robotic preambles.

### M5 — Console and live monitor
- [x] **5.1** Responsive dashboard with a six-field table (type | wxid |
  WeChat ID | display name | whitelist | auto-reply), fuzzy search across all
  fields, and one-click id copying.
- [x] **5.2** SSE live chat monitoring, read-only.

### M6 — Code review remediation and English standardisation
> Full findings and their resolutions are in section 5.

- [x] **6.1 Group authorisation defect (critical).** `Config.is_allowed` took
  `(wxid, roomid="")`; callers that passed only the session id had rooms
  checked against `allowed_wxids`. Every group chat stayed silent even after
  the operator enabled it, while the console reported it as authorised. The
  signature is now `is_allowed(session_id, is_group=None)` with `@chatroom`
  inference, so a one-argument call is correct by construction.
- [x] **6.2 Reply cleaner fought the persona.** A `^好的[，,]` rule stripped the
  exact casual openers the persona prompt asks for. Every pattern is now
  anchored on an explicit disclosure or boilerplate phrase.
- [x] **6.3 Console turn timestamps.** `bot._notify_turn` read `"timestamp"`
  from records the memory store writes as `"time"`, so every turn broadcast at
  the epoch.
- [x] **6.4 Deprecated event-loop access.** `Application.loop` is deprecated
  and reads `None` before a runner binds it; the console now captures the
  serving loop in `start()`.
- [x] **6.5 Debug SQL endpoint.** The `q` term was interpolated straight into
  SQL and the `sql` parameter accepted arbitrary statements against the
  operator's whole message database, unauthenticated. Raw SQL is now gated
  behind `cowagent2_debug_sql`, checked before gateway state, and search terms
  are escaped against a `LIKE ... ESCAPE` clause.
- [x] **6.6 Test isolation.** The suite rewrote the live `data/whitelist.json`
  and `data/contacts_cache.json`. `WebServer` and `ContactScanner` now accept
  injected config, memory and cache paths.
- [x] **6.7 Package hygiene.** Added `__init__.py` to `cowagent2/` and
  `cowagent2/tests/`; removed the dead import-time `scanner` singleton and the
  cache write it performed on every import.
- [x] **6.8 English standardisation.** `config.py`, `memory.py`, `scanner.py`,
  `app.py` and `web_server.py` translated; logger names normalised to
  `cowagent2.*`.

---

## 5. Review findings ledger

| ID | Severity | Component | Finding | Status |
|---|---|---|---|---|
| CA2-01 | CRITICAL | `config.py`, `bot.py` | Rooms authorised against the contact list; group chat entirely non-functional | Fixed (M6.1) |
| CA2-02 | HIGH | `web_server.py` | Unauthenticated arbitrary SQL over the WeChat message database; `q` interpolated unescaped | Fixed (M6.5) |
| CA2-03 | HIGH | `human_simulator.py` | Reply cleaner removed legitimate conversational openers | Fixed (M6.2) |
| CA2-04 | HIGH | `tests/` | Suite mutated live operator runtime data | Fixed (M6.6) |
| CA2-05 | MEDIUM | `bot.py` | Turn timestamps always zero | Fixed (M6.3) |
| CA2-06 | MEDIUM | `web_server.py` | Deprecated `Application.loop` used for cross-thread scheduling | Fixed (M6.4) |
| CA2-07 | MEDIUM | package | Missing `__init__.py`; dead singleton writing to disk at import | Fixed (M6.7) |
| CA2-08 | MEDIUM | all | Mixed Chinese/English comments, docstrings and logs | Fixed (M6.8) |
| CA2-09 | MEDIUM | `memory.py` | No persistence — restart is total amnesia | Open → M7 |
| CA2-10 | MEDIUM | `web_server.py` | Console has no authentication | Open → M9.2 |
| CA2-11 | LOW | `bot.py` | Group `@` stripping is ad-hoc; CowAgent 1's `at_list` approach is more reliable | Open → M7.6 |
| CA2-12 | LOW | `wcf_gateway.py` | `close()` reaches into `wcf._is_running` and raw sockets | Open → M9.1 |
| CA2-13 | LOW | `app.py` | `SIGTERM` is not delivered on Windows; the handler is effectively `SIGINT`-only | Open → M9.1 |
| CA2-14 | LOW | `static/index.html` | Console UI still Chinese | Open → M9.4 |

---

## 6. CowAgent 1 reuse ledger

| Capability | CowAgent 1 source | CowAgent 2 status |
|---|---|---|
| WCF `send_text` contract | `channel/wcf/wcf_channel.py:334` | **Adopted** — positional `(msg, receiver, aters)`, `status == 0` |
| Login / liveness checks | `channel/wcf/wcf_channel.py` | **Adopted** — `is_login()` in gateway and health monitor |
| Contact allow-list semantics | `channel/wcf/contact_filter.py` | **Adopted** — fail-closed empty list, non-string entries dropped |
| Group reply target & `@` handling | `channel/wcf/wcf_message.py` | **Partial** — reply target correct; `at_list` stripping pending (M7.6) |
| Memory subsystem | `agent/memory/*` | **Planned** — M7 |
| Console auth (HMAC token) | `channel/web/web_channel.py:213` | **Planned** — M9.2 |
| SSE streaming patterns | `channel/web/web_channel.py` | **Adopted** — console live stream |

---

## 7. Milestone 7 — Memory system port (the digital twin)

> **Goal.** Give CowAgent 2 durable memory with two layers: one global memory
> that consolidates what the account owner is like across every conversation,
> and one private memory per contact with its own operator-authored documents
> and workspace.

### 7.0 Design intent

The bot is the account owner's digital twin. That means two different things
have to be remembered in two different places:

- **What the owner is like** — decisions, commitments, preferences, plans,
  recurring positions. This belongs in the *global* memory, is consolidated
  from every conversation, and is injected into every reply. It is what makes
  the twin consistent no matter who it is talking to.
- **What happened with one contact** — that person's context, history,
  relationship and the operator's specific instructions for them. This stays
  in that contact's own files and is injected only in that conversation.

#### The privacy boundary this creates

CowAgent 1 partitions WeChat memory per person deliberately, and
`agent/memory/identity.py` states why: a shared pile means *"what the agent
learns about one contact would surface while it talks to another"*, which it
calls the wrong answer for WeChat.

A unified global memory reopens exactly that risk, so M7 does **not** simply
merge the per-contact piles. The consolidation rule is:

> The global memory records facts **about the owner**. Facts **about a
> contact** stay in that contact's file and are never promoted.

Concretely, "the owner decided to move the launch to March" is global; "Alice
is job-hunting and asked me not to tell her manager" is not. The nightly
global consolidation prompt enforces this, and M7.5 adds a test asserting that
a contact-specific fact injected in one conversation cannot be retrieved from
another. Contacts can additionally be marked `memory_private`, which excludes
them from global consolidation entirely.

### 7.1 Target workspace layout

```text
cowagent2/data/workspace/
├── PERSONA.md                       # Stable identity of the account owner
├── MEMORY.md                        # Global consolidated memory (injected always)
├── memory/
│   ├── 2026-09-07.md                # Global daily log
│   ├── dreams/2026-09-07.md         # Consolidation diary
│   └── users/
│       └── <sanitised-wxid>/
│           ├── MEMORY.md            # Per-contact long-term memory
│           ├── PROFILE.md           # Operator-authored doc for this contact
│           ├── 2026-09-07.md        # Per-contact daily log
│           └── workspace/           # Per-contact files the agent may read
└── index.db                         # SQLite chunk index (FTS5 + optional vectors)
```

### 7.2 Module port plan

| CowAgent 1 module | LOC | Port decision |
|---|---|---|
| `agent/memory/identity.py` | 74 | **Port near-verbatim.** Already treats WCF as a per-person channel and sanitises ids into safe directory names. Drop the `common.const` / `Context` coupling — `cowagent2` already has `session_id` and `is_group`. |
| `agent/memory/chunker.py` | 140 | **Port verbatim.** No external dependencies. |
| `agent/memory/summarizer.py` | 914 | **Port the core.** `MemoryFlushManager`, daily summaries, and Deep Dream distillation. Replace `agent.protocol.models.LLMRequest` with the `ZhipuAiClient` the bot already holds; drop the `i18n` indirection and keep the Chinese prompts. |
| `agent/memory/storage.py` | 1257 | **Port.** SQLite chunk store with FTS5 keyword search, corruption quarantine and trigram CJK matching. Vector columns stay but unused until 7.7. |
| `agent/memory/manager.py` | 558 | **Port minus embeddings.** Hybrid search degrades to keyword-only; keep the two-pass file sync and temporal decay. |
| `agent/memory/service.py` | 234 | **Port verbatim.** Filesystem list/read API with the path-traversal guard; backs the console's memory browser. |
| `agent/memory/config.py` | 148 | **Simplify.** CowAgent 2 has exactly one workspace, so the per-workspace registry and pinning collapse to a single dataclass. |
| `agent/memory/conversation_store.py` | 1834 | **Port trimmed.** CowAgent 2 needs `load_messages`, `append_messages`, `clear_session` and session listing — not runs, pinning, display-turn grouping or pagination. Target ~300 LOC. |
| `agent/memory/vector_backend.py` + `embedding/` | 246+ | **Defer to 7.7**, retargeted from OpenAI to Zhipu `embedding-3`. |

### 7.3 Turn-time prompt composition

```
system = human-simulation persona          (human_simulator.build_system_prompt)
       + PERSONA.md                        (who the owner is)
       + MEMORY.md                         (global memory, truncated to 200 lines / 25 KB)
       + memory/users/<id>/MEMORY.md       (what I know about this contact)
       + memory/users/<id>/PROFILE.md      (operator's instructions for this contact)
       + retrieved chunks                  (hybrid search, scopes: shared + this user)
messages = conversation_store.load_messages(session_id)
```

Truncation reuses CowAgent 1's `_truncate_memory_content` policy from
`agent/prompt/workspace.py`: keep the newest 200 lines or 25 KB, whichever
binds first, with a marker telling the model older content exists.

### 7.4 Consolidation cycle

1. **Turn ends** → transcript appended to the conversation store.
2. **Window trims** → discarded messages summarised by the LLM and appended to
   `memory/users/<id>/<date>.md` (asynchronous; never blocks a reply).
3. **Nightly per-contact dream** → that contact's recent dailies distilled into
   `memory/users/<id>/MEMORY.md`.
4. **Nightly global dream** → every non-private contact's dailies rolled up
   into the global `MEMORY.md` under the owner-facts-only rule of 7.0, with a
   diary written to `memory/dreams/<date>.md`.

Step 4 is the genuinely new work. CowAgent 1's `deep_dream` distils either one
user's pile *or* the shared pile; it never rolls many users up into one. The
new prompt, its dedup key, and the owner-vs-contact filter are M7.4.

### 7.5 Deliverables

- [ ] **7.1** `cowagent2/memory/` package: `identity.py`, `chunker.py`,
  `storage.py`, `config.py` ported and unit-tested.
- [ ] **7.2** `conversation_store.py` (trimmed) — durable transcripts;
  `SessionMemoryManager` becomes a cache in front of it, and the existing
  public API is preserved so no call site changes.
- [ ] **7.3** `summarizer.py` — daily flush and per-contact Deep Dream on the
  Zhipu client.
- [ ] **7.4** Global consolidation — the cross-conversation roll-up, with the
  owner-facts-only prompt and `memory_private` exclusion.
- [ ] **7.5** Prompt composition in `bot.py`, plus an isolation test asserting
  a contact-specific fact cannot leak into another conversation.
- [ ] **7.6** Per-contact `PROFILE.md` and `workspace/`: console editor,
  scaffolding on first contact, and CowAgent 1's `at_list` group `@` stripping
  (closing CA2-11).
- [ ] **7.7** Optional hybrid search — Zhipu `embedding-3` behind a config
  flag; keyword-only remains the default.
- [ ] **7.8** Console memory browser via the ported `MemoryService`: browse
  and edit global memory, per-contact memory, dailies and dream diaries.

### 7.6 Acceptance criteria

- A restart preserves every session's history and both memory layers.
- A fact the owner states in conversation A is reflected in `MEMORY.md` and
  influences conversation B after consolidation.
- A fact about contact A is **not** retrievable in a conversation with
  contact B, and does not appear in the global `MEMORY.md`.
- A contact marked `memory_private` never contributes to global memory.
- Clearing one contact's memory leaves every other contact and the global
  memory intact.
- Memory writes never block a reply: flushes and dreams run off the reply path.

---

## 8. Milestone 8 — Interaction depth

- [ ] **8.1 Multi-bubble sending.** Real people send two or three short
  messages rather than one long paragraph. Split on sentence boundaries and
  send in sequence with inter-message delays.
- [ ] **8.2 Presence and schedule.** Slow or defer replies at night; support an
  explicit "away" state.
- [ ] **8.3 Group participation etiquette.** Speak only when `@`-mentioned, on
  configured keywords, or when genuinely relevant.
- [ ] **8.4 Multimodal.** Receive images and reply through a vision model;
  send stickers naturally.

## 9. Milestone 9 — Hardening

- [ ] **9.1 Watchdog and clean lifecycle.** Heartbeat probing of port 10086
  with lossless reconnect; replace the private-attribute teardown in
  `WcfGateway.close()` (CA2-12); Windows-correct signal handling (CA2-13).
- [ ] **9.2 Console authentication.** Port CowAgent 1's HMAC signed-token
  scheme from `channel/web/web_channel.py` (CA2-10).
- [ ] **9.3 WeChat restart detection.** Detect a manual client restart and
  re-establish injection automatically.
- [ ] **9.4 Console UI translation.** Translate `static/index.html` to English
  (CA2-14).

## 10. Milestone 10 — CowAgent 1 vs CowAgent 2 assessment

- [ ] **10.1** Resource and latency comparison: memory footprint, cold start,
  reply latency.
- [ ] **10.2** Blind realism testing with real contacts.
- [ ] **10.3** Architectural stability and maintenance-cost assessment.

---

## 11. ECC skills and subagents for this subsystem

| Task | Skill / subagent | Why |
|---|---|---|
| Python idiom and PEP 8 review | `python-patterns`, `python-reviewer` | Standardisation pass and ongoing review |
| Test design for M7 | `python-testing`, `tdd-workflow`, `tdd-guide` | Memory port needs tests written first |
| Console REST conventions | `api-design` | `/api/*` naming, status codes, error envelopes |
| Failure handling in the WCF and memory paths | `error-handling`, `silent-failure-hunter` | Async flush and subscriber callbacks swallow errors easily |
| Doc governance and drift | `living-docs-governance`, `doc-updater` | Keep this roadmap and `../ROADMAP.md` consistent |
| Security review before each merge | `security-reviewer` | Console endpoints, SQL surfaces, credential isolation |
| Windows/WCF runtime verification | `windows-desktop-e2e` | Process, injection and port checks |
| Architecture review of the memory port | `architect`, `code-architect` | M7 is the largest structural change to date |

> Note: the `unified-memory` skill is **not** applicable here. It covers the
> ECC Memory Vault for cross-harness agent handoffs, not a chatbot's runtime
> memory of its conversations.
