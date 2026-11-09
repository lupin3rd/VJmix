<p align="center">
  <img src="logo.svg" alt="VJmix" width="420">
</p>

# VJmix

VJ controller for **Vimix**, driven by **viOSC**.

An 8×8 step sequencer that fires OSC messages to Vimix in sync with the music
(VU/BPM analysis, MIDI clock, band peaks), with a thumbnail grid, a **Mapper**
that maps an origin to a destination (a live Vimix property, an audio band or a
MIDI/Leap control to Vimix, a controller LED or third-party OSC), an **I/O
Monitor** that shows the MIDI and OSC traffic in both directions, and optional
MIDI controller support (Novation Launchpad profiles included).

[![Watch the video](https://img.youtube.com/vi/dtzOFJbv7ko/maxresdefault.jpg)](https://youtu.be/dtzOFJbv7ko)

## Quick start — AppImage (Linux)

The easiest way to run VJmix on Linux is the self-contained AppImage: a single
file with Python, all libraries and the app bundled — **no Python, no pip, no
root** (PortAudio included, so no `libportaudio2` package is needed). Download
`vjmix-<version>-x86_64.AppImage` from the
[GitHub Releases](https://github.com/lupin3rd/VJmix/releases) page, then:

```bash
chmod +x vjmix-1.3.0-x86_64.AppImage
./vjmix-1.3.0-x86_64.AppImage
```

### Where your data lives

- Config: `~/.config/vjmix/vjmix_config.json` (honors `$XDG_CONFIG_HOME`).
- Controller profiles: drop custom `*.json` profiles into
  `~/.config/vjmix/controllers/` (the Launchpad profiles ship built-in).
- Projects: the Open/Save dialogs default to `~/.config/vjmix/projects/`; you
  can save anywhere you like.

## Quick start — from source (developers)

Requires Python 3.13 and **PortAudio**, which `sounddevice` loads from the system
at import time (the AppImage carries its own, a source checkout does not):

```bash
sudo apt install libportaudio2      # Debian/Ubuntu (Fedora: dnf install portaudio)
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python vjmix.py
```

## Requirements

- [viOSC](https://github.com/lupin3rd/viosc) **1.0.0+** — the daemon that speaks
  to Vimix. It must run on the same machine as Vimix; VJmix reaches it over the
  network. A pre-1.0 viOSC is refused with one visible line.
- [Vimix](https://github.com/brunoherbelin/vimix) **0.9.3 stable or newer** — the
  stable release that carries the OSC fixes VJmix relies on (some of them are not
  documented in the Vimix wiki yet).
- (optional) a Novation Launchpad MK1/MK2/MK3 for pad control

## How VJmix talks to Vimix

VJmix never speaks OSC to Vimix: **viOSC does**, on the machine where Vimix runs.
Between the two apps there is one HTTP link, one port, one token (the pairing
code viOSC shows at start), and everything travels on it:

- **Commands.** Every Mapper, Sequencer, Cue and toolbar action is sent as a JSON
  frame (`{"address": "/vimix/…", "args": [...]}`) on one long-lived chunked
  `POST /link` stream. Ordered, nothing lost, and value sets coalesce per address
  while the link is down so a reconnection lands on the newest value.
- **State.** viOSC keeps the mirror of the session. VJmix reads it as a snapshot
  (`GET /state`, revision + `ETag`, `304` when nothing changed) and follows it
  with an ordered delta stream (`GET /events`, Server-Sent Events). What the
  Mapper needs at a higher rate is declared explicitly with `POST /interest`.
- **Everything else** — thumbnails (`/thumb`), media preview and metadata
  (`/preview`), a read-only file manager for sessions and media (`/fs`), and the
  daemon's own configuration (`/config`) — is a plain HTTP resource on the same
  port.
- **The link has a state**, shown in the viOSC panel and on its LED: `connected`,
  `connecting`, `reconnecting`, `incompatible`.

OSC enters the picture only where something other than viOSC is on the other
end: a Mapper line with an OSC destination, or the Secondary Output. It is never
used to talk to Vimix.

## Support

VJmix is free and GPL-3.0. If it is useful to you, you can buy me a coffee -
a thank-you, never a requirement.

[![Buy me a coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/lupin3rd)

## License

VJmix is **GPL-3.0** — see [LICENSE](LICENSE).

It bundles third-party libraries and two Apache-2.0 hand-tracking models. Every
component, with its exact version, licence, copyright holder and source, is in
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md); the licence texts themselves
— including the AGPL-3.0 text of `essentia` and the Apache-2.0 text of the
models — ship in [`licenses/`](licenses/) and inside the AppImage
(`opt/vjmix/licenses/`).
