# Festo Station Simulator Detailed Design Diagram

## 1. Core Class: FestoStation

### 1.1 Initialization Parameters and State Variables
```
+-------------------------------------------------------+
|                 FestoStation.__init__                 |
+-------------------------------------------------------+
| Input Parameters:                                     |
| - env: SimPy real-time environment instance           |
+-------------------------------------------------------+
| Time Parameters:                                      |
| - extend_time = 2: Cylinder extension time (seconds)  |
| - move_time = 3: Manipulator movement time (seconds)  |
| - vacuum_time = 2: Vacuum suction cup action time (s) |
+-------------------------------------------------------+
| Workpiece and Magazine Status:                        |
| - workpiece_count = 8: Initial workpiece count        |
| - S3 = True: Magazine not empty flag (True=not empty) |
| - k = False: Refill needed flag (calculated from !S3) |
+-------------------------------------------------------+
| Position Sensor Initial States:                       |
| - S1 = True: Cylinder retracted sensor (True=retracted)|
| - S2 = False: Cylinder extended sensor (True=extended)|
| - S4 = True: Manipulator at next station (True=at pos)|
| - S5 = False: Manipulator at magazine (True=at pos)   |
| - S6 = False: Vacuum suction cup status (True=active) |
+-------------------------------------------------------+
| Actuator Initial States:                              |
| - Y1 = False: Cylinder control (True=extend,False=retract)|
| - Y2 = False: Manipulator control (True=move,False=stop) |
| - Y3 = False: Vacuum control (True=on,False=off)      |
+-------------------------------------------------------+
| State Machine and Control Events:                     |
| - state = 0: Initial state (0-8)                      |
| - emergency_flag = False: Emergency stop flag         |
| - start_event = env.event(): Start event              |
+-------------------------------------------------------+
| Time Measurement Variables:                           |
| - cycle_start_time = 0: Cycle start time              |
| - t1 = 0: Cycle time (complete normal cycle)          |
| - t2 = 0: Magazine refill time                        |
| - magazine_refill_time = 10: Magazine refill wait (s) |
| - t2_start_marker = 0: t2 measurement start marker    |
| - first_cycle = True: First cycle flag                |
| - cycle_blocked = False: Cycle blocked flag           |
| - measuring_t2 = False: t2 measurement in progress    |
+-------------------------------------------------------+
| History Arrays (for plotting):                        |
| - time_history = []: Time point history               |
| - state_history = []: State history                   |
| - workpiece_history = []: Workpiece count history     |
| - sensor_history = {}: Sensor state history dictionary |
|   - 'S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'k'           |
| - act_history = {}: Actuator state history dictionary  |
|   - 'Y1', 'Y2', 'Y3'                                  |
| - t1_history = []: t1 time measurement history        |
| - t2_history = []: t2 time measurement history        |
+-------------------------------------------------------+
| Initialization Operations:                            |
| - Start state machine process: env.process(self.run())|
+-------------------------------------------------------+
```

### 1.2 Core Methods

```
+-------------------------------------------------------+
|               FestoStation.update_logic               |
+-------------------------------------------------------+
| Function: Update actuator logic expressions based on  |
|           current sensor states                       |
| Input: None (uses class internal state)               |
| Output: None (updates class internal actuator states) |
+-------------------------------------------------------+
| Implementation Logic:                                 |
| 1. Update k = !S3 (magazine empty flag)               |
| 2. Determine Y1 logic based on t1 and t2 relationship:|
|    - First cycle or t2 not measured: Y1 = !S6         |
|    - t1 > t2: Y1 = !S6 (normal operation)             |
|    - t2 > t1: Y1 = !S6 && (!k || !S4) (blocked op)    |
| 3. Update Y2 = S2 || (!S1 && !S4)                     |
| 4. Update Y3 = S5 || (S1 && !S4)                      |
+-------------------------------------------------------+

+-------------------------------------------------------+
|                  FestoStation.log                     |
+-------------------------------------------------------+
| Function: Record current state to history arrays and  |
|           output information                          |
| Input: msg - Message string to output                 |
| Output: None (updates history arrays and prints)      |
+-------------------------------------------------------+
| Implementation Logic:                                 |
| 1. Get current time t = env.now                       |
| 2. Add current time and state to history arrays       |
| 3. Add all sensor and actuator states to history dicts|
| 4. Add t1 and t2 to corresponding history arrays      |
| 5. Format output of time, workpiece count, t1, t2, msg|
+-------------------------------------------------------+

+-------------------------------------------------------+
|              FestoStation.trigger_start               |
+-------------------------------------------------------+
| Function: Trigger system start                        |
| Input: None                                           |
| Output: None (triggers start_event)                   |
+-------------------------------------------------------+
| Implementation Logic:                                 |
| 1. Check if currently in state 0 (idle)               |
| 2. If yes, try to trigger start_event.succeed()       |
| 3. If already started, catch RuntimeError and ignore  |
| 4. If not in state 0, output start ignored message    |
+-------------------------------------------------------+

+-------------------------------------------------------+
|           FestoStation.trigger_emergency              |
+-------------------------------------------------------+
| Function: Trigger emergency stop                      |
| Input: None                                           |
| Output: None (interrupts state machine process)       |
+-------------------------------------------------------+
| Implementation Logic:                                 |
| 1. Check if not in state 0 and emergency_flag is False|
| 2. If condition met, set emergency_flag to True       |
| 3. Call process.interrupt() to interrupt state machine|
+-------------------------------------------------------+

+-------------------------------------------------------+
|              FestoStation.trigger_exit                |
+-------------------------------------------------------+
| Function: Trigger program exit                        |
| Input: None                                           |
| Output: None (closes charts and exits program)        |
+-------------------------------------------------------+
| Implementation Logic:                                 |
| 1. Output exit message                                |
| 2. Close all matplotlib charts (plt.close('all'))     |
| 3. Call sys.exit() to exit program                    |
+-------------------------------------------------------+
```

