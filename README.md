# Harmonic Beacon Spatializer

13-band binaural spatializer for the Harmonic Beacon (40.4 Hz natural harmonic series). Each band has independent gain, azimuth, distance, and (for BPF bands) Q, rendered over headphones via ATK HRTF.

**Current engine:** SuperCollider (`beacon.scd`) — 12 BPF + 1 HPF @ 1818 Hz, ATK `FoaPanB` / `FoaDecode` with Listen kernels @ 48 kHz, plus a native looping mono/stereo nature-WAV layer. OSC control on port **57120**. Flask web UI on **:5050**.

## Quick Start

### 1. One-time setup (venv)

```bash
cd ~/Projects/beacon-spatial
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Start everything (recommended)

```bash
./start-beacon.sh          # --live default: Zoom R24 CH1 → SoundIn.ar(0)
./start-beacon.sh --file   # loop harmonic_beacon_2026_05_13_session.wav
./start-beacon.sh --no-https  # skip cloudflared tunnel
```

The launcher:

1. Starts `pw-jack scsynth` on port **57110** (2 in / 2 out)
2. Auto-connects JACK (Built-in + R24; R24 CH1 → `SuperCollider:in_1`)
3. Runs `sclang beacon.scd` (OSC on **57120**, wrapped in `script` for a pseudo-TTY)
4. Starts Flask from `venv` at http://localhost:5050
5. Optionally raises a `cloudflared` HTTPS tunnel (needed for phone sensors)

Press **Ctrl-C** to stop all child processes.

### 3. Open the UI

```
http://localhost:5050
```

Three tabs: Manual / Sensors / Presets. Changes go live over OSC to the 13-band engine.

## Files

| File | Role |
|------|------|
| `start-beacon.sh` | Canonical launcher (`pw-jack scsynth`, sclang, Flask, optional HTTPS) |
| `beacon.scd` | Main engine: 13 bands, ATK FOA binaural + nature WAV layer, 74 OSCdefs on 57120 |
| `legacy/beacon_pd_replica.scd` | Optional 6-band PD-algorithm replica (OSC on 9001) |
| `legacy/start-beacon-pd.sh` | Starts the replica alongside the main engine |
| `webui.py` | Flask control surface (:5050); HTTP → OSC to 57120 (and 9001 if up) |
| `beacon-osc.json` | Open Stage Control template (see `beacon-osc.ANNOTATIONS.md`) |
| `harmonic_beacon_2026_05_13_session.wav` | File-mode source loop (mono 48 kHz; large, often not in git) |
| `configs/` | JSON presets (`bands[]` + mix/master; optional sensor_mappings) |
| `assets/nature-samples/` | Nature WAVs for the sample layer — samples live **outside git** (ignored); `MANIFEST.md` (tracked) lists each file with size, SHA-256, and provenance |
| `requirements.txt`, `venv/` | Python deps for the web UI |
| `legacy/` | Frozen Pure Data stack (patches, replica, bridge, launchers, OSC tests) — not the active path |
| `docs/research/` | Historical multi-agent engine-selection notes (May 2026) |

SuperCollider is the only runtime; everything PD lives under `legacy/`.

## Architecture

```
Browser (http://localhost:5050)
    |
    | HTTP POST /control, /control/batch, presets, …
    v
Flask (webui.py)
    |
    | OSC UDP :57120          (optional copy :9001 → PD replica)
    v
sclang (beacon.scd) — OSCdef → synth.set
    |
    v
scsynth -u 57110 via pw-jack
    |
    | source → 12× BPF + HPF@1818 → solo → dry Mix*(1-mix)
    |                              → wet FoaPanB(az,1/dist) → FoaDecode(Listen)
    | → (wet+dry)*master → Out.ar(0, 2)
    | nature WAV → sample_player(gain, release) ───────────→ Out.ar(0, 2)
    v
PipeWire/JACK → headphones (binaural)
```

**Source modes** (`BEACON_SOURCE` via launcher flags):

- `--live` (default): `SoundIn.ar(0)` from Zoom R24 CH1
- `--file`: `PlayBuf` loop of `harmonic_beacon_2026_05_13_session.wav`

No reverb, no LFOs on the main engine (static spatialization by design).

## OSC (summary)

Continuous controls take one float per message; band index is **in the address**, not an argument. Nature loading takes one absolute local WAV path string.

| Address | Range | Notes |
|---------|-------|-------|
| `/beacon/gain/N` | 0–3 | N = 1..13 |
| `/beacon/az/N` | −180..180 | N = 1..13 |
| `/beacon/dist/N` | 0..10 | N = 1..13 |
| `/beacon/q/N` | — | N = 1..12 (BPF only) |
| `/beacon/solo/N` | 0/1 | N = 1..13 |
| `/beacon/mix` | 0..1 | wet/dry balance (not separate wet/dry) |
| `/beacon/master` | 0..3 | |
| `/beacon/nature/load` | absolute WAV path | loop a readable mono/stereo local WAV; invalid loads leave the active layer unchanged |
| `/beacon/nature/gain` | 0..1 | bounded linear gain with 50 ms lag |
| `/beacon/nature/stop` | — | release playback and free the active sample synth/buffer |
| `/beacon/record/start` | path optional | start WAV record |
| `/beacon/record/stop` | — | |
| `/beacon/reset` | — | defaults |

Replica on **9001** uses the same scheme for N=1..6 only. Full detail: `MEMORY.md`, `PD_REPLICA_OSC_SCHEME.md`.

## 13-band layout

| Band | Freq | Type |
|------|------|------|
| 1–6 | 40.4 / 80.8 / 121.2 / 161.6 / 202 / 242.4 Hz | BPF (40.4 Hz bandwidth) |
| 7–12 | 484.8 / 727.2 / 969.6 / 1212 / 1454.4 / 1696.8 Hz | BPF (240.4 Hz bandwidth) |
| 13 | 1818+ Hz | HPF |

## Important

- **Headphones required.** Listen HRTF binaural only works on headphones.
- SuperCollider + ATK quark + Listen FOA decoder kernels at 48 kHz.
- Use `pw-jack scsynth`, not a bare `jackd` session (PipeWire exclusive-mode conflicts).
- sclang must run with a pseudo-TTY (`script` in the launcher); plain daemon mode exits.
- Phone sensors need HTTPS (auto-tunnel) or a secure origin.

## Harmonic Lab joint startup

The maintained Weaver checkout provides `scripts/start-live-stack.sh --guitar-lab`:
Guitar controls plus R24 channel1 through this Spatializer to R24 stereo playback.
It calls the existing Spatializer launcher with `--live --no-https`, keeps the
controller's explicit actuation/save controls, and can optionally start the usual
Weaver/Shaper/HarMoCAP laboratory. It creates no new App or account/transport.

`BEACON_OUTPUT_TARGET=r24|internal|both` selects the existing launcher's output
(default `both` preserves standalone behavior; the joint lab chooses `r24`).
`beacon_routes.py` changes only this SuperCollider client's links and verifies
CH1 input and the chosen outputs. A missing R24 fails rather than using a webcam
or built-in microphone. `beacon_routes.py --output r24 --check` only observes.
The old generic "connected" print did not establish actual JACK links.

Component logs retain only their latest1MiB under
`${XDG_STATE_HOME:-$HOME/.local/state}/beacon-spatial`, or `BEACON_LOG_DIR`.
No log archive or recorded audio is added. Existing named source channels,
presets and default audio devices remain separate from this explicit routing.

The launcher selects `scsynth -l32` explicitly: this remains within sclang
ServerOptions.maxLogins<=32 even on scsynth versions whose default is64.
The receiving default64 produced a real initial login error before recovery;
current successful audio/OSC readiness is distinct from that retained error.

## macOS receiving route (implementation pending native acceptance)

`start-beacon.sh` dispatches to the CoreAudio companion on macOS. It reuses the
same `beacon.scd`, native OSC contract and web UI; it does not invoke PipeWire,
ALSA, `ss`, or Linux `script -c`. Select exact native audio device names first:

```sh
export BEACON_INPUT_DEVICE='Exact CoreAudio input name'
export BEACON_OUTPUT_DEVICE='Exact CoreAudio output name'
./start-beacon.sh --live --no-https
```

The names above are placeholders, never a claim about the receiving hardware.
SuperCollider can be on PATH or in its ordinary `/Applications` bundle;
`BEACON_SCLANG` and `BEACON_SCSYNTH` select existing binaries explicitly. Reuse
`venv`/`.venv` with the repository requirements, installed ATK/sc3 plugins and
kernels. A missing device selection or environment fails without choosing a
webcam/system microphone. The native runner is bounded to8h, uses the same
1MiB latest-tail logger and terminates only process groups it created.

`BEACON_AUDIO_FILE` selects an existing WAV for `--file`; the default is now
relative to `beacon.scd` rather than a developer's home directory. File mode
requests zero hardware input channels. No sample/model/archive is downloaded.
`python3 beacon_macos.py --describe` validates configuration and prints planned
commands without launching audio. It does not establish actual device support.

The native UI binds loopback. There is no public tunnel in this native path;
phone sensor HTTPS delivery is a separate existing integration. Camera/audio
permissions and real input/output require receiving tests, not Linux fixtures.
Native code and lifecycle plans are unit-tested; Mac audio, ATK availability,
latency and human listening are not yet qualified. The full lab's macOS route
and installation record are maintained in harmonic-weaver's MACOS guide.

Native device command reference:
https://doc.sccode.org/Reference/Server-Architecture.html ;
https://doc.sccode.org/Reference/AudioDeviceSelection.html .

The laboratory reference is 40.4 Hz, matching the tuned guitar and Shaper.
Band indices, gains, spatial controls and RQ presets remain compatible; unchanged
RQ values scale absolute bandwidth with the new centers. The high-pass crossover
is 45 times the reference (1818 Hz). Saved controls do not override these centers.
After updating, reload the Spatializer engine and UI through its existing scoped
launcher; snapshot and restore native OSC controls first to preserve active mixes.
Do not restart the guitar controller or body lab for a Spatializer tuning update.
