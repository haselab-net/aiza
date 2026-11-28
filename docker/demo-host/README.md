# docker/demo-host: the machine that runs aiza's public demo

The public demo lets a few people try aiza together in a *room*: one person
creates it, invites the others with one-time links, and each works with an
AI (the `agent` session, `docker/box/`) in a box of their own. This directory
is the host side; the room is `docker/room/`, the box `docker/box/`.

```
browser ─TLS─▶ TLS proxy (Caddy etc.) ─▶ aiza-demo-door (127.0.0.1:8890: seats, invites, signed hand-off)
                 └▶ VM 10.77.0.2:<20101..> room-<room> (docker/room, runc, no way out)
                       └▶ sandbox exec ─unix socket─▶ aiza-demo-boxd@<room>:<seats> ─▶ box-<room>-<n> (docker/box, gVisor)
                                                                                     └▶ aiza-demo-relay (10.77.0.1:3128) only
```

| File | Where | What |
|---|---|---|
| `aiza-demo-door` (+ `.service`) | host | Seats are paths (`/r/<seat>/`). A one-time invite (`/r/<seat>/_door/join#<token>`, stored hashed) becomes a cookie for that path only, so one browser can be several people, one tab each. Every request: the cookie is checked, `X-Demo-*` from outside dropped, and `X-Demo-Room/Seat/User/Role/Exp/Sig` added (`Sig` = HMAC-SHA256 with the room's key over `Room\nSeat\nUser\nRole\nExp\nMethod\nTarget`). The room's creator gets `/r/<seat>/_door/` (invite, kick). Rooms end at their time limit or when idle. A room closed before its end is listed in `/var/lib/aiza-demo-closed/closed.json` (`{room: end}`, readable by all) for the relay. CLI: `create`, `list`, `close`, `reissue`. Needs `DOOR_HOST` (the public name) in its environment. |
| `aiza-demo-relay` (+ `.service`, `relay.json.example`) | host | The only way out of the boxes. `/anthropic/v1/messages` (and `count_tokens`) only: checks the seat's stand-in key (`demo.<room>.<user>.<until>.<sig>`, good until the room's end, and refused at once once the door lists the room as closed; a list it cannot read refuses all), refuses any control character in the request head, reads the body as JSON and writes it out again (one value per key), lets through only the keys, the agent's own tools (no server tools, no URL or file sources, no MCP servers), the beta flags and the models the demo's agent uses, caps `max_tokens`, puts the real API key in its place, and keeps a daily budget per seat, room and in all (an amount is set aside for each request in flight, a seat has a limit on requests at once; 429 with `x-should-retry: false` past it). `CONNECT` to GitHub's hosts only. Everything else 403. The real key and the signing secret come as systemd credentials. |
| `vm/aiza-demo-vmctl` (+ `vm/aiza-demo-vmctl-ssh`, `vm/sudoers-aiza-demo-door`) | VM | `start`/`stop`/`kick` rooms, run by the door over ssh as a forced command; `setup` makes the docker networks and their firewall (boxes reach the relay only; rooms nothing). |
| `vm/aiza-demo-boxd` (+ `vm/aiza-demo-boxd@.service`), `vm/sandbox` | VM | One per room. The room's `sandbox exec` (bound into the room at `/usr/local/bin/sandbox`) passes its stdio over a unix socket; the caller's uid picks their box (demo<n> = uid 1000+n). Boxes: gVisor, read-only root, `/tmp` and `$HOME` writable, 1 GB, no capabilities, no DNS. |

Setting up a host (outline): a VM (KVM) on a bridge of its own with no route
out, the host's firewall letting the VM reach only the relay (and a package
cache while installing); Docker and gVisor (`runsc`) in the VM; the units above;
a TLS proxy for the public name in front of the door; the API key in
`/etc/aiza-demo/anthropic.key` (root, 0600) and a random `relay.secret`; the closed rooms' folder
(`install -d -o aiza-demo-door -g aiza-demo-door -m 755 /var/lib/aiza-demo-closed`). Every page and answer of a room
carries `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer` (aiza-gateway). The TLS proxy passes
a bare LF in a request head as a line end; that is harmless here because the door drops every `X-Demo-*` header
by name before adding its own. Keep the proxy's access log readable by its own user only. Build
`docker/room` and `docker/box` (from the public tree) on the host and
`docker save | docker load` them into the VM.

Who may create rooms is whoever can run `aiza-demo-door create` on the host.
Use an API organisation that holds only what you mean to spend: the relay's
budget is a second line, not the first.