### 1.3 State Machine Main Loop

```
+-------------------------------------------------------+
|                  FestoStation.run                     |
+-------------------------------------------------------+
| Function: Implement state machine main loop logic     |
| Input: None                                           |
| Output: SimPy generator function                      |
+-------------------------------------------------------+
| State Machine Implementation:                         |
|                                                       |
| State 0: Idle                                         |
| - Set initial sensor states: S1=True, S3=True, S4=True|
| - Update actuator logic                               |
| - Wait for start_event                                |
|                                                       |
| Cycle Start: Record cycle_start_time = env.now        |
|                                                       |
| State 1: Cylinder Extension                           |
| - Update actuator logic                               |
| - Wait for extend_time seconds                        |
| - Update sensors: S2=True, S1=False                   |
|                                                       |
| State 2: Move Manipulator to Magazine                 |
| - Update actuator logic                               |
| - Wait for move_time seconds                          |
| - Update sensors: S5=True, S4=False                   |
|                                                       |
| State 3: Activate Vacuum Suction Cup                  |
| - Update actuator logic                               |
| - Wait for vacuum_time seconds                        |
| - Update sensors: S6=True                             |
|                                                       |
| State 4: Retract Cylinder                             |
| - Update actuator logic                               |
| - Wait for extend_time seconds                        |
| - Update sensors: S1=True, S2=False                   |
| - Decrease workpiece count: workpiece_count -= 1      |
| - Update S3 = (workpiece_count > 0)                   |
|                                                       |
| Magazine Empty Check Branch:                          |
| If S3=False (magazine empty):                         |
|   - Record t2_start_marker = env.now                  |
|   - Set measuring_t2 = True                           |
|   - Calculate t1 = env.now - cycle_start_time         |
|   - Enter State 7: Magazine empty, wait for refill    |
|   - Wait until S3 becomes True (magazine refilled)    |
|   - Reset workpiece count: workpiece_count = 8        |
|   - Update sensors: S3=True, S6=False                 |
|   - Enter State 8: Refilled, wait 3 seconds           |
|   - Wait 3 seconds                                    |
|   - Return to State 1                                 |
|   - If measuring_t2=True:                             |
|     - Calculate t2 = env.now - t2_start_marker        |
|     - Set measuring_t2 = False                        |
|     - Compare t1 and t2, set cycle_blocked flag       |
|   - Set first_cycle = False                           |
|   - Continue to next cycle                            |
|                                                       |
| State 5: Return Manipulator to Next Station           |
| - Update actuator logic                               |
| - Wait for move_time seconds                          |
| - Update sensors: S4=True, S5=False                   |
|                                                       |
| State 6: Deactivate Vacuum Suction Cup                |
| - Update actuator logic                               |
| - Wait for vacuum_time seconds                        |
| - Update sensors: S6=False                            |
| - Calculate complete cycle time: t1 = env.now - cycle_start_time |
| - Set first_cycle = False                             |
|                                                       |
| Return to State 1, start new cycle                    |
+-------------------------------------------------------+
| Exception Handling:                                   |
| Catch simpy.Interrupt exception (emergency stop):     |
| - Reset to state 0                                    |
| - Reset all sensor states                             |
| - Update actuator logic                               |
| - Reset emergency_flag = False                        |
| - Reset start_event = env.event()                     |
| - Recursively call run() to restart state machine     |
+-------------------------------------------------------+
```

