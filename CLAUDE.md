# CowAgent-Rev

@.ai-style-rules.md

The rules above are inherited from the existing codebase, not imposed on it.
Before writing code, open the Golden File for the layer you are touching and
follow its shape. Open each coding task by naming the exemplar you are
following and the DONTs that apply.

## Workspace layout

- `CowAgent/` — the active project: web.py console backend, hand-written
  vanilla-JS frontend, Python agent architecture. All work lands here.
- `cowagent2/` — clean-rebuild reference tree. **Read-only.** Port from it by
  copying and adapting into `CowAgent/`; never edit it.
- `WeChatFerry/` — vendored upstream (WeChat 3.9.12.56 hook + Python SDK),
  maintained on its own repair track.
- `ROADMAP.md` — the authority on channel state, upstream defect IDs
  (`WCF-BUG-0N`), and milestone scope. Cite defect IDs in code comments rather
  than re-explaining the defect.
