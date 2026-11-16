#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Latch-up LUP log 재판정 스크립트 (이중 snapback 대응)

입력 log 형식 (force-I sweep latch-up 측정이 남기는 CSV):
    EQPID,PCID,PARTID,LOTID,WFID,XAXIS,YAXIS,DCOP,MOD,ITEM,NUM,If,V1
    EQPA,CARDA,PARTA,LOTA,5,7,2,DCOPA,MODA,ITEMA,1,1.05e-07,0.004952

곡선 하나 = (EQPID..ITEM) 키 + NUM 1..N. 같은 키에서 NUM 이 다시 작아지면
재측정으로 보고 별도 곡선(RUN 2, 3 ...)으로 나눈다.

판정 두 가지를 나란히 출력한다.
  LEGACY_*  : 현재 장비 로직 그대로 (ΔV 부호가 처음 바뀌는 점 = VT, 다음 = VH)
  VT/VH     : 새 로직 (끝까지 유지되는 snapback 만 래치로 인정)

새 로직
  1) snapback 검출 (hysteresis):
       peak 이후 V 가 thr = max(DV_ABS, DV_REL*|Vpeak|) 이상 떨어지면 snapback 1개.
       valley 이후 V 가 DV_ABS 이상 다시 오르면 그 snapback 의 valley 확정.
  2) 래치 확정:
       snapback k 의 depth = Vpeak - Vvalley
       valley 이후 측정 끝까지 최대 재상승폭 rerise = max(V[valley:]) - Vvalley
       rerise <= RECOVER * depth  이면 "유지된 래치".
       → 이 조건을 만족하는 첫 snapback 이 진짜 trigger (VT), 그 이후 최소 V 가 VH.
  3) 상태:
       LATCH       1차 snapback 이 그대로 래치
       LATCH_2ND   앞에 회복된 snapback(pre-trigger)이 있고 뒤에서 래치 (VT1/VH1 = 1차)
       NO_LATCH    snapback 은 있었지만 모두 회복됨
       NO_TRIGGER  snapback 없음
       *_SHORT     래치 후 남은 측정점이 MIN_HOLD_PTS 미만이라 유지 확인 불충분

Python 3.6+ 표준 라이브러리만 사용. --plot 은 matplotlib 이 있을 때만 동작.

사용 예:
    python3 latchup_rejudge.py PARTA_LOTA_LUP.log
    python3 latchup_rejudge.py *.log -o result.csv --plot plots
    python3 latchup_rejudge.py a.log --dv-abs 0.1 --dv-rel 0.05 --recover 0.5
