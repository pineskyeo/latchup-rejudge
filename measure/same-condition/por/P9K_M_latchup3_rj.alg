$Type: Algorithm
$Name: P9K_M_latchup3_rj
$Vers: 1
$Desc: P9K_M_latchup3 measurement, VT/VH judged on the main snapback
$Date: 11/17/2026
$Time: 00:00:00
$User: dc
$-------- ----------------------- ------- - - ------
 INPUT                                               
          I1start=REAL,"A"        0                 
          I1step=REAL,"A"         0                 
          I1stop=REAL,"A"         0                 
          I1end=REAL,"A"          0                 
          V2=REAL,"V"             0                 
          V3=REAL,"V"             0                 
          V4=REAL,"V"             0                 
          V5=REAL,"V"             0                 
          V1Comp=REAL,"V"         5                 
          I2Comp=REAL,"A"         100E-3            
          I3Comp=REAL,"A"         100E-3            
          I4Comp=REAL,"A"         100E-3            
          I5Comp=REAL,"A"         100E-3            
          Tdelay=REAL,"s"         1E-3              
          findStartPoint=REAL     6                 
          Integ=STRING            "SHORT"           
          P1=STRING               ""                
          P2=STRING               ""                
          P3=STRING               ""                
          P4=STRING               ""                
          P5=STRING               ""                
 OUTPUT                                              
          PLOT=REAL                                 
          VT=REAL,"V"                               
          VH=REAL,"V"                               
          VTI=REAL,"A"                              
          VHI=REAL,"A"                              
          VT1=REAL,"V"                              
          VH1=REAL,"V"                              
          NSNAP=REAL                                
          LVT=REAL,"V"                              
          LVH=REAL,"V"                              
 DEVICE                                              
          Multi_OUTPUT1=REAL      1                 
          Multi_OUTPUT2=REAL      0                 
          Multi_OUTPUT3=REAL      0                 
          Multi_OUTPUT4=REAL      0                 
          Multi_OUTPUT5=REAL      0                 
          OutputName=STRING       ""                
          DvAbs=REAL,"V"          0.05              
          DvRel=REAL              0.03              
          MainFrac=REAL           0.7               
 TERMINAL                                            
          P1                                  IO    
          P2                                  SUP2  
          P3                                  SUP3  
          P4                                  SUP4  
          P5                                  SUP5  
$-------- ----------------------- ------- - - ------
