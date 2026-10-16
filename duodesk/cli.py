import argparse
import socket


def _serve(args):
    from .protocol import Connection
    from .server import Server

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((args.host, args.port))
    s.listen(1)
    print(f"[duodesk] server on {args.host}:{args.port}  (other computer is on the {args.edge})")
    print("[duodesk] waiting for a client to connect...  (Ctrl+C to quit)")
    try:
        while True:
            conn_sock, addr = s.accept()
            conn_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[duodesk] client connected from {addr[0]}")
            server = Server(Connection(conn_sock), edge=args.edge,
                            clipboard=not args.no_clipboard,
                            images=not args.no_images, speed=args.speed,
                            edge_px=args.edge_size, debug=args.debug)
            server.run()
            print("[duodesk] client disconnected; waiting again...")
    except KeyboardInterrupt:
        print("\n[duodesk] bye")


def _connect(args):
    from .protocol import Connection
    from .client import Client

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((args.host, args.port))
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"[duodesk] connected to server {args.host}:{args.port}")
    print("[duodesk] ready. Push the mouse against the shared screen edge on the server.")
    client = Client(Connection(sock), clipboard=not args.no_clipboard,
                    images=not args.no_images, speed=args.speed, debug=args.debug)
    try:
        client.run()
    except KeyboardInterrupt:
        client.stop()
        print("\n[duodesk] bye")


def _permcheck(args):
    import sys

    if sys.platform != "darwin":
        print("[duodesk] permcheck is macOS-only; on Windows just allow the firewall prompt.")
        return
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
    except Exception as e:
        print("[duodesk] could not load macOS API:", e)
        return
    trusted = AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    if trusted:
        print("[duodesk] Accessibility: GRANTED. You're good to run the server.")
    else:
        print("[duodesk] Accessibility: NOT granted.")
        print("  A system dialog should have opened, and THIS app was added to")
        print("  System Settings > Privacy & Security > Accessibility (unchecked).")
        print("  Turn it ON there, also add it under 'Input Monitoring', then FULLY")
        print("  quit this terminal app (Cmd+Q) and reopen it before running again.")


def _gui(args):
    # Prefer the HTML/webview UI; fall back to the plain tkinter one.
    try:
        import webview  # noqa: F401

        from .webgui import main as gui_main
    except Exception:
        from .gui import main as gui_main
    gui_main()


def _unfreeze(args):
    import sys

    if sys.platform != "darwin":
        print("[duodesk] unfreeze is macOS-only.")
        return
    import Quartz

    Quartz.CGAssociateMouseAndMouseCursorPosition(True)
    print("[duodesk] mouse cursor re-associated. If it was stuck, it should move now.")


def _selftest(args):
    import socket as _s

    from .protocol import Connection
    from .screen import get_screen_size

    a, b = _s.socketpair()
    ca, cb = Connection(a), Connection(b)
    ca.send({"t": "hello", "n": 1})
    ca.send({"t": "move", "dx": 3, "dy": -2})
    print("recv:", cb.read())
    print("recv:", cb.read())
    print("screen:", get_screen_size())
    print("selftest ok")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="duodesk",
        description="Share one keyboard/mouse/clipboard between two computers over the LAN.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("server", help="run on the machine whose keyboard/mouse you use")
    ps.add_argument("--host", default="0.0.0.0")
    ps.add_argument("--port", type=int, default=24800)
    ps.add_argument("--edge", choices=["right", "left"], default="right",
                    help="which side the OTHER computer physically sits on")
    ps.add_argument("--no-clipboard", action="store_true")
    ps.add_argument("--no-images", action="store_true", help="sync text only, skip image clipboard")
    ps.add_argument("--speed", type=float, default=1.0,
                    help="mouse sensitivity sent to the client; lower = slower (try 0.5 or 0.35)")
    ps.add_argument("--edge-size", type=int, default=2,
                    help="how many px from the edge triggers the jump (raise to 4-6 if it misses)")
    ps.add_argument("--debug", action="store_true", help="print what the server is capturing")
    ps.set_defaults(func=_serve)

    pc = sub.add_parser("client", help="run on the machine being controlled")
    pc.add_argument("--host", required=True, help="server (other machine) IP address")
    pc.add_argument("--port", type=int, default=24800)
    pc.add_argument("--no-clipboard", action="store_true")
    pc.add_argument("--no-images", action="store_true", help="sync text only, skip image clipboard")
    pc.add_argument("--speed", type=float, default=1.0,
                    help="mouse sensitivity multiplier; lower = slower (try 0.5 or 0.35)")
    pc.add_argument("--debug", action="store_true", help="print what the client is receiving")
    pc.set_defaults(func=_connect)

    pg = sub.add_parser("gui", help="open the point-and-click window")
    pg.set_defaults(func=_gui)

    pt = sub.add_parser("selftest", help="verify the install works on this machine")
    pt.set_defaults(func=_selftest)

    pp = sub.add_parser("permcheck", help="macOS: pop the Accessibility permission dialog")
    pp.set_defaults(func=_permcheck)

    pu = sub.add_parser("unfreeze", help="macOS: re-enable the mouse cursor if it got stuck")
    pu.set_defaults(func=_unfreeze)

    args = p.parse_args(argv)
    args.func(args)
