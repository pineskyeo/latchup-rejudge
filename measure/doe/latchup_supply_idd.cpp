/*
 * latchup_supply_idd -- powered-supply latch-up I-test (P9000)
 *
 * AlgorithmDefinition: latchup__supply_idd v1 (topology: supply_io)
 *   - inputs : token, IO_PIN, SUPPLY1..4_PIN ("" = unused), VSUP1..4,
 *              ISTART, RATIO, I_END, V_COMP, SUP_COMP, IDD_ABS, IDD_REL,
 *              PULSE_S, SETTLE_S, HOLD_STEP, HOLD_ABS, MEAS_RANGE,
 *              INTEGRATION, DEBUG
 *   - outputs: STATUS, STEP_COUNT, I_NOM, LU_IT, LU_VT, LU_SUP, I_LATCH,
 *              LU_VH, LU_IH, I_RECOVER
 *
 * latchup_supply_io (legacy port) grounds the supplies and infers latch from
 * the shape of the IO V-I curve, so a snapback that the device cannot hold
 * looks the same as a real latch. This algorithm measures latch-up by its
 * definition instead: the supplies are powered, a trigger current is
 * injected into the IO pin and then REMOVED, and the supply current is
 * measured afterwards. A snapback that does not survive trigger removal
 * leaves the supply current at nominal and is not reported as a latch.
 *
 * Sequence
 *  1. Force each used supply to VSUPn (compliance SUP_COMP) with IO at 0 A,
 *     measure the nominal supply current I_nom[n]. Latch threshold per
 *     supply: thr[n] = max(|I_nom| + IDD_ABS, IDD_REL * |I_nom|)
 *     (JESD78-style criterion; confirm against the revision the spec cites).
 *  2. Trigger step k: I_trig = ISTART * RATIO^k on IO for PULSE_S, measure
 *     the IO voltage, return IO to 0 A, wait SETTLE_S, measure every supply.
 *     Latched when any |I_post[n]| > thr[n]; LU_SUP is the supply with the
 *     largest |I_post| / thr. Stop on latch, |I_trig| >= I_END or
 *     |V_io| >= V_COMP.
 *  3. On latch, step one powered supply (the one with the largest
 *     |I_post| / thr) from VSUP toward 0 V by HOLD_STEP while
 *     |I| - |I_nom| > HOLD_ABS. The last point still latched is
 *     LU_VH / LU_IH, the supply-side hold point of the parasitic SCR.
 *  4. Power-cycle every supply (0 V, then VSUP) and re-measure. A supply
 *     still above thr means the device did not recover.
 *
 * STATUS
 *    0  no latch up to I_END / V_COMP
 *    1  latch, recovered after power cycle
 *    2  latch, NOT recovered after power cycle (damage or stuck latch)
 *   -2  thr >= SUP_COMP on some supply: a latch could not be detected
 *   -3  no supply powered (every used VSUP = 0): a latch cannot be held
 *   -4  bad config: ISTART = 0, RATIO <= 1 or IDD_ABS <= 0
 *
 * Build: g++ -std=gnu++98 -fsyntax-only -isystem <site_tis_include> latchup_supply_idd.cpp
 */

/****** <BEGIN> INCLUDE FILES *********** DON'T EDIT FROM <BEGIN> TO <END> ***/
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <vector>
#include <tis.h>
#ifdef TDE_ENV
#include <SPECS_.h>
#include <DISPATCHER.h>
#include <PROBER.h>
#endif
/****** <END>   INCLUDE FILES *********** DON'T EDIT FROM <BEGIN> TO <END> ***/

#include "../shared/alg_common.h"
#include "../shared/alg_debug.h"

#define ALG_LUI_MAX_STEPS 400
#define ALG_LUI_MAX_HOLD  400
#define ALG_LUI_SUPPLIES  4

using namespace std;

struct lui_in {
    STRINGP token;
    STRINGP io;
    STRINGP sup[ALG_LUI_SUPPLIES];
    REAL vsup[ALG_LUI_SUPPLIES];
    REAL istart, ratio, i_end, v_comp, sup_comp, idd_abs, idd_rel;
    REAL pulse_s, settle_s, hold_step, hold_abs, meas_range;
    STRINGP integration;
    INTEGER debug;
};

struct lui_out {
    REAL status, step_count, i_nom, it, vt, sup, i_latch, vh, ih, i_recover;
};

static void lui_run(const lui_in& in, lui_out& o);

