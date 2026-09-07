# WeChatFerry message-transport patch

Two commits that restore inbound message delivery on WeChatFerry's
`3.9.12.56` branch (upstream PR
[#429](https://github.com/lich0821/WeChatFerry/pull/429)), which this host needs
because WeChat 3.9.12.56 is the installed version.

## The bug

The branch captures messages but never delivers them:

- `msgSock` is declared and closed in `spy/rpc_server.cpp`, but **never opened,
  bound, or sent on**. The only `nng_listen` in the whole `spy/` tree is
  `cmdSock` on port 10086.
- `gMsgQueue` is pushed to by both hooks in `message_receiver.cpp` — correctly,
  under `gMutex` with `gCV.notify_all()` — and **popped by nothing**.

So `tcp://0.0.0.0:10087` never listens. `enable_receiving_msg()` still reports
success, because installing the hook genuinely succeeds; the messages just pile
up in a queue with no reader, and every client fails with `ConnectionRefused`
when it dials the event socket. `master` has the missing consumer
(`nng_pair1_open` → `nng_listen` → `nng_send`); the 3.9.12.56 port dropped it.

## What the patch does

`0001` ports that consumer over, adapted to the branch's free-function layout
(master's is a method on an `RpcServer` class). It reuses the branch's existing
producer side untouched, so the diff is only the missing thread — 96 insertions.

`0002` adds a `workflow_dispatch` trigger, because `ci.yml` otherwise only fires
on pull requests to `master` and a fork pushing a topic branch would build
nothing.

## Building it

Requires VS2019 + vcpkg (`spdlog`, `nng`, `magic-enum`, `minhook`, **x86**).
Easiest route is upstream's own CI, which already builds this branch green:

```bash
git clone https://github.com/lich0821/WeChatFerry
cd WeChatFerry
git checkout -b fix/msg-transport origin/3.9.12.56
git am /path/to/scripts/wcf-msg-transport/*.patch
git remote add fork https://github.com/<you>/WeChatFerry
git push fork fix/msg-transport
```

Then run the **CI** workflow on that branch from the Actions tab, and install
the resulting `wechatferry-binaries` artifact:

```
.venv\Scripts\python scripts\wcf_ci_dlls.py --repo <you>/WeChatFerry --run <run-id>
```

Fully quit and reopen WeChat afterwards — a `spy.dll` already mapped into a
running WeChat is not replaced by a file swap.

## Verifying it worked

Success is one line in `.venv/Lib/site-packages/wcferry/logs/wcf.txt` that has
never yet appeared on this host:

```
[info] [WCF] [rpc_server.cpp] MSG Server listening on tcp://0.0.0.0:10087
```

## Known-separate defect

`MicroMsg.db` handle lookup still fails on this branch, so `get_contacts()`
returns empty and display names fall back to raw wxids. Message receive is
hook-based and does not depend on it, and group `@` detection reads the message
XML rather than the database.