## 2. Helper Function: blank_generator

```
+-------------------------------------------------------+
|                   blank_generator                     |
+-------------------------------------------------------+
| Function: Implement magazine refill logic             |
| Input:                                                |
| - env: SimPy environment instance                     |
| - station: FestoStation instance                      |
| Output: SimPy generator function                      |
+-------------------------------------------------------+
| Implementation Logic:                                 |
| Infinite loop:                                        |
|   If station.S3 is False (magazine empty):            |
|     - Wait station.magazine_refill_time seconds       |
|     - Set station.S3 = True (magazine refilled)       |
|     - Log refill completion                           |
|   Else:                                               |
|     - Wait 1 second (polling check)                   |
+-------------------------------------------------------+
```

## 3. Main Function: run_gui

```
+-------------------------------------------------------+
|                      run_gui                          |
+-------------------------------------------------------+
| Function: Set up simulation environment and GUI       |
| Input: None                                           |
| Output: None (starts GUI main loop)                   |
+-------------------------------------------------------+
| Implementation Steps:                                 |
|                                                       |
| 1. SimPy Environment Setup:                           |
| - Create RealtimeEnvironment(factor=1.0, strict=True) |
| - Create FestoStation instance                        |
| - Start blank_generator process                       |
| - Run env.run() in separate thread                    |
|                                                       |
| 2. Tkinter GUI Setup:                                 |
| - Create main window root = tk.Tk()                   |
| - Set window title and close handler                  |
|                                                       |
| 3. Matplotlib Chart Setup:                            |
| - Create 8 subplots (fig, axs = plt.subplots(8,1))    |
| - Create FigureCanvasTkAgg embedded in Tkinter        |
|                                                       |
| 4. Define animation update function update(frame):    |
|   a. State Transition Chart (axs[0]):                 |
|      - Plot state history as step chart               |
|      - Annotate current state                         |
|                                                       |
|   b. Workpiece Count Chart (axs[1]):                  |
|      - Plot workpiece count history as step chart     |
|      - Annotate current workpiece count               |
|                                                       |
|   c. t1 and t2 Time Chart (axs[2]):                   |
|      - Plot t1 and t2 history as line charts          |
|      - Annotate current t1 and t2 values              |
|                                                       |
|   d. Sensor State Charts (axs[3-5]):                  |
|      - S1 and S2 cylinder state chart                 |
|      - S4 and S5 manipulator position chart           |
|      - S6 vacuum suction cup state chart              |
|                                                       |
|   e. Magazine State Chart (axs[6]):                   |
|      - S3 and k state chart                           |
|                                                       |
|   f. Actuator State Chart (axs[7]):                   |
|      - Y1, Y2, Y3 state chart                         |
|                                                       |
| 5. Create Animation:                                  |
| - ani = FuncAnimation(fig, update, interval=500)      |
|                                                       |
| 6. Create Control Buttons:                            |
| - Start button: Call station.trigger_start()          |
| - Emergency Stop button: Call station.trigger_emergency() |
| - Exit button: Call station.trigger_exit()            |
|                                                       |
| 7. Start Tkinter Main Loop:                           |
| - root.mainloop()                                     |
+-------------------------------------------------------+
```

## 4. Data Flow Diagram

```
+----------------+    +----------------+    +----------------+
|  Sensor States |    | State Machine  |    | Actuator Control|
|  S1-S6, k      |--->|  States 0-8    |--->|  Y1-Y3         |
+----------------+    +----------------+    +----------------+
        ^                     |                     |
        |                     v                     v
+----------------+    +----------------+    +----------------+
|  Workpiece     |<---|  Time          |    |  History       |
|  Count         |    |  Measurement   |    |  Records       |
+----------------+    +----------------+    +----------------+
        ^                     ^                     |
        |                     |                     v
+----------------+    +----------------+    +----------------+
|  Magazine      |    |  GUI Control   |    |  Visualization |
|  Refill Logic  |<---|  Buttons       |<---|  Charts        |
+----------------+    +----------------+    +----------------+
```

## 5. Key Logic Expressions Explained