"""

from __future__ import print_function

import argparse
import csv
import glob
import math
import os
import re
import sys
from collections import OrderedDict

KEY_COLS = ["EQPID", "PCID", "PARTID", "LOTID", "WFID", "XAXIS", "YAXIS",
            "DCOP", "MOD", "ITEM"]
HEADER = KEY_COLS + ["NUM", "If", "V1"]


# --------------------------------------------------------------------------
# 입력
# --------------------------------------------------------------------------
def read_curves(paths):
    """log 파일들을 읽어 곡선 목록을 돌려준다.

    반환: list of dict(key=tuple, run=int, num=[], i=[], v=[], src=str)
    """
    curves = OrderedDict()      # (key, run) -> curve
    last_num = {}               # key -> (run, last NUM)
    bad = 0
    for path in paths:
        with open(path, "r", newline="", encoding="utf-8",
                  errors="replace") as f:
            for lineno, row in enumerate(csv.reader(f), 1):
                if not row or not "".join(row).strip():
                    continue
                row = [c.strip() for c in row]
                if row[0] == "EQPID":           # header (중간 반복 포함)
                    continue
                if len(row) < len(HEADER):
                    bad += 1
                    continue
                try:
                    num = int(float(row[10]))
                    cur = float(row[11])
                    vol = float(row[12])
                except ValueError:
                    bad += 1
                    continue
                key = tuple(row[:10])
                run, prev = last_num.get(key, (0, None))
                if prev is None or num <= prev:  # 새 곡선 시작 / 재측정
                    run += 1
                last_num[key] = (run, num)
                c = curves.get((key, run))
                if c is None:
                    c = {"key": key, "run": run, "num": [], "i": [], "v": [],
                         "src": os.path.basename(path)}
                    curves[(key, run)] = c
                c["num"].append(num)
                c["i"].append(cur)
                c["v"].append(vol)
    if bad:
        print("[warn] 해석 못한 행 %d 개 건너뜀" % bad, file=sys.stderr)
    out = []
    for c in curves.values():
        order = sorted(range(len(c["num"])), key=lambda k: c["num"][k])
        for f in ("num", "i", "v"):
            c[f] = [c[f][k] for k in order]
        out.append(c)
    return out


# --------------------------------------------------------------------------
# legacy 판정 (기존 장비 알고리즘의 ΔV 부호 변화 판정 재현)
# --------------------------------------------------------------------------
def legacy_judge(v, i, find_start, pad_to=0):
    """legacy 로직 재현. 배열은 0-based (NUM = index+1).

    pad_to > len(v) 이면 legacy 처럼 측정 안 된 뒤쪽을 0 으로 채운다
    (legacy 는 max_Pt 까지 0 으로 남은 배열을 그대로 스캔함).
    """
    vf = list(v) + [0.0] * max(0, pad_to - len(v))
    cf = list(i) + [0.0] * max(0, pad_to - len(i))
    n = len(vf)
    vdel = [0.0] + [vf[j] - vf[j - 1] for j in range(1, n)]
    res = {"VT": None, "VT_I": None, "VH": None, "VH_I": None,
           "VT_NUM": None, "VH_NUM": None}
    k = 0
    for j in range(max(1, find_start), n):
        if vdel[j] * vdel[j - 1] < 0:
            res["VT"], res["VT_I"], res["VT_NUM"] = vf[j - 1], cf[j - 1], j
            k = j
            break
    for j in range(k + 1, n):
        if j > 2 and vdel[j] * vdel[j - 1] < 0:
            res["VH"], res["VH_I"], res["VH_NUM"] = vf[j - 1], cf[j - 1], j
            break
    return res


# --------------------------------------------------------------------------
# 새 판정
# --------------------------------------------------------------------------
def find_snapbacks(vp, start, dv_abs, dv_rel):
    """hysteresis peak/valley 검출. vp 는 극성 정규화된(양수 방향) 전압.

    반환: [(peak_idx, valley_idx), ...]
    """
    n = len(vp)
    if n - start < 2:
        return []

    def thr(vpeak):
        return max(dv_abs, dv_rel * abs(vpeak))

    events = []
    mode = "up"
    imax = start
    imin = start
    peak = start
    for j in range(start + 1, n):
        if mode == "up":
            if vp[j] >= vp[imax]:
                imax = j
            elif vp[imax] - vp[j] > thr(vp[imax]):
                mode = "down"
                peak = imax
                imin = j
        else:
            if vp[j] <= vp[imin]:
                imin = j
            elif vp[j] - vp[imin] > dv_abs:
                events.append((peak, imin))
                mode = "up"
                imax = j
    if mode == "down":
        events.append((peak, imin))
    return events


def new_judge(v, i, find_start, dv_abs, dv_rel, recover, min_hold_pts):
    n = len(v)
    # 극성: 음방향 주입이면 부호를 뒤집어서 판단하고 결과는 원래 부호로 출력
    nz = [x for x in i if x != 0.0]
    pol = -1.0 if nz and sorted(nz)[len(nz) // 2] < 0 else 1.0
    vp = [x * pol for x in v]

    res = OrderedDict([
        ("STATUS", "NO_TRIGGER"), ("N_SNAP", 0),
        ("VT", None), ("VT_I", None), ("VT_NUM", None),
        ("VH", None), ("VH_I", None), ("VH_NUM", None),
        ("VT1", None), ("VT1_I", None), ("VH1", None), ("VH1_I", None),
        ("HOLD_PTS", None), ("RERISE_RATIO", None),
        ("SNAP_DEPTH", None), ("TAIL_VMAX", None), ("TAIL_VMAX_NUM", None),
        ("LAST_VT", None), ("LAST_VH", None), ("V_LAST", v[-1] if v else None),
    ])
    ev = find_snapbacks(vp, max(0, find_start), dv_abs, dv_rel)
    res["N_SNAP"] = len(ev)
    if not ev:
        return res, ev, None

    p0, q0 = ev[0]
    res["VT1"], res["VT1_I"] = v[p0], i[p0]
    res["VH1"], res["VH1_I"] = v[q0], i[q0]
    res["LAST_VT"], res["LAST_VH"] = v[ev[-1][0]], v[ev[-1][1]]

    chosen = None
    ratios = []
    for idx, (p, q) in enumerate(ev):
        depth = vp[p] - vp[q]
        rerise = max(vp[q:]) - vp[q]
        ratio = rerise / depth if depth > 0 else float("inf")
        ratios.append(ratio)
        if ratio <= recover:
            chosen = idx
            break

    # 진단: 판정에 쓴 snapback(래치면 채택된 것, 아니면 비율이 가장 작은 것)의
    # depth 와 valley 이후 최고점 위치
    di = chosen if chosen is not None else ratios.index(min(ratios))
    dp, dq = ev[di]
    t = max(range(dq, n), key=lambda k: vp[k])
    res["SNAP_DEPTH"] = vp[dp] - vp[dq]
    res["TAIL_VMAX"], res["TAIL_VMAX_NUM"] = v[t], t + 1

    if chosen is None:
        res["STATUS"] = "NO_LATCH"
        res["RERISE_RATIO"] = min(ratios)
        return res, ev, None

    p, q = ev[chosen]
    # VH = trigger 이후 최저 전압 (holding 전압)
    h = min(range(p, n), key=lambda k: vp[k])
    res["VT"], res["VT_I"], res["VT_NUM"] = v[p], i[p], p + 1
    res["VH"], res["VH_I"], res["VH_NUM"] = v[h], i[h], h + 1
    res["HOLD_PTS"] = n - 1 - q
    res["RERISE_RATIO"] = ratios[chosen]
    status = "LATCH" if chosen == 0 else "LATCH_2ND"
    if res["HOLD_PTS"] < min_hold_pts:
        status += "_SHORT"
    res["STATUS"] = status
    return res, ev, (p, h)


# --------------------------------------------------------------------------
# 출력
# --------------------------------------------------------------------------
def fmt(x):
    if x is None:
        return ""
    if isinstance(x, float):
        if math.isinf(x):
            return "inf"
        return "%.6g" % x
    return str(x)


def diff(new, old):
    if new is None or old is None:
        return None
    return new - old


def same(a, b, tol=1e-9):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def pct_str(xs, ps=(10, 50, 90)):
    xs = sorted(x for x in xs if x is not None and not math.isinf(x))
    if not xs:
        return "-"
    out = []
    for p in ps:
        k = min(len(xs) - 1, max(0, int(round(p / 100.0 * (len(xs) - 1)))))
        out.append("%.3g" % xs[k])
    return " / ".join(out)


def _pt(leg_or_res, key_v, key_i, key_num):
    """(V, I, NUM) 또는 None."""
    if leg_or_res.get(key_v) is None:
        return None
    return (leg_or_res[key_v], leg_or_res.get(key_i), leg_or_res.get(key_num))


def _pt_str(pt):
    if pt is None:
        return "-"
    v, i, num = pt
    return "%.3f V @ %.3g A (NUM %s)" % (v, abs(i) if i else 0.0, num)


def plot_curve(c, leg, res, ev, sel, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = [abs(a) if a != 0 else float("nan") for a in c["i"]]
    v = c["v"]
    n = len(v)

    def xy(num):
        if num is None or not (1 <= num <= n):
            return None
        return x[num - 1], v[num - 1]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.plot(x, v, "-", color="0.6", lw=1)
    ax.plot(x, v, ".", color="0.4", ms=3)
    for k, (p, q) in enumerate(ev):
        ax.plot(x[p], v[p], "^", color="tab:orange", ms=7, alpha=0.8,
                label="snapback peak" if k == 0 else None)
        ax.plot(x[q], v[q], "v", color="tab:orange", ms=7, alpha=0.8,
                label="snapback valley" if k == 0 else None)

    lvt, lvh = xy(leg["VT_NUM"]), xy(leg["VH_NUM"])
    nvt, nvh = xy(res["VT_NUM"]), xy(res["VH_NUM"])
    if lvt:
        ax.plot(*lvt, marker="s", mfc="none", mec="tab:blue", ms=13, mew=2,
                ls="none", label="LEGACY VT")
    if lvh:
        ax.plot(*lvh, marker="D", mfc="none", mec="tab:blue", ms=12, mew=2,
                ls="none", label="LEGACY VH")
    if nvt:
        ax.plot(*nvt, marker="o", color="tab:red", ms=10, ls="none",
                label="NEW VT")
    if nvh:
        ax.plot(*nvh, marker="o", color="tab:green", ms=10, ls="none",
                label="NEW VH")
    # legacy -> new 이동 화살표
    for a0, a1, col in ((lvt, nvt, "tab:red"), (lvh, nvh, "tab:green")):
        if a0 and a1 and a0 != a1:
            ax.annotate("", xy=a1, xytext=a0,
                        arrowprops=dict(arrowstyle="->", color=col, lw=1.6,
                                        connectionstyle="arc3,rad=0.2"))
    # 래치가 아니면 valley 이후 최고점(회복 판정 근거)을 표시
    if res["STATUS"] == "NO_LATCH":
        t = xy(res["TAIL_VMAX_NUM"])
        if t:
            ax.plot(*t, marker="x", color="tab:purple", ms=11, mew=2,
                    ls="none", label="max after valley")

    lines = [
        "LEGACY VT  %s" % _pt_str(_pt(leg, "VT", "VT_I", "VT_NUM")),
        "LEGACY VH  %s" % _pt_str(_pt(leg, "VH", "VH_I", "VH_NUM")),
    ]
    if sel:
        lines += [
            "NEW    VT  %s" % _pt_str(_pt(res, "VT", "VT_I", "VT_NUM")),
            "NEW    VH  %s" % _pt_str(_pt(res, "VH", "VH_I", "VH_NUM")),
        ]
    else:
        lines.append("NEW        %s  (snap %d, rerise ratio %s)"
                     % (res["STATUS"], res["N_SNAP"],
                        fmt(res["RERISE_RATIO"]) or "-"))
    ax.text(0.01, 0.99, "\n".join(lines), transform=ax.transAxes,
            va="top", ha="left", fontsize=8, family="monospace",
            bbox=dict(boxstyle="round", fc="white", ec="0.7", alpha=0.9))

    ax.set_xscale("log")
    ax.set_xlabel("|If| (A)")
    ax.set_ylabel("V1 (V)")
    k = c["key"]
    ax.set_title("%s  W%s (%s,%s)  %s  run%d  [%s]"
                 % (k[3], k[4], k[5], k[6], k[9], c["run"], res["STATUS"]),
                 fontsize=9)
    ax.grid(True, which="both", alpha=0.3)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_summary(pairs, path):
    """전체 곡선의 legacy vs new VT/VH 분포와 이동."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axs = plt.subplots(1, 3, figsize=(15, 4.6))
    for ax, name in zip(axs[:2], ("VT", "VH")):
        lg = [p["L" + name] for p in pairs if p["L" + name] is not None]
        nw = [p["N" + name] for p in pairs if p["N" + name] is not None]
        allv = lg + nw
        if not allv:
            ax.set_title("%s: no data" % name)
            continue
        lo, hi = min(allv), max(allv)
        if hi <= lo:
            hi = lo + 1.0
        bins = [lo + (hi - lo) * k / 60.0 for k in range(61)]
        ax.hist(lg, bins=bins, histtype="step", lw=1.8, color="tab:blue",
                label="LEGACY %s (n=%d)" % (name, len(lg)))
        ax.hist(nw, bins=bins, histtype="step", lw=1.8, color="tab:red",
                label="NEW %s (n=%d)" % (name, len(nw)))
        ax.set_xlabel("%s (V)" % name)
        ax.set_ylabel("count")
        ax.set_title("%s distribution: legacy vs new" % name)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    ax = axs[2]
    both = [(p["LVT"], p["NVT"]) for p in pairs
            if p["LVT"] is not None and p["NVT"] is not None]
    if both:
        lx = [a for a, _ in both]
        ny = [b for _, b in both]
        ax.plot(lx, ny, ".", ms=4, alpha=0.5, color="tab:purple")
        lo, hi = min(lx + ny), max(lx + ny)
        ax.plot([lo, hi], [lo, hi], "--", color="0.5", lw=1, label="no change")
        ax.legend(fontsize=8)
    n_lost = sum(1 for p in pairs if p["LVT"] is not None and p["NVT"] is None)
    ax.set_xlabel("LEGACY VT (V)")
    ax.set_ylabel("NEW VT (V)")
    ax.set_title("VT moved (n=%d), legacy VT -> no latch: %d"
                 % (len(both), n_lost))
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="LUP log 재판정 (이중 snapback 대응)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("logs", nargs="+", help="LUP log 파일 (glob 가능)")
    ap.add_argument("-o", "--out", default="latchup_rejudge_result.csv",
                    help="결과 CSV")
    ap.add_argument("--find-start", type=int, default=6,
                    help="판정 시작 index (0-based, legacy findStartPoint)")
    ap.add_argument("--dv-abs", type=float, default=0.05,
                    help="snapback 최소 drop / valley 재상승 인정폭 (V)")
    ap.add_argument("--dv-rel", type=float, default=0.03,
                    help="snapback 최소 drop 비율 (|Vpeak| 대비)")
    ap.add_argument("--recover", type=float, default=0.5,
                    help="valley 이후 재상승폭/snapback depth 가 이 값 초과면 "
                         "회복(가짜 trigger)으로 판정")
    ap.add_argument("--min-hold-pts", type=int, default=3,
                    help="래치 후 최소 유지 확인 점 수")
    ap.add_argument("--legacy-pad", type=int, default=0,
                    help="legacy 재현 시 배열을 이 길이(max_Pt)까지 0 으로 채움 "
                         "(0=채우지 않음)")
    ap.add_argument("--plot", metavar="DIR",
                    help="곡선 PNG 저장 폴더 (matplotlib 필요)")
    ap.add_argument("--plot-all", action="store_true",
                    help="모든 곡선 plot (기본: LATCH 가 아니거나 legacy 와 "
                         "다른 곡선만)")
    ap.add_argument("--plot-max", type=int, default=300,
                    help="plot 최대 개수")
    a = ap.parse_args(argv)

    paths = []
    for p in a.logs:
        hits = glob.glob(p)
        paths.extend(sorted(hits) if hits else [p])
    curves = read_curves(paths)
    if not curves:
        print("곡선이 없습니다.", file=sys.stderr)
        return 1

    can_plot = False
    if a.plot:
        try:
            import matplotlib  # noqa: F401
            can_plot = True
            if not os.path.isdir(a.plot):
                os.makedirs(a.plot)
        except ImportError:
            print("[warn] matplotlib 이 없어 plot 을 건너뜁니다.",
                  file=sys.stderr)

    cols = (KEY_COLS + ["RUN", "N_POINTS", "SRC",
            "LEGACY_VT", "LEGACY_VT_I", "LEGACY_VT_NUM",
            "LEGACY_VH", "LEGACY_VH_I", "LEGACY_VH_NUM",
            "STATUS", "N_SNAP",
            "VT", "VT_I", "VT_NUM", "VH", "VH_I", "VH_NUM",
            "VT1", "VT1_I", "VH1", "VH1_I",
            "HOLD_PTS", "RERISE_RATIO", "SNAP_DEPTH", "TAIL_VMAX",
            "TAIL_VMAX_NUM", "LAST_VT", "LAST_VH", "V_LAST",
            "VT_CHANGED", "VH_CHANGED", "VT_SHIFT", "VH_SHIFT",
            "VT_NUM_SHIFT", "VH_NUM_SHIFT"])
    stats = OrderedDict()
    diag = {"nsnap": {}, "ratio": [], "depth": [], "npts": [],
            "tail_at_end": 0, "n_nolatch": 0}
    pairs = []
    n_vt_chg = n_vh_chg = n_plot = 0

    with open(a.out, "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(cols)
        for c in curves:
            leg = legacy_judge(c["v"], c["i"], a.find_start, a.legacy_pad)
            res, ev, sel = new_judge(c["v"], c["i"], a.find_start, a.dv_abs,
                                     a.dv_rel, a.recover, a.min_hold_pts)
            vt_chg = not same(leg["VT"], res["VT"])
            vh_chg = not same(leg["VH"], res["VH"])
            n_vt_chg += vt_chg
            n_vh_chg += vh_chg
            stats[res["STATUS"]] = stats.get(res["STATUS"], 0) + 1

            row = list(c["key"]) + [c["run"], len(c["v"]), c["src"],
                   leg["VT"], leg["VT_I"], leg["VT_NUM"],
                   leg["VH"], leg["VH_I"], leg["VH_NUM"]]
            row += [res[k] for k in ("STATUS", "N_SNAP", "VT", "VT_I",
                    "VT_NUM", "VH", "VH_I", "VH_NUM", "VT1", "VT1_I", "VH1",
                    "VH1_I", "HOLD_PTS", "RERISE_RATIO", "SNAP_DEPTH",
                    "TAIL_VMAX", "TAIL_VMAX_NUM", "LAST_VT", "LAST_VH",
                    "V_LAST")]
            row += ["Y" if vt_chg else "", "Y" if vh_chg else ""]
            row += [diff(res["VT"], leg["VT"]), diff(res["VH"], leg["VH"]),
                    diff(res["VT_NUM"], leg["VT_NUM"]),
                    diff(res["VH_NUM"], leg["VH_NUM"])]
            pairs.append({"LVT": leg["VT"], "LVH": leg["VH"],
                          "NVT": res["VT"], "NVH": res["VH"]})
            w.writerow([fmt(x) for x in row])

            ns = min(res["N_SNAP"], 4)
            diag["nsnap"][ns] = diag["nsnap"].get(ns, 0) + 1
            diag["npts"].append(len(c["v"]))
            if res["STATUS"] == "NO_LATCH":
                diag["n_nolatch"] += 1
                diag["ratio"].append(res["RERISE_RATIO"])
                diag["depth"].append(res["SNAP_DEPTH"])
                if res["TAIL_VMAX_NUM"] == len(c["v"]):
                    diag["tail_at_end"] += 1

            interesting = (res["STATUS"] != "LATCH") or vt_chg or vh_chg
            if can_plot and n_plot < a.plot_max and (a.plot_all or interesting):
                k = c["key"]
                name = "_".join([k[3], "W" + k[4], k[5], k[6], k[9],
                                 "r%d" % c["run"], res["STATUS"]])
                name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name) + ".png"
                plot_curve(c, leg, res, ev, sel, os.path.join(a.plot, name))
                n_plot += 1

    total = len(curves)
    print("곡선 %d 개 → %s" % (total, a.out))
    for k, n in stats.items():
        print("  %-18s %5d" % (k, n))
    print("  legacy 대비 VT 변경 %d, VH 변경 %d" % (n_vt_chg, n_vh_chg))
    if can_plot:
        sp = os.path.join(a.plot, "_summary_legacy_vs_new.png")
        plot_summary(pairs, sp)
        print("  plot %d 개 + 요약 %s → %s" % (n_plot, os.path.basename(sp),
                                            a.plot))

    print("\n[진단]")
    print("  측정점 수 p10/p50/p90 : %s" % pct_str(diag["npts"]))
    print("  snapback 수 분포      : %s" % ", ".join(
        "%s개=%d" % ("4+" if k == 4 else k, diag["nsnap"][k])
        for k in sorted(diag["nsnap"])))
    if diag["n_nolatch"]:
        print("  NO_LATCH %d 개 중" % diag["n_nolatch"])
        print("    RERISE_RATIO p10/p25/p50/p75/p90 : %s"
              % pct_str(diag["ratio"], (10, 25, 50, 75, 90)))
        print("    SNAP_DEPTH(V) p10/p50/p90        : %s"
              % pct_str(diag["depth"]))
        print("    valley 이후 최고점이 마지막 측정점 : %d 개"
              % diag["tail_at_end"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
