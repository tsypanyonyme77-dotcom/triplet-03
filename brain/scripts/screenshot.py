"""Drive headless Chromium over the DevTools protocol: load a page, press keys, save screenshots.

Chromium's own `--screenshot` flag hangs on the timeline screen, whose event stream never
closes; this talks to the browser directly instead.

    uv run brain serve &                                   # the screen at port 8080
    uv run python scripts/screenshot.py 1920x1080 /tmp/shot \\
        goto:http://127.0.0.1:8080/ wait:2 key:2 wait:20 shot:b2 "js:document.title"

Steps run in order: goto:<url>  wait:<seconds>  key:<key>  shot:<name> (saves <prefix>-<name>.png)
js:<expression> (prints the result). Page errors are printed at the end.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

PORT = 9377


async def main(size: str, prefix: str, steps: list[str]) -> None:
    width, height = map(int, size.split("x"))
    browser = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if browser is None:
        sys.exit("error: needs Chromium")
    profile = tempfile.mkdtemp(prefix="screenshot-")
    headed = os.environ.get("SCREENSHOT_HEADED") == "1"  # a real window on the real GPU, with the display's own scale
    flags = [f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", f"--window-size={width},{height}", "--hide-scrollbars", "--no-first-run"]
    if not headed:
        # Software WebGL, so the 3D canopy draws on a machine with no GPU (and in rehearsal).
        flags = ["--headless=new", *flags, "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
    process = subprocess.Popen([browser, *flags, "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                break
            except OSError:
                time.sleep(0.25)
        else:
            sys.exit("error: Chromium did not start")
        page = next(t for t in targets if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            counter, errors = 0, []

            async def call(method: str, **params):
                nonlocal counter
                counter += 1
                await ws.send(json.dumps({"id": counter, "method": method, "params": params}))
                while True:
                    message = json.loads(await ws.recv())
                    if message.get("method") == "Runtime.exceptionThrown":
                        errors.append(message["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:300])
                    if message.get("method") == "Runtime.consoleAPICalled" and message["params"]["type"] == "error":
                        errors.append(" ".join(str(a.get("value", "")) for a in message["params"]["args"])[:300])
                    if message.get("id") == counter:
                        return message.get("result", {})

            await call("Runtime.enable")
            await call("Page.enable")
            if not headed:
                await call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=float(os.environ.get("SCREENSHOT_DPR", "1")), mobile=False)
            for step in steps:
                kind, _, arg = step.partition(":")
                if kind == "goto":
                    await call("Page.navigate", url=arg)
                elif kind == "fullscreen":
                    # a real window only: ask the compositor for the whole screen
                    win = (await call("Browser.getWindowForTarget"))["windowId"]
                    await call("Browser.setWindowBounds", windowId=win, bounds={"windowState": "fullscreen"})
                elif kind == "media":
                    # media:prefers-reduced-motion=reduce, set before the next goto
                    name, _, value = arg.partition("=")
                    await call("Emulation.setEmulatedMedia", features=[{"name": name, "value": value}])
                elif kind == "script":
                    # script:<js> runs on every new document before the page's own scripts (for example to hide WebGL)
                    await call("Page.addScriptToEvaluateOnNewDocument", source=arg)
                elif kind == "wait":
                    await asyncio.sleep(float(arg))
                elif kind == "key":
                    for phase in ("keyDown", "keyUp"):
                        await call("Input.dispatchKeyEvent", type=phase, key=arg, text=arg if phase == "keyDown" and len(arg) == 1 else "")
                elif kind == "js":
                    result = await call("Runtime.evaluate", expression=arg, returnByValue=True, awaitPromise=True)
                    print("js:", json.dumps(result.get("result", {}).get("value"))[:1500])
                    if result.get("exceptionDetails"):
                        print("js exception:", result["exceptionDetails"].get("exception", {}).get("description", "")[:600])
                elif kind == "shot":
                    data = await call("Page.captureScreenshot", format="png")
                    path = f"{prefix}-{arg}.png"
                    with open(path, "wb") as file:
                        file.write(base64.b64decode(data["data"]))
                    print("saved", path)
                else:
                    sys.exit(f"error: unknown step {step!r}")
            print("page errors:", errors or "none")
    finally:
        process.terminate()


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3:]))