```
1. Magazine Empty Flag: k = !S3

2. Cylinder Control Logic (Y1):
   - First cycle or t2 not measured: Y1 = !S6
   - When t1 > t2 (normal operation): Y1 = !S6
   - When t2 > t1 (blocked operation): Y1 = !S6 && (!k || !S4)
   
   Explanation:
   - !S6: Cylinder can only operate when vacuum suction cup is not active
   - When t2 > t1, additional condition (!k || !S4):
     * !k: Can operate when magazine is not empty
     * !S4: Can operate when manipulator is not at next station
     * This ensures that when magazine refill time is longer than cycle time,
       the system won't try to start a new cycle when magazine is empty and
       manipulator is at the next station

3. Manipulator Control Logic (Y2): Y2 = S2 || (!S1 && !S4)
   Explanation:
   - S2: Move manipulator when cylinder is extended
   - !S1 && !S4: Move manipulator when cylinder is not retracted and
                 manipulator is not at next station

4. Vacuum Suction Cup Control Logic (Y3): Y3 = S5 || (S1 && !S4)
   Explanation:
   - S5: Activate vacuum when manipulator is at magazine
   - S1 && !S4: Activate vacuum when cylinder is retracted and
                manipulator is not at next station
```

## 6. Time Measurement Logic Explained

```
t1 Measurement (Cycle Time):
- Start: Record cycle_start_time = env.now at the beginning of each cycle
- End: 
  * If magazine is empty: Calculate t1 = env.now - cycle_start_time at the end of state 4
  * Normal cycle: Calculate t1 = env.now - cycle_start_time at the end of state 6

t2 Measurement (Magazine Refill Time):
- Start: Record t2_start_marker = env.now when magazine becomes empty
- End: Calculate t2 = env.now - t2_start_marker when magazine is refilled and returns to state 1

t1 and t2 Comparison Logic:
- If t1 > t2: System can cycle normally, as magazine refill is faster than work cycle
- If t2 > t1: System needs to wait for magazine refill, using more complex Y1 logic to prevent starting new cycles when magazine is empty
```

## 7. State Machine Detailed Flow Chart

```
+-------------------+
|   State 0: Idle   |
+-------------------+
         |
         | [Start Button]
         v
+-------------------+
|State 1: Extend Cyl|<---------+
+-------------------+          |
         |                     |
         | [extend_time]       |
         v                     |
+-------------------+          |
|State 2: Move to   |          |
|      Magazine     |          |
+-------------------+          |
         |                     |
         | [move_time]         |
         v                     |
+-------------------+          |
|State 3: Activate  |          |
|    Vacuum Cup     |          |
+-------------------+          |
         |                     |
         | [vacuum_time]       |
         v                     |
+-------------------+          |
|State 4: Retract   |          |
|     Cylinder      |          |
+-------------------+          |
         |                     |
    +----+----+                |
    |         |                |
[S3=True] [S3=False]           |
    |         |                |
    |         v                |
    |  +-------------------+   |
    |  |State 7: Wait for  |   |
    |  |  Magazine Refill  |   |
    |  +-------------------+   |
    |         |                |
    |         | [Magazine Refilled]
    |         v                |
    |  +-------------------+   |
    |  |State 8: Wait After|   |
    |  |      Refill       |   |
    |  +-------------------+   |
    |         |                |
    |         | [3 second wait]|
    |         +----------------+
    v
+-------------------+
|State 5: Return to |
|    Next Station   |
+-------------------+
         |
         | [move_time]
         v
+-------------------+
|State 6: Deactivate|
|    Vacuum Cup     |
+-------------------+
         |
         | [vacuum_time]
         +----------------+
```

## 8. Key Timing Diagrams

### 8.1 Normal Cycle Timing (t1 > t2)

```
Time   ─────────────────────────────────────────────────────────>
State  0    1    2    3    4    5    6    1    2    3    4    ...
       │    │    │    │    │    │    │    │    │    │    │
S1     │████│    │    │    │████│████│████│    │    │    │████...
S2     │    │████│████│████│    │    │    │████│████│████│    ...
S3     │████│████│████│████│████│████│████│████│████│████│████...
S4     │████│████│    │    │    │████│████│████│    │    │    ...
S5     │    │    │████│████│████│    │    │    │████│████│████...
S6     │    │    │    │████│████│████│    │    │    │████│████...
Y1     │    │████│    │    │    │    │    │████│    │    │    ...
Y2     │    │    │████│    │    │████│    │    │████│    │    ...
Y3     │    │    │    │████│████│    │    │    │    │████│████...
       │    │<──────── t1 ────────>│    │
```

