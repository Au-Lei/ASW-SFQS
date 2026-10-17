"""Run two owned processes and stop both on Ctrl+C; never kill by port number."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.core.settings import Settings


def port_available(port):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1",port))
        except OSError:
            return False
    return True


def health_ready(port):
    # Local traffic must not use a user's external HTTP proxy.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/v1/health",timeout=1) as response:
            return response.status==200 and json.load(response).get("status")=="ok"
    except (OSError,ValueError):
        return False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--startup-timeout",type=int,default=60)
    args=parser.parse_args()
    settings=Settings(app_env="development")
    node=shutil.which("node")
    vite=ROOT/"frontend/node_modules/vite/bin/vite.js"
    if not node or not vite.is_file():
        raise SystemExit("Install Node.js and run scripts/setup.ps1 first.")
    for port in (settings.app_port,settings.frontend_port):
        if not port_available(port):
            raise SystemExit(f"Port {port} is already in use. Stop its owner or change .env; no process was killed.")
    logs=settings.storage_root/"logs"
    logs.mkdir(parents=True,exist_ok=True)
    env={**os.environ,"APP_ENV":"development","APP_HOST":"127.0.0.1",
         "APP_PORT":str(settings.app_port),"FRONTEND_PORT":str(settings.frontend_port),"PYTHONUTF8":"1"}
    children=[]
    handles=[]
    flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
    try:
        commands=[("backend",[sys.executable,"-m","backend"],ROOT),
                  ("frontend",[node,str(vite),"--host","127.0.0.1","--port",str(settings.frontend_port),"--strictPort"],ROOT/"frontend")]
        for name,command,cwd in commands:
            handle=(logs/f"{name}.log").open("ab")
            handles.append(handle)
            children.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=handle,stderr=subprocess.STDOUT,creationflags=flags))
        deadline=time.monotonic()+args.startup_timeout
        while not (health_ready(settings.app_port) and health_ready(settings.frontend_port)):
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A development service exited. Check data/logs/backend.log and frontend.log.")
            if time.monotonic()>deadline:
                raise RuntimeError("Services did not become ready before timeout. Check data/logs/.")
            time.sleep(.3)
        print(f"ASW-SFQS ready: http://127.0.0.1:{settings.frontend_port}",flush=True)
        print("Ctrl+C stops both services. No database has been created or reset.",flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(.5)
        raise RuntimeError("A development service stopped unexpectedly. Check data/logs/.")
    except KeyboardInterrupt:
        print("Stopping owned development services...",flush=True)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        for handle in handles:
            handle.close()


if __name__=="__main__":
    main()
