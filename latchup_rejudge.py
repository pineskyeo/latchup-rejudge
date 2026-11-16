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


def pick_snap(vp, ev, rule, main_frac=0.7):
    """규칙에 따라 VT 로 쓸 snapback index 를 고른다 (ev 는 비어 있지 않음)."""
    depth = [vp[p] - vp[q] for p, q in ev]
    if rule == "first":
        return 0
    if rule == "last":
        return len(ev) - 1
    if rule == "deepest":
        return max(range(len(ev)), key=lambda k: depth[k])
    if rule == "maxpeak":
        return max(range(len(ev)), key=lambda k: vp[ev[k][0]])
    if rule == "main":
        # 주 snapback: depth 가 최대 depth 의 main_frac 이상인 것 중 peak V 최고
        dmax = max(depth)
        cand = [k for k in range(len(ev)) if depth[k] >= main_frac * dmax]
        return max(cand, key=lambda k: vp[ev[k][0]])
    raise ValueError("unknown rule: %s" % rule)


def new_judge(v, i, find_start, dv_abs, dv_rel, recover, min_hold_pts,
              rule="main", main_frac=0.7):
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
        ("VT_ORDER", None),
    ])
    ev = find_snapbacks(vp, max(0, find_start), dv_abs, dv_rel)
    res["N_SNAP"] = len(ev)
    if not ev:
        return res, ev, None

    p0, q0 = ev[0]
    res["VT1"], res["VT1_I"] = v[p0], i[p0]
    res["VH1"], res["VH1_I"] = v[q0], i[q0]
    res["LAST_VT"], res["LAST_VH"] = v[ev[-1][0]], v[ev[-1][1]]

    if rule != "sustain":
        k = pick_snap(vp, ev, rule, main_frac)
        p, q = ev[k]
        depth = vp[p] - vp[q]
        t = max(range(q, n), key=lambda j: vp[j])
        res["VT"], res["VT_I"], res["VT_NUM"] = v[p], i[p], p + 1
        res["VH"], res["VH_I"], res["VH_NUM"] = v[q], i[q], q + 1
        res["VT_ORDER"] = k + 1
        res["HOLD_PTS"] = n - 1 - q
        res["SNAP_DEPTH"] = depth
        res["RERISE_RATIO"] = ((vp[t] - vp[q]) / depth if depth > 0
                               else float("inf"))
        res["TAIL_VMAX"], res["TAIL_VMAX_NUM"] = v[t], t + 1
        res["STATUS"] = "TRIGGER" if len(ev) == 1 else "TRIGGER_MULTI"
        return res, ev, (p, q)

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


# --------------------------------------------------------------------------
# 집계 분석 리포트 (원시 데이터 없이 공유 가능한 통계만 출력)
# --------------------------------------------------------------------------
RULES = ("LEGACY", "FIRST", "DEEPEST", "LAST", "MAXPEAK", "MAIN")
RULE_DESC = OrderedDict([
    ("LEGACY", "현재 장비: dV 부호가 처음 바뀌는 점"),
    ("FIRST", "첫 번째 snapback"),
    ("DEEPEST", "가장 깊게 떨어지는 snapback"),
    ("LAST", "마지막 snapback"),
    ("MAXPEAK", "peak 전압이 가장 높은 snapback"),
    ("MAIN", "주 snapback: depth >= 최대 depth*MAIN_FRAC 중 peak V 최고"),
])
LOG_STEP = math.log10(1.05)


