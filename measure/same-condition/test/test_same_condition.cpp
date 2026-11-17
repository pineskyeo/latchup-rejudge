/* Equivalence test for the "same measurement, fixed judgment" latch-up
 * algorithms, against the cortex stub TIS.
 *
 * For every case in the fixture (expected values from latchup_rejudge.py):
 *  1. POR P9K_M_latchup3_rj: VT/VH/VTI/VHI/VT1/VH1/NSNAP = rejudge main rule,
 *     LVT/LVH = rejudge legacy_judge
 *  2. DOE latchup_supply_io_rj: every output equals POR, same instrument calls
 *  3. measurement unchanged: DOE _rj makes exactly the same instrument calls
 *     as the original cortex latchup_supply_io, and its LEG_VT/LEG_VH equal
 *     the original VT/VH
 */
#include CORTEX_ORIG_SRC
#include "../doe/latchup_supply_io_rj.cpp"
#include "../por/P9K_M_latchup3_rj.cpp"

#include <cmath>
#include <fstream>
#include <sstream>

static int g_fail = 0, g_ok = 0;
static void check(bool c, const std::string& msg) {
    if (!c) { printf("FAIL: %s\n", msg.c_str()); g_fail++; } else g_ok++;
}
static bool near(double a, double b) {
    return fabs(a - b) <= 1e-9 * (fabs(b) > 1e-30 ? fabs(b) : 1.0);
}

struct fx {
    std::string name;
    int n_grid, sign;
    std::vector<double> v;
    int nsnap, vt, vh, vt1, vh1, lvt, lvh;
};

static std::vector<fx> load_fixture(const char* path) {
    std::vector<fx> out;
    std::ifstream f(path);
    std::string l1, l2, l3;
    while (std::getline(f, l1) && std::getline(f, l2) && std::getline(f, l3)) {
        fx c;
        std::istringstream a(l1), b(l2), d(l3);
        a >> c.name >> c.n_grid >> c.sign;
        double x;
        while (b >> x) c.v.push_back(x);
        d >> c.nsnap >> c.vt >> c.vh >> c.vt1 >> c.vh1 >> c.lvt >> c.lvh;
        out.push_back(c);
    }
    return out;
}

/* Inputs that reproduce a fixture curve: grid n_grid, stop after m points. */
struct setup { double istart, istep, istop, iend; };
static setup make_setup(const fx& c) {
    setup s;
    s.istart = c.sign * 1e-7;
    s.istep = s.istart;
    s.istop = s.istart * (c.n_grid + 0.5);       /* (stop-start)/step + 1 = n + 0.5 */
    const int m = (int)c.v.size();
    s.iend = (m == c.n_grid) ? 1e9 : 1e-7 * pow(1.05, m) * (1 - 1e-9);
    return s;
}

static std::string calls_until_release(bool skip_framing) {
    std::string s;
    for (size_t i = 0; i < g_calls.size(); ++i) {
        if (g_calls[i] == "disable_port_all") break;
        if (skip_framing && (g_calls[i] == "start_tis_log" || g_calls[i] == "stop_tis_log" ||
                             g_calls[i] == "sync_th")) continue;
        s += g_calls[i] + ";";
    }
    return s;
}

static void reset(const fx& c) {
    g_calls.clear();
    g_meas_v.clear();
    g_meas_v["TIO"] = c.v;
}

struct res { double o[10]; std::string trace, full; bool drained; };

static res run_por(const fx& c) {
    const setup s = make_setup(c);
    reset(c);
    std::vector<REAL> ist(1, s.istart), istep(1, s.istep), istop(1, s.istop), iend(1, s.iend);
    std::vector<REAL> v2(1, 0.0), v3(1, 0.0), v4(1, 0.0), v5(1, 0.0), vc(1, 100.0);
    std::vector<REAL> c2(1, 1e-3), c3(1, 1e-3), c4(1, 1e-3), c5(1, 1e-3), td(1, 1e-3), fs(1, 6);
    std::vector<STRINGP> integ(1, (STRINGP)"SHORT"), p1(1, (STRINGP)"TIO"), p2(1, (STRINGP)"TVDD"),
                         p3(1, (STRINGP)"TVSS"), p4(1, (STRINGP)""), p5(1, (STRINGP)""), on(1, (STRINGP)c.name.c_str());
    std::vector<REAL> m1(1, 1.0), m0(1, 0.0), da(1, 0.05), dr(1, 0.03), mf(1, 0.7);
    std::vector<REAL> PLOT, VT, VH, VTI, VHI, VT1, VH1, NS, LVT, LVH;
    P9K_M_latchup3_rj_sub(ist, istep, istop, iend, v2, v3, v4, v5, vc, c2, c3, c4, c5, td, fs,
                          integ, p1, p2, p3, p4, p5, m1, m0, m0, m0, m0, on, da, dr, mf,
                          PLOT, VT, VH, VTI, VHI, VT1, VH1, NS, LVT, LVH, 1);
    res r;
    double o[10] = { PLOT[0], VT[0], VH[0], VTI[0], VHI[0], VT1[0], VH1[0], NS[0], LVT[0], LVH[0] };
    for (int k = 0; k < 10; k++) r.o[k] = o[k];
    r.trace = calls_until_release(true);
    r.drained = g_meas_v["TIO"].empty();
    return r;
}

static void doe_inputs(const fx& c, const setup& s,
        std::vector<STRINGP>& tok, std::vector<STRINGP>& io, std::vector<STRINGP>& s1,
        std::vector<STRINGP>& s2, std::vector<STRINGP>& s3, std::vector<STRINGP>& s4) {
    (void)c; (void)s;
    tok.assign(1, (STRINGP)"RUN1__cx1.tsv001.eg001.Md01.tg001.c0001");
    io.assign(1, (STRINGP)"TIO"); s1.assign(1, (STRINGP)"TVDD"); s2.assign(1, (STRINGP)"TVSS");
    s3.assign(1, (STRINGP)""); s4.assign(1, (STRINGP)"");
}

