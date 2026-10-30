# Devices: platform, packaging and tooling

The safety rules for working on a real device are in [AGENTS.md](../AGENTS.md) ("Devices") and
always apply. The device commands are in [TESTING.md](../TESTING.md).

## Target platform

| Item | Value |
|---|---|
| OS | The SpruceOS it ships in: Cheevos is bundled with Spruce, so the bridge needs only the PyUI it was verified against (`pyui-tested-commit`). Needs PyUI views, `spruce/scripts/appEnv.sh` and RAOfflineProxy 2.x. |
| Devices | Every device supported by SpruceOS. |
| Resolutions | Every resolution the default SPRUCE theme ships: 640×480, 720×480, 752×560, 720×720, 960×720, 1024×768, 1280×720, 480×800. |
| Runtime | Spruce's CPython **3.10.18**: `$SPRUCE_PYTHON` (32-bit: `spruce/bin/python/bin/python3.10`; 64-bit: `spruce/flip/bin/python3.10`). |
| Built-in modules we rely on | `ssl` (OpenSSL 3.5), `sqlite3`, `json`, `hashlib`, `zlib`, `ctypes`, `zoneinfo` |
| Third-party | **None of our own.** PySDL2 0.9.17 is loaded only indirectly, through PyUI. No `requests`, no Pillow. |
| UI toolkit | PyUI, imported at runtime from `/mnt/SDCARD/App/PyUI/main-ui` ([pyui.md](pyui.md)). |
| TLS | CA bundle at `$SSL_CERT_FILE` (`/mnt/SDCARD/spruce/etc/ca-certificates.crt`). An unset/incorrect clock or another TLS failure uses HTTP automatically. RA's Date supplies app time without changing the device clock. |

## Packaging

```
/mnt/SDCARD/App/Cheevos/
  config.json     {"label": "Cheevos", "icon": "cheevos.png", "pyuiEntry": "cheevos.native:run",
                   "description": "RetroAchievements hub", "gameProgress": 2}
                  (no "launch": PyUI runs it in its own process; no "devices": every device)
  identify-rom.sh Spruce's game menu runs it to identify a ROM: sources appEnv.sh and execs
                  -m cheevos.platform.identify_rom, headless ([integration.md](integration.md))
  cheevos.png     app icon
  cheevos/        the Python package, with res/icons
  cache/          created at runtime
```

- `make package` builds it into `dist/App/Cheevos/` (no desktop runner, no tests) and zips that
  as `dist/Cheevos-<version>.zip`, with the `Cheevos/` prefix and no `App/` folder.
  `identify-rom.sh` is executable: Spruce runs it directly.