void latchup_supply_idd(
    const vector<STRINGP>& token,
    const vector<STRINGP>& IO_PIN,
    const vector<STRINGP>& SUPPLY1_PIN,
    const vector<STRINGP>& SUPPLY2_PIN,
    const vector<STRINGP>& SUPPLY3_PIN,
    const vector<STRINGP>& SUPPLY4_PIN,
    const vector<REAL>& VSUP1,
    const vector<REAL>& VSUP2,
    const vector<REAL>& VSUP3,
    const vector<REAL>& VSUP4,
    const vector<REAL>& ISTART,
    const vector<REAL>& RATIO,
    const vector<REAL>& I_END,
    const vector<REAL>& V_COMP,
    const vector<REAL>& SUP_COMP,
    const vector<REAL>& IDD_ABS,
    const vector<REAL>& IDD_REL,
    const vector<REAL>& PULSE_S,
    const vector<REAL>& SETTLE_S,
    const vector<REAL>& HOLD_STEP,
    const vector<REAL>& HOLD_ABS,
    const vector<REAL>& MEAS_RANGE,
    const vector<STRINGP>& INTEGRATION,
    const vector<INTEGER>& DEBUG,
    vector<REAL>& STATUS,
    vector<REAL>& STEP_COUNT,
    vector<REAL>& I_NOM,
    vector<REAL>& LU_IT,
    vector<REAL>& LU_VT,
    vector<REAL>& LU_SUP,
    vector<REAL>& I_LATCH,
    vector<REAL>& LU_VH,
    vector<REAL>& LU_IH,
    vector<REAL>& I_RECOVER,
    const INTEGER _size) {

    STATUS.assign(_size, 0.0);
    STEP_COUNT.assign(_size, 0.0);
    I_NOM.assign(_size, 0.0);
    LU_IT.assign(_size, 0.0);
    LU_VT.assign(_size, 0.0);
    LU_SUP.assign(_size, 0.0);
    I_LATCH.assign(_size, 0.0);
    LU_VH.assign(_size, 0.0);
    LU_IH.assign(_size, 0.0);
    I_RECOVER.assign(_size, 0.0);

    for (int __i = 0; __i < _size; __i++) {
        lui_in in;
        in.token = token[__i];
        in.io = IO_PIN[__i];
        in.sup[0] = SUPPLY1_PIN[__i];
        in.sup[1] = SUPPLY2_PIN[__i];
        in.sup[2] = SUPPLY3_PIN[__i];
        in.sup[3] = SUPPLY4_PIN[__i];
        in.vsup[0] = VSUP1[__i];
        in.vsup[1] = VSUP2[__i];
        in.vsup[2] = VSUP3[__i];
        in.vsup[3] = VSUP4[__i];
        in.istart = ISTART[__i];
        in.ratio = RATIO[__i];
        in.i_end = I_END[__i];
        in.v_comp = V_COMP[__i];
        in.sup_comp = SUP_COMP[__i];
        in.idd_abs = IDD_ABS[__i];
        in.idd_rel = IDD_REL[__i];
        in.pulse_s = PULSE_S[__i];
        in.settle_s = SETTLE_S[__i];
        in.hold_step = HOLD_STEP[__i];
        in.hold_abs = HOLD_ABS[__i];
        in.meas_range = MEAS_RANGE[__i];
        in.integration = INTEGRATION[__i];
        in.debug = DEBUG[__i];

        lui_out o;
        lui_run(in, o);

        STATUS[__i] = o.status;
        STEP_COUNT[__i] = o.step_count;
        I_NOM[__i] = o.i_nom;
        LU_IT[__i] = o.it;
        LU_VT[__i] = o.vt;
        LU_SUP[__i] = o.sup;
        I_LATCH[__i] = o.i_latch;
        LU_VH[__i] = o.vh;
        LU_IH[__i] = o.ih;
        I_RECOVER[__i] = o.i_recover;
    }

    return;
}

/* Settle floor shared with latchup_supply_io (legacy imsi.pl:657-660). */
static REAL lui_floor(REAL t) { return t < 1.0E-4 ? 1.0E-4 : t; }

static void lui_measure_supplies(alg_log_t& lg, const lui_in& in,
                                 const int used[], int nu, REAL out[]) {
    for (int u = 0; u < nu; ++u) {
        double i = 0.0;
        ALG_TIS(lg, measure_i(in.sup[used[u]], &i, 0.0));
        out[used[u]] = i;
    }
}

/* Index of the used supply with the largest |cur| / thr, restricted to
 * powered supplies when powered_only is set; -1 if none qualifies. With
 * need_over set, only supplies above their threshold qualify. */