static res run_doe_rj(const fx& c) {
    const setup s = make_setup(c);
    reset(c);
    std::vector<STRINGP> tok, io, s1, s2, s3, s4;
    doe_inputs(c, s, tok, io, s1, s2, s3, s4);
    std::vector<REAL> vz(1, 0.0), ist(1, s.istart), istep(1, s.istep), istop(1, s.istop), iend(1, s.iend);
    std::vector<REAL> vc(1, 100.0), sc(1, 1e-3), mr(1, 0.0), dl(1, 1e-3), da(1, 0.05), dr(1, 0.03), mf(1, 0.7);
    std::vector<INTEGER> fs(1, 6), dbg(1, 0);
    std::vector<STRINGP> integ(1, (STRINGP)"SHORT");
    std::vector<REAL> PC, VT, VH, VTI, VHI, VT1, VH1, NS, LVT, LVH;
    latchup_supply_io_rj(tok, io, s1, s2, s3, s4, vz, vz, vz, vz, ist, istep, istop, iend, vc, sc,
                         fs, mr, dl, integ, da, dr, mf, dbg,
                         PC, VT, VH, VTI, VHI, VT1, VH1, NS, LVT, LVH, 1);
    res r;
    double o[10] = { PC[0], VT[0], VH[0], VTI[0], VHI[0], VT1[0], VH1[0], NS[0], LVT[0], LVH[0] };
    for (int k = 0; k < 10; k++) r.o[k] = o[k];
    r.trace = calls_until_release(true);
    r.full = "";
    for (size_t i = 0; i < g_calls.size(); ++i) r.full += g_calls[i] + ";";
    r.drained = g_meas_v["TIO"].empty();
    return r;
}

static res run_doe_orig(const fx& c) {
    const setup s = make_setup(c);
    reset(c);
    std::vector<STRINGP> tok, io, s1, s2, s3, s4;
    doe_inputs(c, s, tok, io, s1, s2, s3, s4);
    std::vector<REAL> vz(1, 0.0), ist(1, s.istart), istep(1, s.istep), istop(1, s.istop), iend(1, s.iend);
    std::vector<REAL> vc(1, 100.0), sc(1, 1e-3), mr(1, 0.0), dl(1, 1e-3);
    std::vector<INTEGER> fs(1, 6), dbg(1, 0);
    std::vector<STRINGP> integ(1, (STRINGP)"SHORT");
    std::vector<REAL> PC, VT, VH, VTI, VHI;
    latchup_supply_io(tok, io, s1, s2, s3, s4, vz, vz, vz, vz, ist, istep, istop, iend, vc, sc,
                      fs, mr, dl, integ, dbg, PC, VT, VH, VTI, VHI, 1);
    res r;
    for (int k = 0; k < 10; k++) r.o[k] = 0;
    r.o[0] = PC[0]; r.o[1] = VT[0]; r.o[2] = VH[0];
    r.full = "";
    for (size_t i = 0; i < g_calls.size(); ++i) r.full += g_calls[i] + ";";
    r.drained = g_meas_v["TIO"].empty();
    return r;
}

static double at(const fx& c, int idx) { return idx < 0 ? 0.0 : c.v[idx]; }
static double cur_at(const fx& c, int idx) { return idx < 0 ? 0.0 : c.sign * 1e-7 * pow(1.05, idx + 1); }

int main(int argc, char** argv) {
    if (argc < 2) { printf("usage: %s fixture.txt\n", argv[0]); return 2; }
    const std::vector<fx> cases = load_fixture(argv[1]);
    check(!cases.empty(), "fixture loaded");
    static const char* nm[10] = { "PLOT", "VT", "VH", "VTI", "VHI", "VT1", "VH1", "NSNAP", "LVT", "LVH" };

    for (size_t k = 0; k < cases.size(); ++k) {
        const fx& c = cases[k];
        const std::string t = c.name + ": ";
        const res p = run_por(c);
        const double exp[10] = { (double)c.v.size(), at(c, c.vt), at(c, c.vh), cur_at(c, c.vt),
                                 cur_at(c, c.vh), at(c, c.vt1), at(c, c.vh1), (double)c.nsnap,
                                 at(c, c.lvt), at(c, c.lvh) };
        for (int o = 0; o < 10; o++)
            check(near(p.o[o], exp[o]), t + "POR " + nm[o] + " = rejudge");
        check(p.drained, t + "POR consumed every point");

        const res d = run_doe_rj(c);
        for (int o = 0; o < 10; o++)
            check(d.o[o] == p.o[o], t + "DOE " + nm[o] + " == POR");
        check(d.trace == p.trace, t + "DOE and POR instrument calls identical");

        const res g = run_doe_orig(c);
        check(g.full == d.full, t + "measurement unchanged: _rj calls == original latchup_supply_io");
        check(g.o[0] == d.o[0], t + "same point count as original");
        check(g.o[1] == d.o[8] && g.o[2] == d.o[9], t + "LEG_VT/LEG_VH == original VT/VH");
        printf("%-22s pts=%3d snaps=%d  legacy VT=%.4f VH=%.4f  ->  new VT=%.4f VH=%.4f\n",
               c.name.c_str(), (int)p.o[0], (int)p.o[7], p.o[8], p.o[9], p.o[1], p.o[2]);
    }

    printf("\n%d checks ok, %d failed\n", g_ok, g_fail);
    return g_fail ? 1 : 0;
}