def polarity(i):
    nz = [x for x in i if x != 0.0]
    return -1.0 if nz and sorted(nz)[len(nz) // 2] < 0 else 1.0


def curve_features(c, ev, leg, main_frac=0.7):
    """한 곡선의 집계용 특징. 전압은 극성 정규화(양수 방향)."""
    pol = polarity(c["i"])
    vp = [x * pol for x in c["v"]]
    ai = [abs(x) for x in c["i"]]
    snaps = []
    for k, (p, q) in enumerate(ev):
        snaps.append({"order": k + 1, "vt": vp[p], "it": ai[p],
                      "vh": vp[q], "depth": vp[p] - vp[q]})
    rule = {}
    main = snaps[pick_snap(vp, ev, "main", main_frac)] if snaps else None
    lv = leg["VT"] * pol if leg["VT"] is not None else None
    lh = leg["VH"] * pol if leg["VH"] is not None else None
    rule["LEGACY"] = (lv, lh)
    if snaps:
        pick = {
            "FIRST": snaps[0],
            "DEEPEST": max(snaps, key=lambda s: s["depth"]),
            "LAST": snaps[-1],
            "MAXPEAK": max(snaps, key=lambda s: s["vt"]),
            "MAIN": main,
        }
        for r, s_ in pick.items():
            rule[r] = (s_["vt"], s_["vh"])
    else:
        for r in RULES[1:]:
            rule[r] = (None, None)
    k = c["key"]
    return {"item": k[9], "n": len(vp), "v_last": vp[-1],
            "i_last": ai[-1], "vmax": max(vp), "snaps": snaps, "rule": rule,
            "main": main, "wf": k[4], "x": _num(k[5]), "y": _num(k[6])}


def _num(t):
    try:
        return float(t)
    except ValueError:
        return None


def _q(xs, p):
    k = min(len(xs) - 1, max(0, int(round(p / 100.0 * (len(xs) - 1)))))
    return xs[k]


def robust(xs):
    """n, median, robust sigma(1.4826*MAD), p10, p90, BC."""
    xs = sorted(x for x in xs if x is not None)
    n = len(xs)
    if n == 0:
        return None
    med = _q(xs, 50)
    mad = sorted(abs(x - med) for x in xs)
    rs = 1.4826 * _q(mad, 50)
    band = max(5.0 * rs, 0.05)
    out = sum(1 for x in xs if abs(x - med) > band)
    return {"n": n, "med": med, "rs": rs, "p10": _q(xs, 10),
            "p90": _q(xs, 90), "bc": bimodality(xs), "out": out}


def bimodality(xs):
    """Sarle's bimodality coefficient. > 0.555 이면 다봉(쌍봉) 의심."""
    n = len(xs)
    if n < 4:
        return None
    m = sum(xs) / float(n)
    m2 = sum((x - m) ** 2 for x in xs) / n
    if m2 <= 0:
        return None
    m3 = sum((x - m) ** 3 for x in xs) / n
    m4 = sum((x - m) ** 4 for x in xs) / n
    g = m3 / m2 ** 1.5
    k = m4 / m2 ** 2 - 3.0
    g1 = g * math.sqrt(n * (n - 1)) / (n - 2)
    g2 = ((n + 1) * k + 6) * (n - 1) / float((n - 2) * (n - 3))
    return (g1 ** 2 + 1) / (g2 + 3.0 * (n - 1) ** 2 / ((n - 2) * (n - 3)))


def ascii_hist(xs, lo, hi, bins=20, width=40):
    xs = [x for x in xs if x is not None]
    if not xs or hi <= lo:
        return ["    (데이터 없음)"]
    cnt = [0] * bins
    for x in xs:
        b = int((x - lo) / (hi - lo) * bins)
        cnt[min(bins - 1, max(0, b))] += 1
    top = max(cnt) or 1
    out = []
    for b in range(bins):
        x0 = lo + (hi - lo) * b / bins
        out.append("    %8.3f | %-*s %d" % (x0, width,
                                             "#" * int(round(cnt[b] * width
                                                             / float(top))),
                                             cnt[b]))
    return out


def fmt_stat(st):
    if not st:
        return "n=0"
    bc = "-" if st["bc"] is None else "%.2f" % st["bc"]
    return ("n=%5d  med=%7.3f  rσ=%6.3f  p10=%7.3f  p90=%7.3f  out=%4d  BC=%s%s"
            % (st["n"], st["med"], st["rs"], st["p10"], st["p90"], st["out"],
               bc,
               " (쌍봉?)" if st["bc"] is not None and st["bc"] > 0.555
               else ""))


def build_report(feats, top_items=10):
    L = []
    add = L.append
    N = len(feats)
    add("=" * 78)
    add("Latch-up 재판정 분석 리포트 (집계 통계만, 칩 ID/원시값 없음)")
    add("전압은 극성 정규화(음방향 주입이면 부호 반전)한 값")
    add("=" * 78)

    # [1] sweep 종료 방식
    nmax = max(f["n"] for f in feats)
    full = [f for f in feats if f["n"] == nmax]
    short = [f for f in feats if f["n"] < nmax]
    add("")
    add("[1] sweep 종료 방식 (최대 점 수 %d)" % nmax)
    for name, grp in (("끝까지 측정", full), ("중간 종료", short)):
        if not grp:
            add("  %-10s %5d 개" % (name, 0))
            continue
        add("  %-10s %5d 개 (%4.1f%%)  마지막 V p10/50/90 = %s   "
            "마지막 |I| p50 = %.3g A"
            % (name, len(grp), 100.0 * len(grp) / N,
               pct_str([f["v_last"] for f in grp]),
               _q(sorted(f["i_last"] for f in grp), 50)))
    lastmax = sum(1 for f in feats if f["v_last"] >= f["vmax"] - 1e-12)
    add("  마지막 점이 곡선 최고 전압인 곡선: %d 개 (%.1f%%)"
        % (lastmax, 100.0 * lastmax / N))

    # [2] snapback 순서별 통계
    add("")
    add("[2] snapback 순서별 통계 (k번째 snapback)")
    add("  %-4s %6s  %-26s %-24s %-24s" % ("k", "개수", "peak V p10/50/90",
                                           "peak |I| p10/50/90",
                                           "depth V p10/50/90"))
    for k in range(1, 6):
        ss = [s for f in feats for s in f["snaps"] if s["order"] == k]
        if not ss:
            break
        add("  %-4d %6d  %-26s %-24s %-24s"
            % (k, len(ss), pct_str([s["vt"] for s in ss]),
               pct_str([s["it"] for s in ss]),
               pct_str([s["depth"] for s in ss])))

    # [3] 전류 decade 경계(range 전환) artifact 검사
    add("")
    add("[3] snapback 위치 vs 전류 decade 경계 (SMU range 전환 artifact 검사)")
    add("  peak 전류의 log10 소수부 분포. 무작위면 10개 구간이 고르게 ~10%씩.")
    add("  특정 구간(특히 0.0x 또는 0.9x)에 몰리면 range 전환 artifact 의심.")
    for label, sel in (("전체", None), ("1번째", 1), ("2번째+", 2)):
        ss = [s for f in feats for s in f["snaps"]
              if s["it"] > 0 and (sel is None or (s["order"] == 1 if sel == 1
                                                  else s["order"] >= 2))]
        if not ss:
            continue
        cnt = [0] * 10
        near = 0
        for s in ss:
            lg = math.log10(s["it"])
            fr = lg - math.floor(lg)
            cnt[min(9, int(fr * 10))] += 1
            if min(fr, 1 - fr) <= LOG_STEP * 1.01:
                near += 1
        add("  %-7s n=%5d  decade 경계 ±1 step 안: %4.1f%% (무작위 기대 %.1f%%)"
            % (label, len(ss), 100.0 * near / len(ss), 200.0 * LOG_STEP))
        add("          소수부 구간 %: " + " ".join(
            "%.1f:%4.1f" % (b / 10.0, 100.0 * cnt[b] / len(ss))
            for b in range(10)))

    # [4] legacy VT: snapback 1개 vs 여러 개 그룹 비교
    add("")
    add("[4] LEGACY VT 를 snapback 개수로 나눠 보기 (Trend 쌍봉 원인 확인)")
    for label, cond in (("snap 0개", lambda n: n == 0),
                        ("snap 1개", lambda n: n == 1),
                        ("snap 2개+", lambda n: n >= 2)):
        xs = [f["rule"]["LEGACY"][0] for f in feats if cond(len(f["snaps"]))]
        add("  %-9s %s" % (label, fmt_stat(robust(xs))))

    # [5] 판정 규칙 후보 비교 (전체)
    add("")
    add("[5] 판정 규칙 후보별 VT / VH 분포 (전체 곡선)")
    add("  rσ = robust sigma(1.4826*MAD). out = |VT-med| > max(5rσ, 0.05V) 개수.")
    add("  BC = bimodality coefficient, 0.555 초과면 쌍봉 의심. 단 소수 outlier 에도"
        " 커지므로 rσ 가 작으면 out 과 히스토그램을 우선할 것.")
    add("  ITEM 이 여러 개면 ITEM 차이 때문에 섞여 보일 수 있으니 [6] 도 함께 볼 것.")
    for r in RULES:
        add("  %-8s %s" % (r, RULE_DESC[r]))
        add("    VT  %s" % fmt_stat(robust([f["rule"][r][0] for f in feats])))
        add("    VH  %s" % fmt_stat(robust([f["rule"][r][1] for f in feats])))

    # [6] ITEM 별 규칙 비교
    items = OrderedDict()
    for f in feats:
        items.setdefault(f["item"], []).append(f)
    order = sorted(items, key=lambda k: -len(items[k]))
    add("")
    add("[6] ITEM 별 VT 비교 (곡선 수 상위 %d 개 ITEM, ITEM 이름은 순번으로 표시)"
        % min(top_items, len(order)))
    for idx, it in enumerate(order[:top_items], 1):
        grp = items[it]
        nsn = {}
        for f in grp:
            k = min(len(f["snaps"]), 3)
            nsn[k] = nsn.get(k, 0) + 1
        add("  ITEM#%d  곡선 %d 개  snap 수 분포: %s" % (
            idx, len(grp), ", ".join("%s=%d" % ("3+" if k == 3 else k, nsn[k])
                                     for k in sorted(nsn))))
        for r in RULES:
            add("    %-8s VT %s" % (r, fmt_stat(robust(
                [f["rule"][r][0] for f in grp]))))

    # [7] 가장 큰 ITEM 의 규칙별 VT 히스토그램
    for hi_idx, it in enumerate(order[:2], 1):
        grp = items[it]
        allv = [f["rule"][r][0] for f in grp for r in RULES
                if f["rule"][r][0] is not None]
        if allv:
            lo, hi = min(allv), max(allv)
            add("")
            add("[7] ITEM#%d 규칙별 VT 히스토그램 (공통 축 %.3f ~ %.3f V)"
                % (hi_idx, lo, hi))
            for r in RULES:
                add("  -- %s" % r)
                L.extend(ascii_hist([f["rule"][r][0] for f in grp], lo, hi))

    # [8] MAIN VT outlier 프로파일
    add("")
    add("[8] MAIN VT outlier 프로파일 (상위 4 ITEM). outlier = |VT-med| > "
        "max(5rσ, 0.05V)")
    add("  outlier 가 몇 번째 snapback 을 골랐는지, 그 전류/depth 가 정상 곡선과"
        " 어떻게 다른지.")
    for idx, it in enumerate(order[:4], 1):
        grp = [f for f in items[it] if f["main"]]
        st = robust([f["main"]["vt"] for f in grp])
        if not st:
            continue
        band = max(5.0 * st["rs"], 0.05)
        outs = [f for f in grp if abs(f["main"]["vt"] - st["med"]) > band]
        ins = [f for f in grp if abs(f["main"]["vt"] - st["med"]) <= band]
        add("  ITEM#%d  outlier %d / %d  (위쪽 %d, 아래쪽 %d)" % (
            idx, len(outs), len(grp),
            sum(1 for f in outs if f["main"]["vt"] > st["med"]),
            sum(1 for f in outs if f["main"]["vt"] < st["med"])))
        if not outs:
            continue
        for label, g in (("정상", ins), ("outlier", outs)):
            od = {}
            for f in g:
                o = min(f["main"]["order"], 3)
                od[o] = od.get(o, 0) + 1
            ns = {}
            for f in g:
                m = min(len(f["snaps"]), 3)
                ns[m] = ns.get(m, 0) + 1
            add("    %-7s VT_ORDER %s | snap 수 %s" % (
                label,
                " ".join("%s=%d" % ("3+" if k_ == 3 else k_, od[k_])
                         for k_ in sorted(od)),
                " ".join("%s=%d" % ("3+" if k_ == 3 else k_, ns[k_])
                         for k_ in sorted(ns))))
            add("            VT p10/50/90 %s | I@VT p10/50/90 %s | depth %s"
                % (pct_str([f["main"]["vt"] for f in g]),
                   pct_str([f["main"]["it"] for f in g]),
                   pct_str([f["main"]["depth"] for f in g])))
            add("            FIRST VT p50 %s | 마지막 V p50 %s | 점 수 p50 %s"
                % (pct_str([f["snaps"][0]["vt"] for f in g], (50,)),
                   pct_str([f["v_last"] for f in g], (50,)),
                   pct_str([f["n"] for f in g], (50,))))

    # [9] trigger 유무가 섞인 ITEM
    mixed = []
    for it in order:
        g = items[it]
        nt = sum(1 for f in g if not f["snaps"])
        if len(g) >= 20 and 0.05 <= nt / float(len(g)) <= 0.95:
            mixed.append((it, nt))
    add("")
    add("[9] snapback 없는 곡선이 5~95%% 섞인 ITEM (%d 개)" % len(mixed))
    nmax = max(f["n"] for f in feats)
    for it, nt in mixed:
        g = items[it]
        idx = order.index(it) + 1
        add("  ITEM#%d  곡선 %d, snapback 없음 %d (%.0f%%)" % (
            idx, len(g), nt, 100.0 * nt / len(g)))
        for label, sub in (("snapback 있음", [f for f in g if f["snaps"]]),
                           ("snapback 없음", [f for f in g if not f["snaps"]])):
            if not sub:
                continue
            short = sum(1 for f in sub if f["n"] < nmax)
            add("    %-12s n=%4d  최고 V p10/50/90 %s | 마지막 V p50 %s | "
                "중간 종료 %d (%.0f%%)" % (
                    label, len(sub), pct_str([f["vmax"] for f in sub]),
                    pct_str([f["v_last"] for f in sub], (50,)), short,
                    100.0 * short / len(sub)))
        # 웨이퍼별
        wfs = OrderedDict()
        for f in g:
            wfs.setdefault(f["wf"], [0, 0])
            wfs[f["wf"]][0] += 1
            if not f["snaps"]:
                wfs[f["wf"]][1] += 1
        add("    웨이퍼별 snapback 없음 비율: " + ", ".join(
            "W%d %d/%d" % (k_ + 1, v_[1], v_[0])
            for k_, v_ in enumerate(wfs.values())))
        # 중심/가장자리 (die 좌표 중앙값 기준 거리 3분위)
        pts = [f for f in g if f["x"] is not None and f["y"] is not None]
        if len(pts) >= 9:
            cx = _q(sorted(f["x"] for f in pts), 50)
            cy = _q(sorted(f["y"] for f in pts), 50)
            d = sorted(((f["x"] - cx) ** 2 + (f["y"] - cy) ** 2) ** 0.5
                       for f in pts)
            t1, t2 = _q(d, 33), _q(d, 67)
            zone = {"중심": [0, 0], "중간": [0, 0], "가장자리": [0, 0]}
            for f in pts:
                r = ((f["x"] - cx) ** 2 + (f["y"] - cy) ** 2) ** 0.5
                z = "중심" if r <= t1 else ("중간" if r <= t2 else "가장자리")
                zone[z][0] += 1
                if not f["snaps"]:
                    zone[z][1] += 1
            add("    die 위치별 snapback 없음 비율: " + ", ".join(
                "%s %d/%d (%.0f%%)" % (z, zone[z][1], zone[z][0],
                                       100.0 * zone[z][1] / max(1, zone[z][0]))
                for z in ("중심", "중간", "가장자리")))
    add("")
    return L


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
    ap.add_argument("--rule", default="main",
                    choices=("main", "maxpeak", "deepest", "first", "last",
                             "sustain"),
                    help="VT 로 쓸 snapback 선택 규칙. main=주 snapback, "
                         "sustain=래치 유지 확인(--recover 사용)")
    ap.add_argument("--main-frac", type=float, default=0.7,
                    help="main 규칙: 최대 depth 대비 이 비율 이상 snapback 만 후보")
    ap.add_argument("--recover", type=float, default=0.5,
                    help="valley 이후 재상승폭/snapback depth 가 이 값 초과면 "
                         "회복(가짜 trigger)으로 판정")
    ap.add_argument("--min-hold-pts", type=int, default=3,
                    help="래치 후 최소 유지 확인 점 수")
    ap.add_argument("--legacy-pad", type=int, default=0,
                    help="legacy 재현 시 배열을 이 길이(max_Pt)까지 0 으로 채움 "
                         "(0=채우지 않음)")
    ap.add_argument("--report", metavar="FILE",
                    help="집계 분석 리포트 파일 (기본: <out>_report.txt)")
    ap.add_argument("--report-items", type=int, default=10,
                    help="리포트에서 ITEM 별로 볼 상위 ITEM 수")
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
            "VT_NUM_SHIFT", "VH_NUM_SHIFT", "VT_ORDER"])
    stats = OrderedDict()
    diag = {"nsnap": {}, "ratio": [], "depth": [], "npts": [],
            "tail_at_end": 0, "n_nolatch": 0}
    pairs = []
    feats = []
    n_vt_chg = n_vh_chg = n_plot = 0

    with open(a.out, "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(cols)
        for c in curves:
            leg = legacy_judge(c["v"], c["i"], a.find_start, a.legacy_pad)
            res, ev, sel = new_judge(c["v"], c["i"], a.find_start, a.dv_abs,
                                     a.dv_rel, a.recover, a.min_hold_pts,
                                     a.rule, a.main_frac)
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
                    diff(res["VH_NUM"], leg["VH_NUM"]), res["VT_ORDER"]]
            pairs.append({"LVT": leg["VT"], "LVH": leg["VH"],
                          "NVT": res["VT"], "NVH": res["VH"]})
            w.writerow([fmt(x) for x in row])

            feats.append(curve_features(c, ev, leg, a.main_frac))
            ns = min(res["N_SNAP"], 4)
            diag["nsnap"][ns] = diag["nsnap"].get(ns, 0) + 1
            diag["npts"].append(len(c["v"]))
            if res["STATUS"] == "NO_LATCH" or (
                    a.rule != "sustain" and res["N_SNAP"]):
                diag["n_nolatch"] += 1
                diag["ratio"].append(res["RERISE_RATIO"])
                diag["depth"].append(res["SNAP_DEPTH"])
                if res["TAIL_VMAX_NUM"] == len(c["v"]):
                    diag["tail_at_end"] += 1

            interesting = (res["STATUS"] not in ("LATCH", "TRIGGER")
                           or vt_chg or vh_chg)
            if can_plot and n_plot < a.plot_max and (a.plot_all or interesting):
                k = c["key"]
                name = "_".join([k[3], "W" + k[4], k[5], k[6], k[9],
                                 "r%d" % c["run"], res["STATUS"]])
                name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name) + ".png"
                plot_curve(c, leg, res, ev, sel, os.path.join(a.plot, name))
                n_plot += 1

    total = len(curves)
    print("곡선 %d 개 → %s   (rule=%s)" % (total, a.out, a.rule))
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
        print("  %s %d 개 중" % ("NO_LATCH" if a.rule == "sustain"
                                 else "snapback 있는 곡선", diag["n_nolatch"]))
        print("    RERISE_RATIO p10/p25/p50/p75/p90 : %s"
              % pct_str(diag["ratio"], (10, 25, 50, 75, 90)))
        print("    SNAP_DEPTH(V) p10/p50/p90        : %s"
              % pct_str(diag["depth"]))
        print("    valley 이후 최고점이 마지막 측정점 : %d 개"
              % diag["tail_at_end"])

    rp = a.report or (os.path.splitext(a.out)[0] + "_report.txt")
    with open(rp, "w", encoding="utf-8") as fr:
        fr.write("\n".join(build_report(feats, a.report_items)) + "\n")
    print("\n분석 리포트 → %s" % rp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
