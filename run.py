"""Start ReliefGrid:  python run.py

Opens http://localhost:8000 in your browser. API docs are at http://localhost:8000/docs
Options:  python run.py --port 8080   |   python run.py --reset   (reload the sample data)
          python run.py --phones   (drivers and shelters can scan delivery slips with their phones)
"""

import argparse
import json
import os
import socket
import sys
import threading
import urllib.request
import webbrowser

import uvicorn

from app import API_LEVEL, VERSION


def port_in_use(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1" if host in ("0.0.0.0", "localhost") else host, port)) == 0


def running_version(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=1) as r:
            return json.loads(r.read())
    except Exception:
        return None


def lan_address():
    """This computer's address on the local network (what a phone on the same Wi-Fi uses to reach it)."""
    for probe in ("10.255.255.255", "192.168.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 1))          # no packet is sent; this just picks the outgoing interface
                ip = s.getsockname()[0]
                if not ip.startswith("127."):
                    return ip
        except OSError:
            pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def main():
    parser = argparse.ArgumentParser(description="Run ReliefGrid")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1",
                        help="use 0.0.0.0 to let other computers on the same network open it")
    parser.add_argument("--reset", action="store_true", help="wipe the database and reload sample data")
    parser.add_argument("--empty", action="store_true", help="wipe the database and start with no data (real use)")
    parser.add_argument("--phones", action="store_true",
                        help="let phones on the same Wi-Fi scan delivery slips (driver pick-up, shelter sign-off)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://localhost:{args.port}"
    phone_url = None
    if args.phones:
        args.host = "0.0.0.0"
        ip = lan_address()
        if ip:
            phone_url = f"http://{ip}:{args.port}"
            os.environ["RELIEFGRID_PHONE_URL"] = phone_url
        else:
            print("\n  Couldn't find this computer's Wi-Fi address, so slips will show text instead of a phone link."
                  "\n  Connect to a Wi-Fi network (or turn on a hotspot) and run again.\n")

    if port_in_use(args.host, args.port):
        v = running_version(args.port)
        if v and v.get("api_level") == API_LEVEL:
            print(f"\n  ReliefGrid {v.get('version')} is already running at {url}. Opening it.\n")
            if not args.no_browser:
                webbrowser.open(url)
            return
        who = "an older version of ReliefGrid" if v else "another program (maybe an older ReliefGrid)"
        print(f"\n  Port {args.port} is already in use by {who}."
              + "\n  Close that window (or press Ctrl+C in it), then run this again."
              + f"\n  Or use another port:  python run.py --port {args.port + 1}\n")
        sys.exit(1)

    if args.reset or args.empty:
        answer = input("  This wipes ALL data in reliefgrid.db. Type RESET to continue: ").strip()
        if answer != "RESET":
            print("  Nothing changed.")
            sys.exit(0)
        from app.db.seed import load_empty, load_sample
        (load_empty if args.empty else load_sample)()
        print("  Started with an empty database." if args.empty else "  Sample data loaded.")

    print(f"\n  ReliefGrid {VERSION} is running at {url}\n  API docs: {url}/docs")
    if phone_url:
        print(f"  Phones on the same Wi-Fi can scan delivery slips: they open {phone_url}"
              "\n  (If Windows asks whether to allow Python on private networks, choose Allow.)")
    print("  Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