static int lui_pick_supply(const lui_in& in, const int used[], int nu,
                           const REAL cur[], const REAL thr[],
                           int powered_only, int need_over) {
    int best = -1;
    REAL best_r = 0.0;
    for (int u = 0; u < nu; ++u) {
        const int s = used[u];
        if (powered_only && in.vsup[s] == 0.0) continue;
        const REAL r = fabs(cur[s]) / thr[s];
        if (need_over && !(fabs(cur[s]) > thr[s])) continue;
        if (best < 0 || r > best_r) { best = s; best_r = r; }
    }
    return best;
}

/* Runs steps 1-4 on hardware that is already connected; returns STATUS. */
static REAL lui_sequence(alg_log_t& lg, const lui_in& in, lui_out& o,
                         const int used[], int nu) {
    const INTEGER integ = alg_integ_code(in.integration);
    const REAL pulse = lui_floor(in.pulse_s);
    const REAL settle = lui_floor(in.settle_s);

    ALG_TIS(lg, psmu_set_adc(in.io, integ, 1.0));
    for (int u = 0; u < nu; ++u)
        ALG_TIS(lg, psmu_set_adc(in.sup[used[u]], integ, 1.0));

    /* 1. Power up, IO at rest, nominal supply current. */
    for (int u = 0; u < nu; ++u) {
        const int s = used[u];
        ALG_TIS(lg, force_v(in.sup[s], in.vsup[s], in.vsup[s], in.sup_comp));
    }
    ALG_TIS(lg, force_i(in.io, 0.0, in.istart, in.v_comp));
    ALG_TIS(lg, wait_th(settle));

    REAL inom[ALG_LUI_SUPPLIES] = { 0.0, 0.0, 0.0, 0.0 };
    REAL thr[ALG_LUI_SUPPLIES] = { 1.0, 1.0, 1.0, 1.0 };
    lui_measure_supplies(lg, in, used, nu, inom);
    int undetectable = 0;
    for (int u = 0; u < nu; ++u) {
        const int s = used[u];
        const REAL a = fabs(inom[s]) + in.idd_abs;
        const REAL r = in.idd_rel * fabs(inom[s]);
        thr[s] = a > r ? a : r;
        alg_log_line(lg, 1, "sup%d %s v=%g inom=%.6e thr=%.6e", s + 1,
                     in.sup[s], (double)in.vsup[s], (double)inom[s],
                     (double)thr[s]);
        if (thr[s] >= in.sup_comp) undetectable = 1;
    }
    if (undetectable) {
        alg_log_line(lg, 1, "status=-2 thr >= sup_comp=%g", (double)in.sup_comp);
        return -2.0;
    }

    /* 2. Trigger, remove, judge by supply current. */
    REAL ipost[ALG_LUI_SUPPLIES] = { 0.0, 0.0, 0.0, 0.0 };
    REAL itrig = in.istart;
    int latched = -1;
    for (int k = 0; k < ALG_LUI_MAX_STEPS; ++k) {
        if (k > 0) itrig *= in.ratio;
        ALG_TIS(lg, force_i(in.io, itrig, itrig, in.v_comp));
        ALG_TIS(lg, wait_th(pulse));
        double vio = 0.0;
        ALG_TIS(lg, measure_v(in.io, &vio, in.meas_range));
        if (lg.level >= 2) {
            /* Supply current split while the trigger is applied: which
             * supply sinks the injected current (debug trace only). */
            REAL idur[ALG_LUI_SUPPLIES] = { 0.0, 0.0, 0.0, 0.0 };
            lui_measure_supplies(lg, in, used, nu, idur);
            for (int u = 0; u < nu; ++u)
                alg_log_line(lg, 2, "k=%d during sup%d=%.6e", k,
                             used[u] + 1, (double)idur[used[u]]);
        }
        ALG_TIS(lg, force_i(in.io, 0.0, itrig, in.v_comp));
        ALG_TIS(lg, wait_th(settle));
        lui_measure_supplies(lg, in, used, nu, ipost);
        o.step_count = (REAL)(k + 1);

        latched = lui_pick_supply(in, used, nu, ipost, thr, 0, 1);
        alg_log_line(lg, 1, "k=%d itrig=%.6e vio=%.6e post_sup1=%.6e latch=%d",
                     k, (double)itrig, vio, (double)ipost[used[0]],
                     latched >= 0 ? latched + 1 : 0);
        if (latched >= 0) {
            o.it = itrig;
            o.vt = vio;
            break;
        }
        if (fabs((double)itrig) >= fabs((double)in.i_end)) break;
        if (fabs(vio) >= fabs((double)in.v_comp)) break;
    }
    if (latched < 0) return 0.0;

    o.sup = (REAL)(latched + 1);
    o.i_nom = inom[latched];
    o.i_latch = ipost[latched];

    /* 3. Hold point: lower one powered supply until the latch releases. */
    const int hs = lui_pick_supply(in, used, nu, ipost, thr, 1, 0);
    o.vh = in.vsup[hs];
    o.ih = ipost[hs];
    if (in.hold_step > 0.0) {
        const REAL v0 = in.vsup[hs];
        const REAL dir = v0 > 0.0 ? -1.0 : 1.0;
        for (int h = 1; h <= ALG_LUI_MAX_HOLD; ++h) {
            REAL vs = v0 + dir * (REAL)h * in.hold_step;
            if ((v0 > 0.0 && vs < 0.0) || (v0 < 0.0 && vs > 0.0)) vs = 0.0;
            ALG_TIS(lg, force_v(in.sup[hs], vs, v0, in.sup_comp));
            ALG_TIS(lg, wait_th(settle));
            double ih = 0.0;
            ALG_TIS(lg, measure_i(in.sup[hs], &ih, 0.0));
            const int held = fabs(ih) - fabs((double)inom[hs]) > in.hold_abs;
            alg_log_line(lg, 1, "hold sup%d v=%g i=%.6e held=%d", hs + 1,
                         (double)vs, ih, held);
            if (!held) break;
            o.vh = vs;
            o.ih = ih;
            if (vs == 0.0) break;
        }
    }

    /* 4. Power cycle, then check the device returned to nominal. */
    for (int u = 0; u < nu; ++u) {
        const int s = used[u];
        ALG_TIS(lg, force_v(in.sup[s], 0.0, in.vsup[s], in.sup_comp));
    }
    ALG_TIS(lg, wait_th(settle));
    for (int u = 0; u < nu; ++u) {
        const int s = used[u];
        ALG_TIS(lg, force_v(in.sup[s], in.vsup[s], in.vsup[s], in.sup_comp));
    }
    ALG_TIS(lg, wait_th(settle));
    REAL irec[ALG_LUI_SUPPLIES] = { 0.0, 0.0, 0.0, 0.0 };
    lui_measure_supplies(lg, in, used, nu, irec);
    o.i_recover = irec[latched];
    const int stuck = lui_pick_supply(in, used, nu, irec, thr, 0, 1);
    return stuck >= 0 ? 2.0 : 1.0;
}