- The Apps launcher discovers any `App/*/config.json`. With `"pyuiEntry"`, PyUI runs Cheevos
  inside its own process and unloads it when it closes ([pyui.md](pyui.md), "In-process
  sessions"); it needs a SpruceOS whose PyUI has `apps/native_app.py`. An app with no `"launch"`
  is known to PyUI's hidden-apps list by its folder.
- `config.json`'s `"gameProgress"` tells Spruce what the package supports: 1 for opening one
  game (`run(game_id=N)`), 2 when `identify-rom.sh` ships too. Raise it only with a new contract
  Spruce checks for.
- **No `devices` list:** a `devices` list in an app's `config.json` hides it on every device not
  named there. Cheevos ships without one, so the Apps menu shows it on every device: it runs
  wherever PyUI does, with no platform set-up of its own.
- **Failures:** `cheevos.native.run` logs an error and shows a message; PyUI does the same for
  one it raises before Cheevos's code runs ([product.md](product.md), "Offline and error
  behaviour").
- The release is that zip; users copy its `Cheevos` folder into `App` on the SD card. Pushing a
  `v<version>` tag publishes it as a GitHub release (the `release` job in `ci.yml`; steps in
  [RELEASING.md](../RELEASING.md), under "Releases"). The description links merged PR titles
  and direct commit titles.
  Pre-releases start at the previous version tag; stable releases start at the previous stable tag.
  Stable releases are mirrored into SpruceOS's `App/Cheevos/` through an upstream PR.

## Device gotchas (verified on a Miyoo Mini+, SpruceOS 4.5.0)
- **Idle check:** a test once replaced the cache under an open session; hence the rule to check
  that neither Cheevos nor a game is running first.
- **Stray taps:** once Cheevos exits (B on its home screen), further taps reach Spruce's menu,
  where A starts a game. A blind tap loop once launched a game this way. `device.sh press` now
  refuses on the device unless Cheevos is running, and stops at the first refusal. Opened from
  the menus, Cheevos has no process of its own: `device.sh running` (which `press` uses) looks
  for PyUI holding the app's log open, or for a `make launch` session. In PyUI's own menus, A
  on Settings' first row powers off. Still, take a screenshot between screens rather than
  sending long sequences.
- **`pgrep -f` self-match:** a plain `pgrep -f` pattern also matches the remote shell's own
  command line. Use the `[x]` trick (`'[c]heevos'`), and keep the plain text out of the rest of
  the same remote script too: a later `grep "python3.10 -m cheevos..."` once made an idle check
  find "Cheevos" (the shell itself).
- **Backups must stay off device `/tmp`.** It is RAM-backed tmpfs. An 18 MB app backup
  during integration testing caused memory pressure, thread creation failures and a device
  freeze. Stream backups over SSH to the development machine and deployment archives straight
  to the SD card; never stage a full backup or package in the device's `/tmp`. Small, bounded
  test fixtures and the app's image scratch are fine.
- **busybox limits:** busybox tar rejects pax/xattr headers, so deploy uses
  `COPYFILE_DISABLE=1 tar --format ustar`. Busybox `sort` has no `-h`.
- **SSH:** ssh's ControlPath must be under ~104 bytes, so the control socket lives in
  `/tmp/cheevos-mini-%C`.
- **Screenshots:** `fbgrab` output is upside down; rotate it 180° (Spruce's `screenshot.sh`
  does the same).
- **Input injection:** `send_event /dev/input/event0 CODE:1|0`. Codes: A=57, B=29, X=42,
  Y=56, Start=28, Select=97, L1=18, R1=20, D-pad 103/108/105/106. Never send MENU (1), power
  or combos.
- **Running a command remotely:** write `/tmp/cmd_to_run.sh` (PyUI's own format), then send
  SIGTERM to PyUI; `principal.sh` runs the command and restarts PyUI afterwards. It also
  records the command for autoresume. `make launch` uses it ([pyui.md](pyui.md), "In-process
  sessions").
- **Graphics memory:** SDL textures come from the MMA pool (`mma_heap=…sz=0x1500000`, 21 MB),
  not from the RAM `MemAvailable` reports. The framebuffer and PyUI's screen-sized canvases
  take about 11.5 MB of it, leaving about 9 MB for textures. Free space:
  `/proc/mi_modules/mi_sys_mma/mma_heap_name0` (`chunk_mgr_avail`, hex). Big textures need
  one contiguous block. See [pyui.md](pyui.md), "Texture caches never evict".
- **Log times are UTC** (marked `Z`), comparable with logs from before the app ran inside
  PyUI (which applies the saved time zone partway through its start-up).
- **PIDs wrap at 4096**, so a low PID doesn't mean an old process. Check
  `/proc/<pid>/stat` against `/proc/uptime` for its age.
- **Network services:** Spruce restarts Samba and SFTPGo after every app exits; SSH (dropbear)
  survives.
- **Storage, `/tmp` and the clock:** see [sync-and-storage.md](sync-and-storage.md).
- **What the desktop can't show:** the MMIYOO SDL driver's quirks (translucent fills, see
  [pyui.md](pyui.md)), real speed, FAT32, the real proxy, Wi-Fi and an unset clock.

## Performance (Miyoo Mini+)

The hardware: a dual-core Cortex-A7 at 1.2 GHz, 128 MB RAM (103 MB for Linux, the rest for the
graphics pool), slow SD writes. Big lists and image-heavy screens need a check on it.
- **Inside PyUI** (2026-10-30): the same memory as the separate process it used to be while
  open, and ~6-7 MB kept by PyUI after it closes, flat from one session to the next; opens in
  0.5 s ([pyui.md](pyui.md), "In-process sessions"). The figures below were taken when Cheevos
  was a separate process (with PyUI exited).
- **Memory headroom is small.** Measured 2026-10-14 on Spruce 4.5.5 nightly with a 2,948-game
  account: about 17 MB available on Home, with RAOfflineProxy's service at 30–36 MB beside
  Cheevos (33–36 MB RSS). Browsing images fills the 4 MB `/tmp` image scratch, and the heap
  levels off at +3–4.5 MB. Below about 8 MB available, starting a thread fails (the kernel's
  heuristic refuses an 8 MB stack): PyUI's Wi-Fi status refresh then raised `can't start new
  thread` and Cheevos exited. 0.1.6 and the Awards carousel both got there after 20–30 pages
  of awards; a long desktop run under `tracemalloc` showed no Python leak.
- **CPU:** measure per thread from `/proc/<pid>/task/*/stat` (fields 14 + 15, 1/100 s ticks);
  100 ticks a second is one core. Busybox `top` shows % of both cores together.

### Opening
Inside PyUI (2026-10-30, Mini+, warm): A to Cheevos running 0.5 s, nearly all of it Python
importing the package from the SD card; Home's first frame 0.05 s later. The first open after an
update also compiles every module (3 s). As a separate process (2026-10-14, 2,948-game
account) Home appeared 4.1–4.5 s after Python started, 3.4 s of it imports: finding and reading
each module from the SD card costs a few ms before its code even runs, and each dataclass
5–7 ms to build.
- **Rule: import what Home's first frame doesn't need on first use.** Every screen but Home
  (`home._open`), the badge grid and carousel (`views`), the RA client and transport (`app`'s
  factories), the sync engine (on the sync thread, `background`) and `email.utils` (`clock`)
  load when first used; `ra_client/__init__.py` imports nothing. Names the UI needs without
  the engine live in `sync/options.py`; `Credentials` lives in `core/credentials.py`.
  `tests/unit/test_startup_imports.py` fails if any of them loads with `cheevos.native` (what
  PyUI imports): add a new screen or worker to its list. The modules that import on first use
  are listed in `pyproject.toml`'s per-file `PLC0415` ignores. The cost moves to each screen's
  first opening (Games +0.3 s, Profile +0.2 s, Awards +0.1 s the first time). Inside PyUI every
  open imports the package again, since closing unloads it.
- **The auto-sync starts after Home's first frame** (`Home(sync_when_shown=...)`, on its
  first tick): started before, the sync thread's imports competed with the first frame
  (+0.3 s).
- **ROM identification helper** (`identify-rom.sh`), measured 2026-10-18 on the Mini+ with
  Spruce 4.5.5 and RAOfflineProxy 2.2.0-alpha1 nightly 54, warm, from the shell to the JSON:
  a saved path 0.6-0.7 s (1.3 s on the first run, compiling bytecode): `appEnv.sh` 0.05 s,
  Python 0.12 s, the helper's imports 0.43 s (argparse, logging, dataclasses and pathlib lead),
  the lookup under 10 ms. A hash the proxy has cached (CHD, CUE): 1.4-1.6 s. A new ROM asked
  of RA: 2.7-3.1 s for a small ROM, 6.2-6.7 s for a 16-32 MB zipped GBA ROM (extraction to SD
  dominates). Helper RSS 8.5 MB for a saved path, at most 15 MB with TLS; MemAvailable stayed at
  13 MB or more with PyUI, the proxy service and the helper resident. In the game menu, Spruce
  shows "Checking RetroAchievements..." for that time, then hands over to Cheevos (3 s more to
  its first frame). Started from PyUI, the same saved path took 0.9-2.4 s from the A press to
  the answer, so Spruce now reads saved matches itself ([integration.md](integration.md)).
- **An uncached ROM, by stage** (SNES zip, from Cheevos's own modules, 2026-10-18): Python
  0.12-0.4 s, `cheevos.platform.paths` import 0.35 s, `candidates` 0.2 s, the proxy's
  `rom_hashing` with its library 0.2 s, extracting and hashing 0.25 s, `sqlite3` and the
  proxy's cache 0.15 s, `ssl` with `http.client` 0.4-0.5 s, then RA's `r=gameid` 1.6-5.2 s.
  Inside that request: the CA context 0.1 s, DNS 0.3-0.8 s (the first lookup in a process),
  TCP 0.1 s, TLS 0.1 s, the answer 0.1 s. Spruce's `curl` (`spruce/bin{,64}/curl`, c-ares DNS)
  fetched the same answer in 0.3-0.6 s, process included, so the helper now asks RA with it
  ([integration.md](integration.md)). Same build, alternating runs, PyUI busy in its menu
  (load average 4): the RA step 0.6-1.3 s through curl against 1.8-2.1 s through Python; a
  whole new SNES zip 2.5-3.7 s against 3.8-4.2 s. A hash in the proxy's cache never asks RA
  (1.9-2.1 s either way). The first lookup after a reboot spent 11 s hashing and reading the
  proxy's cache, against 0.25 s afterwards.
- **How it was measured:** a patched build (never shipped) logs the first frame's time from
  the process start (`/proc/self/stat`), and can run `cProfile` up to it. `make launch` passes
  `DEVICE_PYTHON_FLAGS` to PyUI's Python (e.g. `-X importtime`, written to
  `/tmp/cheevos-dev/stderr.log`).
