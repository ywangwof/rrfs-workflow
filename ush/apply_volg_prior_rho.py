#!/usr/bin/env python3
"""Restore TEMPO graupel volume and copy unanalyzed scalars after LETKF.

Pass-2 analysis writes the whole scalars array from a shared MPAS pool, so
volg, ni, nifa and nwfa in every member file are the last member's background.
qg and ng are real per-member updates and are left unchanged.

volg (L/kg in TEMPO) is rebuilt from this member's prior density:

    rho_b = clip(1000 * qg_b / volg_b, 50, 800)   when the prior has graupel
    rho_b = 500                                    otherwise
    volg_a = 1000 * qg_a / rho_b                   when the analysis has graupel
    volg_a = 0                                     otherwise

ni, nifa and nwfa are copied from this member's own prior, not rescaled.

The script checks every member before writing. Pre-fix volg/ni/nifa/nwfa must
match the last member's prior bitwise. If they do not, it exits without
touching any file.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
from netCDF4 import Dataset

QG_MIN = 1e-8
VOL_MIN = 1e-11
RHO_MIN = 50.0
RHO_MAX = 800.0
RHO_DEFAULT = 500.0
COPY_VARS = ("ni", "nifa", "nwfa")
STAMP_VARS = ("volg",) + COPY_VARS


def member_path(root: str, member: int, name: str) -> str:
    return f"{root}/mem{member:03d}/{name}"


def read_var(path: str, name: str) -> np.ndarray:
    with Dataset(path) as ds:
        if name not in ds.variables:
            raise SystemExit(f"{path} has no variable {name}")
        return np.asarray(ds.variables[name][0], dtype=np.float32)


def rebuild_volg(qg_a: np.ndarray, qg_b: np.ndarray, volg_b: np.ndarray) -> tuple[np.ndarray, int, int]:
    usable = (qg_b > QG_MIN) & (volg_b > VOL_MIN)
    rho = np.full(qg_b.shape, RHO_DEFAULT, dtype=np.float64)
    rho[usable] = np.clip(
        1000.0 * qg_b[usable].astype(np.float64) / volg_b[usable].astype(np.float64),
        RHO_MIN,
        RHO_MAX,
    )
    volg_a = np.zeros(qg_a.shape, dtype=np.float32)
    pos = qg_a > QG_MIN
    volg_a[pos] = (1000.0 * qg_a[pos].astype(np.float64) / rho[pos]).astype(np.float32)
    return volg_a, int(usable.sum()), int(pos.sum())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ana-dir", required=True)
    parser.add_argument("--prior-root", required=True)
    parser.add_argument("--prior-name", required=True)
    parser.add_argument("--nmem", type=int, required=True)
    args = parser.parse_args()
    if args.nmem < 1:
        raise SystemExit("nmem must be positive")

    ana_name = "mpasout.nc"
    last = args.nmem
    prior_last = {
        name: read_var(member_path(args.prior_root, last, args.prior_name), name)
        for name in STAMP_VARS
    }

    pending = []
    for member in range(1, args.nmem + 1):
        ana = member_path(args.ana_dir, member, ana_name)
        prior = member_path(args.prior_root, member, args.prior_name)
        ana_stamp = {name: read_var(ana, name) for name in STAMP_VARS}
        for name in STAMP_VARS:
            if not np.array_equal(ana_stamp[name], prior_last[name]):
                raise SystemExit(
                    f"pre-check failed: mem{member:03d} analysis {name} "
                    f"is not mem{last:03d} prior; no file written"
                )
        qg_a = read_var(ana, "qg")
        qg_b = read_var(prior, "qg")
        volg_b = read_var(prior, "volg")
        volg_a, n_usable, n_pos = rebuild_volg(qg_a, qg_b, volg_b)
        copied = {name: read_var(prior, name) for name in COPY_VARS}
        pending.append((member, ana, volg_a, copied, n_usable, n_pos))

    for member, ana, volg_a, copied, n_usable, n_pos in pending:
        with Dataset(ana, "r+") as ds:
            ds.variables["volg"][0] = volg_a
            ds.variables["volg"].setncattr(
                "volcons", "vol=1000*qg_ana/rho_prior_tempo"
            )
            for name, values in copied.items():
                ds.variables[name][0] = values
                ds.variables[name].setncattr("prior_copy", "member_background")
        rho_note = ""
        if n_pos:
            pos = volg_a > 0
            # density on points that received a rebuilt volume
            qg_a = read_var(ana, "qg")
            rho = 1000.0 * qg_a[pos].astype(np.float64) / volg_a[pos].astype(np.float64)
            rho_note = f" rho_med={float(np.median(rho)):.1f} rho_max={float(rho.max()):.1f}"
        print(
            f"mem{member:03d} usable_prior={n_usable} qg_pos={n_pos}{rho_note}",
            flush=True,
        )
    print(f"wrote {args.nmem} members", flush=True)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(1)