### 8.2 Magazine Refill Timing (t2 > t1)

```
Time   ─────────────────────────────────────────────────────────>
State  0    1    2    3    4    7    8    1    2    3    4    ...
       │    │    │    │    │    │    │    │    │    │    │
S1     │████│    │    │    │████│████│████│    │    │    │████...
S2     │    │████│████│████│    │    │    │████│████│████│    ...
S3     │████│████│████│████│    │████│████│████│████│████│    ...
S4     │████│████│    │    │    │    │    │████│    │    │    ...
S5     │    │    │████│████│████│████│    │    │████│████│████...
S6     │    │    │    │████│████│    │    │    │    │████│████...
Y1     │    │████│    │    │    │    │    │████│    │    │    ...
Y2     │    │    │████│    │    │    │    │    │████│    │    ...
Y3     │    │    │    │████│████│    │    │    │    │████│████...
       │    │<── t1 ──>│    │    │    │    │
       │    │<────────── t2 ────────────>│    │
```

## 9. System Architecture Diagram

```
+-----------------------------------------------------+
|                    GUI Layer                        |
| +------------------+  +-------------------------+   |
| |   Control Panel  |  |    Visualization Panel  |   |
| | - Start          |  | - State Transition Chart|   |
| | - Emergency Stop |  | - Workpiece Count Chart |   |
| | - Exit           |  | - Time Measurement Chart|   |
| +------------------+  | - Sensor Status Charts  |   |
|                       | - Actuator Status Charts|   |
|                       +-------------------------+   |
+-----------------------------------------------------+
                          ^
                          |
                          v
+-----------------------------------------------------+
|                    Logic Layer                      |
| +------------------+  +-------------------------+   |
| | State Machine    |  |   Time Measurement     |   |
| | - State Transitions| | - t1 Measurement      |   |
| | - Sensor Updates |  | - t2 Measurement       |   |
| | - Actuator Control| | - Logic Expression Adj.|   |
| +------------------+  +-------------------------+   |
+-----------------------------------------------------+
                          ^
                          |
                          v
+-----------------------------------------------------+
|                 Simulation Layer                    |
| +------------------+  +-------------------------+   |
| | SimPy Real-time  |  |  Magazine Refill       |   |
| | Environment      |  |  Process               |   |
| | - Time Advancement| | - Monitor Magazine     |   |
| | - Event Handling |  | - Timed Refill         |   |
| | - Process Scheduling| | - Update System State|   |
| +------------------+  +-------------------------+   |
+-----------------------------------------------------+
```

## 10. System Configuration Parameters Table

| Parameter Name        | Default | Unit | Description                      |
|-----------------------|---------|------|----------------------------------|
| extend_time           | 2       | sec  | Cylinder extension/retraction time |
| move_time             | 3       | sec  | Manipulator movement time        |
| vacuum_time           | 2       | sec  | Vacuum suction cup action time   |
| workpiece_count       | 8       | pcs  | Initial workpiece count          |
| magazine_refill_time  | 10      | sec  | Magazine refill wait time        |
| animation_interval    | 500     | ms   | Chart refresh interval           |
| simulation_factor     | 1.0     | ratio| Simulation to real-time ratio    |

## 11. System State Table

| State # | State Name           | Sensor States                    | Actuator States                 |
|---------|----------------------|----------------------------------|--------------------------------|
| 0       | Idle                 | S1=T, S3=T, S4=T                 | Y1=F, Y2=F, Y3=F               |
| 1       | Extend Cylinder      | S1=F, S2=T                       | Y1=T, Y2=F, Y3=F               |
| 2       | Move to Magazine     | S4=F, S5=T                       | Y1=F, Y2=T, Y3=F               |
| 3       | Activate Vacuum      | S6=T                             | Y1=F, Y2=F, Y3=T               |
| 4       | Retract Cylinder     | S1=T, S2=F                       | Y1=F, Y2=F, Y3=T               |
| 5       | Return to Next Station| S4=T, S5=F                      | Y1=F, Y2=T, Y3=T               |
| 6       | Deactivate Vacuum    | S6=F                             | Y1=F, Y2=F, Y3=F               |
| 7       | Wait for Refill      | S1=T, S3=F, S6=F                 | Y1=F, Y2=F, Y3=F               |
| 8       | Wait After Refill    | S1=T, S3=T, S6=F                 | Y1=F, Y2=F, Y3=F               |

