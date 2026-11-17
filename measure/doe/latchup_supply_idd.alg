
$Type: Algorithm
$Name: latchup_supply_idd
$Vers: 1
$Desc: Powered-supply latch-up I-test: trigger, remove, judge by supply current
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
          RATIO=REAL            1.05               
          I_END=REAL,"A"                           
          V_COMP=REAL,"V"                          
          SUP_COMP=REAL,"A"     0.1                
          IDD_ABS=REAL,"A"      1E-2               
          IDD_REL=REAL          1.4                
          PULSE_S=REAL,"s"      1E-3               
          SETTLE_S=REAL,"s"     1E-3               
          HOLD_STEP=REAL,"V"    0.05               
          HOLD_ABS=REAL,"A"     1E-4               
          MEAS_RANGE=REAL,"V"   0                  
          INTEGRATION=STRING                       
          DEBUG=INTEGER         0                  
 OUTPUT                                            
          STATUS=REAL           0                  
          STEP_COUNT=REAL       0                  
          I_NOM=REAL            0                  
          LU_IT=REAL            0                  
          LU_VT=REAL            0                  
          LU_SUP=REAL           0                  
          I_LATCH=REAL          0                  
          LU_VH=REAL            0                  
          LU_IH=REAL            0                  
          I_RECOVER=REAL        0                  
 DEVICE                                            
 TERMINAL                                          
          IO_PIN                                   
          SUPPLY1_PIN                              
          SUPPLY2_PIN                              
          SUPPLY3_PIN                              
          SUPPLY4_PIN                              
$-------- --------------------- -------- - - ------

