# nest-kvm

Share **one keyboard, mouse and clipboard** between your Mac and your Windows
laptop over the same Wi-Fi — exactly like Input Leap / Barrier / Synergy, but
small and yours to extend.

- Move the mouse to the screen edge that faces the other laptop → the cursor
  jumps over and drives that machine. Move it back → control returns.
- Copy on one machine, paste on the other (clipboard **text** syncs both ways).
- **Nothing else is shared.** Each laptop keeps its own OS, apps and files. No
  screen mirroring, no data merge — only mouse, keyboard and clipboard text
  travel over the network.

> **server** = the machine whose keyboard/mouse you physically use.
> **client** = the machine that gets driven.
> To drive from the *other* laptop, just swap: run `server` there and `client` here.

---

## 1. Install (on BOTH laptops)

Needs Python 3.9+.

```bash
cd nest-kvm
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m nestkvm selftest       # should print two messages, a screen size, "selftest ok"
```

## 2. Grant permissions

**macOS** (required — the OS blocks input capture/injection otherwise):
System Settings → Privacy & Security →
- **Accessibility** → add & enable your Terminal (or iTerm)
- **Input Monitoring** → add & enable the same app

Then fully quit and reopen the terminal.

**Windows:** first run pops a firewall prompt — allow it on Private networks.

## 3. Run

Say the Windows laptop sits to the **right** of the Mac, and you want to use the
**Mac's** keyboard/mouse.

On the **Mac** (server):
```bash
python -m nestkvm server --edge right
```

Find the Mac's LAN IP: `ipconfig getifaddr en0` (e.g. `192.168.1.20`).

On **Windows** (client):
```bash
python -m nestkvm client --host 192.168.1.20
```

Now shove the mouse off the right edge of the Mac screen — it appears on Windows.
Push it back to the left edge of Windows to return to the Mac.

Swap `--edge left` if the other laptop is on your left.

### Drive the Mac from Windows instead
Run `server` on Windows and `client` on the Mac — same commands, roles swapped.

---

## 4. How it works (for when you extend it)

```
nestkvm/
  protocol.py   length-prefixed JSON framing over one TCP socket
  screen.py     primary-display pixel size per OS
  keys.py       (de)serialize pynput keys/buttons <-> plain dicts
  clipboard.py  polls the clipboard, syncs text both ways (echo-guarded)
  server.py     capture + edge detection + suppress-and-forward
  client.py     receive + inject, tracks cursor, hands control back at the edge
  cli.py        `server` / `client` / `selftest`
```

Message types on the wire (all JSON): `enter`, `move`, `down`, `up`, `scroll`,
`kd`, `ku`, `clip`, `leave`. Add a new feature = add a new `"t"` value and handle
it on the other side. Nothing else to touch.

The server flips between two modes with a single manager thread: LOCAL (one plain
mouse listener watching for the edge) and REMOTE (suppressing mouse+keyboard
listeners that forward everything; the cursor is warped back to screen-centre each
move so it never sticks to a real edge, and we send the delta from centre).

## 5. Known rough edges (MVP)

- **Mouse feel on macOS-as-server:** macOS re-associates hardware deltas ~¼s after
  each cursor warp (`CGAssociateMouseAndMouseCursorPosition`), which pynput doesn't
  expose, so the pointer can feel slightly sticky while driving from a Mac. Driving
  *to* the Mac (Windows-as-server) is smooth. Fixable later with a small Quartz tweak.
- **Keyboard layouts / shifted symbols:** keys are forwarded by character, so an
  unusual layout may mis-type some symbols. Basic typing, arrows, enter, backspace,
  modifiers work.
- **No encryption / no auth yet:** use only on your own trusted home Wi-Fi. TLS +
  a shared token is an easy next addition.
- **One client at a time.**

## 6. Ideas to add next

Drag-and-drop file transfer · a hotkey to force-return control · TLS + pairing
code · multi-monitor edge maps · auto-reconnect · a tray icon.
