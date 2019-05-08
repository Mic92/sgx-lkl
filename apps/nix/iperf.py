#!/usr/bin/env python3

import getpass
import json
import os
import subprocess
import time
from collections import defaultdict
from datetime import datetime
from enum import Enum
from typing import Any, DefaultDict, Dict, List

import pandas as pd
from helpers import (
    NOW,
    ROOT,
    RemoteCommand,
    Settings,
    create_settings,
    flamegraph_env,
    nix_build,
    run,
    spawn,
)
from network import Network, NetworkKind


def _postprocess_iperf(
    raw_data: Dict[str, Any], direction: str, system: str, stats: Dict[str, Any]
) -> None:
    cpu = raw_data["end"]["cpu_utilization_percent"]

    for intervall in raw_data["intervals"]:
        for key in cpu.keys():
            stats[f"cpu_{key}"].append(cpu[key])

        moved_bytes = 0
        seconds = 0
        for stream in intervall["streams"]:
            moved_bytes += stream["bytes"]
            seconds += stream["seconds"]

        stats["system"].append(system)
        stats["bytes"].append(moved_bytes)
        stats["seconds"].append(seconds)
        stats["direction"].append(direction)


def _benchmark_iperf(
    settings: Settings,
    local_iperf: str,
    remote_iperf: RemoteCommand,
    direction: str,
    system: str,
    stats: Dict[str, List[int]],
    extra_env: Dict[str, str] = {},
):
    env = extra_env.copy()
    env.update(flamegraph_env(f"iperf-{direction}-{system}-{NOW}"))
    with spawn(local_iperf, extra_env=env):
        while True:
            try:
                proc = remote_iperf.run(
                    "bin/iperf", ["-c", settings.local_dpdk_ip6, "-n", "1024"]
                )
                break
            except subprocess.CalledProcessError:
                print(".")
                pass

        iperf_args = ["-P", "4", "-c", settings.local_dpdk_ip6, "--json"]
        if direction == "send":
            iperf_args += ["-R"]

        proc = remote_iperf.run("bin/iperf", iperf_args, extra_env=extra_env)
        _postprocess_iperf(json.loads(proc.stdout), direction, system, stats)


def benchmark_iperf(
    settings: Settings,
    attr: str,
    system: str,
    stats: Dict[str, List[int]],
    extra_env: Dict[str, str] = {},
) -> None:
    local_iperf = nix_build(attr)
    remote_iperf = settings.remote_command(nix_build("iperf-remote"))

    _benchmark_iperf(
        settings, local_iperf, remote_iperf, "send", system, stats, extra_env
    )
    _benchmark_iperf(
        settings, local_iperf, remote_iperf, "receive", system, stats, extra_env
    )


def benchmark_native(settings: Settings, stats: Dict[str, List[int]]) -> None:
    Network(NetworkKind.NATIVE, settings).setup()

    benchmark_iperf(settings, "iperf-native", "native", stats)


def benchmark_sgx_lkl(settings: Settings, stats: Dict[str, List[int]]) -> None:
    Network(NetworkKind.TAP, settings).setup()
    extra_env = dict(
        SGXLKL_IP6=settings.local_dpdk_ip6,
        SGXLKL_TAP_OFFLOAD="1",
        SGXLKL_TAP_MTU="9000"
    )
    benchmark_iperf(settings, "iperf", "sgx-lkl", stats, extra_env=extra_env)


def benchmark_sgx_io(settings: Settings, stats: Dict[str, List[int]]):
    Network(NetworkKind.DPDK, settings).setup()
    extra_env = dict(SGXLKL_DPDK_MTU="9000")

    benchmark_iperf(settings, "iperf", "sgx-io", stats, extra_env=extra_env)


def main() -> None:
    stats: DefaultDict[str, List] = defaultdict(list)

    settings = create_settings()

    benchmark_sgx_io(settings, stats)
    benchmark_native(settings, stats)
    benchmark_sgx_lkl(settings, stats)

    csv = f"iperf-{NOW}.tsv"
    print(csv)
    pd.DataFrame(stats).to_csv(csv, index=False, sep="\t")


if __name__ == "__main__":
    main()
