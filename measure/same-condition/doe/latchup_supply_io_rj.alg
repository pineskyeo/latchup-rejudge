
$Type: Algorithm
$Name: latchup_supply_io_rj
$Vers: 1
$Desc: Latch-up current ramp, VT/VH judged on the main snapback
$Date: 11/17/2026
$Time: 00:00:00
$User: cortex_new_algorithm
$-------- --------------------- -------- - - ------
 INPUT                                             
          token=STRING          ""                 
          IO_PIN=STRING                            
          SUPPLY1_PIN=STRING    ""                 
          SUPPLY2_PIN=STRING    ""                 
          SUPPLY3_PIN=STRING    ""                 
          SUPPLY4_PIN=STRING    ""                 
          VSUP1=REAL,"V"        0                  
          VSUP2=REAL,"V"        0                  
          VSUP3=REAL,"V"        0                  
          VSUP4=REAL,"V"        0                  
          ISTART=REAL,"A"                          
          ISTEP=REAL,"A"                           
          ISTOP=REAL,"A"                           
          I_END=REAL,"A"                           
          V_COMP=REAL,"V"                          
          SUP_COMP=REAL,"A"     1E-3               
          FIND_START=INTEGER    0                  
          MEAS_RANGE=REAL,"V"   0                  
          DELAY_S=REAL,"s"                         
          INTEGRATION=STRING                       
          DV_ABS=REAL,"V"       0.05               
          DV_REL=REAL           0.03               
          MAIN_FRAC=REAL        0.7                
          DEBUG=INTEGER         0                  
 OUTPUT                                            
          POINT_COUNT_RAW=REAL  0                  
          VT=REAL               0                  
          VH=REAL               0                  
          VT_I=REAL             0                  
          VH_I=REAL             0                  
          VT1=REAL              0                  
          VH1=REAL              0                  
          N_SNAP=REAL           0                  
          LEG_VT=REAL           0                  
          LEG_VH=REAL           0                  
 DEVICE                                            
 TERMINAL                                          
          IO_PIN                                   
          SUPPLY1_PIN                              
          SUPPLY2_PIN                              
          SUPPLY3_PIN                              
          SUPPLY4_PIN                              
$-------- --------------------- -------- - - ------

