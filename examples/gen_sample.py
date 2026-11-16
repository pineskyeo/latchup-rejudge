"""합성 LUP log 생성: 단일/이중 snapback, 회복, 무트리거, 노이즈, 음극성, 재측정."""
import random
import sys
random.seed(1)
N=269
I=[1e-7*1.05**(j+1) for j in range(N)]
def lerp(a,b,t): return a+(b-a)*t
def seg(pts):
    # pts: list of (index, V) knots -> piecewise linear over index
    v=[]
    for j in range(N):
        for (j0,v0),(j1,v1) in zip(pts,pts[1:]):
            if j0<=j<=j1: v.append(lerp(v0,v1,(j-j0)/max(1,j1-j0))); break
    return v
cases={
 'A_single':   seg([(0,0.005),(150,8.0),(151,1.5),(268,1.9)]),
 'B_double':   seg([(0,0.005),(120,7.0),(121,4.0),(170,9.0),(171,1.5),(268,1.9)]),
 'C_notrig':   seg([(0,0.005),(268,10.0)]),
 'D_recover':  seg([(0,0.005),(150,8.0),(151,4.0),(268,9.5)]),
 'G_double_lowVt2': seg([(0,0.005),(120,7.0),(121,4.0),(170,6.0),(171,1.5),(268,1.9)]),
}
noisy=seg([(0,0.005),(120,7.0),(121,4.0),(170,9.0),(171,1.5),(268,1.9)])
cases['E_double_noise']=[x+random.gauss(0,0.005) for x in noisy]
with open(sys.argv[1] if len(sys.argv) > 1 else 'sample_lup.log', 'w') as f:
    f.write("EQPID,PCID,PARTID,LOTID,WFID,XAXIS,YAXIS,DCOP,MOD,ITEM,NUM,If,V1\n")
    for k,(name,v) in enumerate(cases.items()):
        for j in range(N):
            f.write("EQPA,CARDA,PARTA,LOTA,5,%d,2,DCOPA,MODA,%s,%d,%.6g,%.6g\n"%(k,name,j+1,I[j],v[j]))
    # negative polarity double snapback
    v=cases['B_double']
    for j in range(N):
        f.write("EQPA,CARDA,PARTA,LOTA,5,9,2,DCOPA,MODA,F_neg_double,%d,%.6g,%.6g\n"%(j+1,-I[j],-v[j]))
    # retest of A on same key (NUM resets)
    for j in range(N):
        f.write("EQPA,CARDA,PARTA,LOTA,5,0,2,DCOPA,MODA,A_single,%d,%.6g,%.6g\n"%(j+1,I[j],cases['A_single'][j]))
