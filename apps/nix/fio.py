import json
import os
import subprocess
import signal
from typing import Dict, List, Optional

import pandas as pd
from helpers import (
    NOW,
    create_settings,
    flamegraph_env,
    nix_build,
    read_stats,
    write_stats,
    scone_env
)
from storage import Storage, StorageKind


def benchmark_fio(
    system: str,
    attr: str,
    directory: str,
    stats: Dict[str, List],
    extra_env: Dict[str, str] = {},
) -> None:

    env = os.environ.copy()
    # we don't need network for these benchmarks
    del env["SGXLKL_TAP"]
    env.update(dict(SGXLKL_CWD=directory))
    env.update(flamegraph_env(f"fio-{system}-{NOW}"))
    env.update(extra_env)
    enable_sgxio = "1" if system == "sgx-io" else "0"
    env.update(SGXLKL_ENABLE_SGXIO=enable_sgxio)
    threads = "8" if system == "sgx-io" else "2"
    env.update(SGXLKL_ETHREADS=threads)
    env.update(extra_env)
    fio = nix_build(attr)
    stdout: Optional[int] = subprocess.PIPE
    if os.environ.get("SGXLKL_ENABLE_GDB", "0") == "1":
        stdout = None

    cmd = [str(fio), "bin/fio", "--output-format=json", "--eta=always", "fio-rand-RW.job"]
    proc = subprocess.Popen(cmd, stdout=stdout, text=True, env=env)
    data = ""
    in_json = False
    print(f"[Benchmark]: {system}")
    try:
        if proc.stdout is None:
            proc.wait()
        else:
            for line in proc.stdout:
                print(line, end="")
                if line == "{\n":
                    in_json = True
                if in_json:
                    data += line
                if line == "}\n":
                    break
    finally:
        try:
            print("stop fio...")
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.SIGKILL)
            proc.wait()
    if data == "":
        raise RuntimeError(f"Did not get a result when running benchmark for {system}")
    jsondata = json.loads(data)
    for jobnum, job in enumerate(jsondata["jobs"]):
        stats["system"].append(system)
        stats["job"].append(jobnum)
        for op in ["read", "write", "trim"]:
            metrics = job[op]
            for metric_name, metric in metrics.items():
                if isinstance(metric, dict):
                    for name, submetric in metric.items():
                        stats[f"{op}-{metric_name}-{name}"].append(submetric)
                else:
                    stats[f"{op}-{metric_name}"].append(metric)


def benchmark_native(storage: Storage, stats: Dict[str, List]) -> None:
    mount = storage.setup(StorageKind.NATIVE)
    with mount as mnt:
        benchmark_fio("native", "fio-native", mnt, stats, extra_env=mount.extra_env())


def benchmark_scone(storage: Storage, stats: Dict[str, List]) -> None:
    mount = storage.setup(StorageKind.SCONE)
    with mount as mnt:
        extra_env = scone_env(mnt)
        extra_env.update(mount.extra_env())
        benchmark_fio("scone", "fio-scone", mnt, stats, extra_env=extra_env)


def benchmark_sgx_lkl(storage: Storage, stats: Dict[str, List]) -> None:
    mount = storage.setup(StorageKind.LKL)
    with mount as mnt:
        benchmark_fio(
            "sgx-lkl",
            "fio-sgx-lkl",
            mnt,
            stats,
            extra_env=mount.extra_env(),
        )


def benchmark_sgx_io(storage: Storage, stats: Dict[str, List]) -> None:
    mount = storage.setup(StorageKind.SPDK)
    with mount as mnt:
        benchmark_fio("sgx-io", "fio-sgx-io", mnt, stats, extra_env=mount.extra_env())


def main() -> None:
    stats = read_stats("fio.json")

    settings = create_settings()

    storage = Storage(settings)

    system = set(stats["system"])

    benchmarks = {
        "native": benchmark_native,
        "sgx-io": benchmark_sgx_io,
        "scone": benchmark_scone,
        "sgx-lkl": benchmark_sgx_lkl,
    }

    for name, benchmark in benchmarks.items():
        if name in system:
            print(f"skip {name} benchmark")
            continue
        benchmark(storage, stats)
        write_stats("fio.json", stats)

    csv = f"fio-throughput-{NOW}.tsv"
    print(csv)
    throughput_df = pd.DataFrame(stats)
    throughput_df.to_csv(csv, index=False, sep="\t")
    throughput_df.to_csv("fio-throughput-latest.tsv", index=False, sep="\t")


if __name__ == "__main__":
    main()
