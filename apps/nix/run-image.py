#!/usr/bin/env python

import os
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import List, Optional, Dict
from contextlib import contextmanager

NOW = datetime.now().strftime("%Y%m%d-%H%M%S")


def get_debugger(perf_data: str) -> List[str]:
    if os.environ.get("SGXLKL_ENABLE_GDB", None) is not None:
        return ["sgx-lkl-gdb", "--args"]
    elif os.environ.get("SGXLKL_ENABLE_STRACE", None) is not None:
        return ["strace"]
    elif os.environ.get("SGXLKL_ENABLE_FLAMEGRAPH", None) is not None:
        return ["perf", "record", "-o", perf_data, "-a", "-g", "-F99", "--"]
    return []


def generate_flamegraph(perf_data: str, flamegraph: str) -> None:
    if os.environ.get("SGXLKL_ENABLE_FLAMEGRAPH", None) is None:
        return
    perf = subprocess.Popen(["perf", "script", "-i", perf_data], stdout=subprocess.PIPE)
    stackcollapse = subprocess.Popen(["stackcollapse-perf.pl"], stdin=perf.stdout, stdout=subprocess.PIPE)
    with open(flamegraph, "w") as f:
        flamegraph_proc = subprocess.Popen(
            ["flamegraph.pl"], stdin=stackcollapse.stdout, stdout=f
        )
    flamegraph_proc.communicate()


@contextmanager
def debug_mount_env(image: str):
    env = os.environ.copy()
    if os.environ.get("SGXLKL_ENABLE_FLAMEGRAPH", None) is None or image == "NONE":
        yield env
        return

    with tempfile.TemporaryDirectory(prefix="dbgmount-") as tmpdirname:
        subprocess.run(["sudo", "mount", image, tmpdirname])
        env["SGXLKL_DEBUGMOUNT"] = tmpdirname

        try:
            yield env
        finally:
            subprocess.run(["sudo", "umount", tmpdirname])


def run(image: str, debugger: List[str], cmd: List[str], env: Dict[str, str], tmpdirname: str):
    native_mode = image == "NONE"

    if native_mode:
        proc = subprocess.Popen(debugger + cmd, env=env)
    else:
        tmp_fsimage = os.path.join(tmpdirname, "fs.img")
        shutil.copyfile(image, tmp_fsimage)

        proc = subprocess.Popen(debugger + ["sgx-lkl-run", tmp_fsimage] + cmd, env=env)

        def stop_proc(signum, frame) -> None:
            proc.terminate()
        signal.signal(signal.SIGINT, stop_proc)
        proc.wait()

 
def main(args: List[str]) -> None:
    if len(args) < 3:
        print(f"USAGE: {sys.argv[0]} image", file=sys.stderr)
        sys.exit(1)
    image = args[1]
    cmd = args[2:]

    with tempfile.TemporaryDirectory(prefix="run-image-") as tmpdirname:
        perf_data = os.path.join(tmpdirname, "perf.data")
        debugger = get_debugger(perf_data)
        try:
            with debug_mount_env(image) as env:
                run(image, debugger, cmd, env, tmpdirname)
        finally:
            if os.environ.get("SGXLKL_ENABLE_FLAMEGRAPH", None) is None:
                return

            flamegraph = os.environ.get("FLAMEGRAPH_FILENAME", None)
            if flamegraph is None:
                flamegraph = os.path.join(tmpdirname, f"flamegraph-{NOW}.svg")
            generate_flamegraph(perf_data, flamegraph)
            perf = os.environ.get("PERF_FILENAME", None)
            if perf is not None:
                shutil.move(perf_data, perf)


if __name__ == "__main__":
    main(sys.argv)