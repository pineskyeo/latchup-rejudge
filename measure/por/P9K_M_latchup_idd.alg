$Type: Algorithm
$Name: P9K_M_latchup_idd
$Vers: 1
$Desc: Powered-supply latch-up I-test (trigger, remove, judge by supply current)
$Date: 11/17/2026
$Time: 00:00:00
$User: dc
$-------- ----------------------- ------- - - ------
 INPUT                                               
          I1start=REAL,"A"        0                 
          I1ratio=REAL            1.05              
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
          Iabs=REAL,"A"           10E-3             
          Irel=REAL               1.4               
          Tpulse=REAL,"s"         1E-3              
          Tdelay=REAL,"s"         1E-3              
          Vhstep=REAL,"V"         0.05              
          Ihabs=REAL,"A"          100E-6            
          Integ=STRING            "SHORT"           
          P1=STRING               ""                
          P2=STRING               ""                
          P3=STRING               ""                
          P4=STRING               ""                
          P5=STRING               ""                
 OUTPUT                                              
          STATUS=REAL                               
          STEP_COUNT=REAL                           
          I_NOM=REAL,"A"                            
          LU_IT=REAL,"A"                            
          LU_VT=REAL,"V"                            
          LU_SUP=REAL                               
          I_LATCH=REAL,"A"                          
          LU_VH=REAL,"V"                            
          LU_IH=REAL,"A"                            
          I_RECOVER=REAL,"A"                        
 DEVICE                                              
          Multi_OUTPUT1=REAL      1                 
          OutputName=STRING       ""                
 TERMINAL                                            
          P1                                  IO    
          P2                                  SUP2  
          P3                                  SUP3  
          P4                                  SUP4  
          P5                                  SUP5  
$-------- ----------------------- ------- - - ------