static void lui_run(const lui_in& in, lui_out& o) {
    o.status = 0.0; o.step_count = 0.0; o.i_nom = 0.0; o.it = 0.0;
    o.vt = 0.0; o.sup = 0.0; o.i_latch = 0.0; o.vh = 0.0; o.ih = 0.0;
    o.i_recover = 0.0;

    alg_log_t lg = alg_log_begin(in.debug, in.token);
    alg_log_line(lg, 1, "latchup_idd io=%s istart=%g ratio=%g iend=%g vcomp=%g",
                 in.io, (double)in.istart, (double)in.ratio,
                 (double)in.i_end, (double)in.v_comp);

    int used[ALG_LUI_SUPPLIES];
    int nu = 0;
    int powered = 0;
    for (int s = 0; s < ALG_LUI_SUPPLIES; ++s) {
        const string pin(in.sup[s]);
        if (pin.empty()) continue;
        used[nu++] = s;
        if (in.vsup[s] != 0.0) powered = 1;
    }

    if (in.istart == 0.0 || !(in.ratio > 1.0) || !(in.idd_abs > 0.0)) {
        o.status = -4.0;
    } else if (!powered) {
        o.status = -3.0;
    } else {
        for (int u = 0; u < nu; ++u)
            ALG_TIS(lg, connect_pin(PSMU, in.sup[used[u]]));
        ALG_TIS(lg, connect_pin(PSMU, in.io));
        o.status = lui_sequence(lg, in, o, used, nu);
        disable_port_all();
        disconnect_all();
        sync_th(0);
    }
    alg_log_line(lg, 1, "status=%g steps=%g it=%.6e vt=%.6e sup=%g vh=%g ih=%.6e",
                 (double)o.status, (double)o.step_count, (double)o.it,
                 (double)o.vt, (double)o.sup, (double)o.vh, (double)o.ih);
    alg_log_end(lg);
}
