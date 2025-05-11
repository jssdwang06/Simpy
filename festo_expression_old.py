import threading  # multi-threaded
import sys # exit
import simpy.rt  # real-time simulation
import matplotlib.pyplot as plt  # for plotting
from matplotlib.animation import FuncAnimation  # for animation

import tkinter as tk  # for GUI
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class FestoStation:
    def __init__(self, env):
        self.env = env
        # ── Time parameters ──
        self.extend_time = 2  # cylinder extend/retract time
        self.move_time = 3  # manipulator movement time
        self.vacuum_time = 2  # vacuum gripper action time

        # ── Workpiece & magazine flag ──
        self.workpiece_count = 8  # initial workpiece count
        self.S3 = True  # magazine non-empty
        self.k = False  # need refill

        # ── Position sensors ──
        self.S1 = True  # cylinder retracted
        self.S2 = False  # cylinder extended
        self.S4 = True  # manipulator at next station
        self.S5 = False  # manipulator at magazine
        self.S6 = False  # vacuum engaged

        # ── Actuator outputs ──
        self.Y1 = False  # cylinder control
        self.Y2 = False  # manipulator control
        self.Y3 = False  # vacuum control

        # ── FSM state & control events ──
        self.state = 0  # initial state
        self.emergency_flag = False  # emergency stop
        self.start_event = env.event()  # start event
        
        # ── Timing measurements ──
        self.cycle_start_time = 0  # to calculate t1 (cycle time)
        self.t1 = 0  # cycle time (full normal cycle)
        self.t2 = 0  # time refill
        self.magazine_refill_time = 10  # magazine refill wait time (default)
        # self.state1_start_time = 0  # to mark start of state 1 for t2 calculation
        self.t2_start_marker = 0  # to mark when we start measuring t2
        # self.refill_in_progress = False  # flag to track refill status
        self.cycle_blocked = False  # flag to block cycle when t2 > t1
        self.first_cycle = True  # flag for first cycle
        self.measuring_t2 = False  # flag to track if we're measuring t2

        # Histories for plotting
        self.time_history = []
        self.state_history = []
        self.workpiece_history = []
        self.sensor_history = {s: [] for s in ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'k']}
        self.act_history = {a: [] for a in ['Y1', 'Y2', 'Y3']}
        
        # New timing histories
        self.t1_history = []
        self.t2_history = []

        # Kick off process
        self.process = env.process(self.run())

    # Update logic expression
    def update_logic(self):
        # Based on the expression from the synthesized FSM
        self.k = not self.S3
        
        # Special case for initial cycle or when t1/t2 haven't been measured yet
        if self.first_cycle or self.t2 == 0:
            self.Y1 = (not self.S6)
            # Using default expression for first cycle
        elif self.t1 > self.t2:
            self.Y1 = (not self.S6)
            # Normal operation when t1 > t2
        else:
            # When t2 > t1, the operation is blocked by magazine refill
            self.Y1 = (not self.S6) and ((not self.k) or (not self.S4))

        self.Y2 = self.S2 or ((not self.S1) and (not self.S4))
        self.Y3 = self.S5 or (self.S1 and (not self.S4))

    def log(self, msg):  # formatted log output
        t = self.env.now
        # record history
        self.time_history.append(t)
        self.state_history.append(self.state)
        self.workpiece_history.append(self.workpiece_count)
        for s in self.sensor_history:    self.sensor_history[s].append(getattr(self, s))
        for a in self.act_history:       self.act_history[a].append(getattr(self, a))
        self.t1_history.append(self.t1)
        self.t2_history.append(self.t2)
        print(f"{t:6.1f} | WP={self.workpiece_count:2d} | t1={self.t1:.1f} | t2={self.t2:.1f} | {msg}")

    def trigger_start(self):
        if self.state == 0:
            try:
                self.start_event.succeed()
                print(">>> System start!")

            except RuntimeError:
                pass
        else:
            print(">>> Start ignored; system already running.")

    def trigger_emergency(self):
        # Only trigger once until reset
        if self.state not in (0, ) and not self.emergency_flag:
            print(">>> Emergency Stop triggered!")
            self.emergency_flag = True
            self.process.interrupt()

    def trigger_exit(self):
        print(">>> Exiting...")
        plt.close('all')
        sys.exit()

    def set_refill_time(self, new_time):
        """Allow changing magazine refill wait time during simulation"""
        self.magazine_refill_time = new_time
        print(f">>> Magazine refill wait time set to {self.magazine_refill_time:.1f}s")

    def run(self):
        try:
            # ── State 0: Idle ──
            self.state = 0
            self.S1, self.S3, self.S4 = True, True, True
            self.update_logic()
            self.log("State 0 ▶ Idle (awaiting Start)")
            yield self.start_event

            while True:
                # Check for emergency stop
                if self.emergency_flag:
                    raise simpy.Interrupt()

                # ── Begin normal cycle - record start time for t1 calculation ──
                self.cycle_start_time = self.env.now
                
                # ── State 1: Extend cylinder
                self.state = 1
                # self.state1_start_time = self.env.now  # Record start time for t2 calculation
                
                self.log("State 1 ▶ Cylinder extending")
                self.update_logic()                
                yield self.env.timeout(self.extend_time)
                self.S2, self.S1 = True, False
                self.update_logic()                

                # ── State 2: Move to magazine
                self.state = 2
                self.log("State 2 ▶ Manipulator moving to magazine")
                self.update_logic()
                yield self.env.timeout(self.move_time)
                self.S5, self.S4 = True, False
                self.update_logic()

                # ── State 3: Vacuum ON
                self.state = 3
                self.log("State 3 ▶ Vacuum ON")
                self.update_logic()
                yield self.env.timeout(self.vacuum_time)
                self.S6 = True
                self.update_logic()

                # ── State 4: Retract cylinder
                self.state = 4
                self.log("State 4 ▶ Cylinder retracting")
                self.update_logic()
                yield self.env.timeout(self.extend_time)
                self.S1, self.S2 = True, False
                self.update_logic()

                # Pick one workpiece
                self.workpiece_count -= 1
                self.S3 = (self.workpiece_count > 0)
                if not self.S3:
                    self.magazine_empty_time = self.env.now
                    self.log("Magazine became empty")
                self.update_logic()

                # If empty, handle magazine refill process
                if not self.S3:
                    # Start measuring t2 when magazine is empty
                    self.t2_start_marker = self.env.now
                    self.measuring_t2 = True
                    
                    # Calculate t1 (cycle time up to this point)
                    self.t1 = self.env.now - self.cycle_start_time
                    self.log(f"Cycle time t1 = {self.t1:.1f}s")
                    
                    # Turn off vacuum when entering state 7
                    self.state = 7
                    # self.refill_in_progress = True
                    self.log("State 7 ▶ Magazine empty, waiting refill")
                    self.update_logic()

                    # Wait for magazine refill
                    refill_start_time = self.env.now
                    while not self.S3:
                        yield self.env.timeout(1)
                    
                    # Reset state after refill
                    self.workpiece_count = 8  # refilled
                    self.S3 = True
                    self.S6 = False
                    self.update_logic()
                    self.state = 8
                    self.log("State 8 ▶ Refilled, after 3s restarting")
                    # self.refill_in_progress = False

                    # Wait 3 seconds in state 8 before transitioning
                    yield self.env.timeout(3)

                    # Transition to state 1 (cylinder extend)
                    self.state = 1
                    
                    # Calculate t2 when returning to state 1 after refill
                    if self.measuring_t2:
                        self.t2 = self.env.now - self.t2_start_marker
                        self.measuring_t2 = False
                        self.log(f"Calculated t2 = {self.t2:.1f}s (time from state 4 through refill back to state 1)")
                        # 10 + 3  (yield self.env.timeout(3))

                    self.update_logic()
                    yield self.env.timeout(self.extend_time)
                    self.S2, self.S1 = True, False
                    self.update_logic()
                    
                    # Check if t2 > t1 condition for future cycles
                    if self.t2 > self.t1:
                        # self.log("t2 > t1: Cycle beginning will be blocked until S3 is restored")
                        self.cycle_blocked = True
                    else:
                        # self.log("t1 > t2: Station will operate in normal cycle mode")
                        self.cycle_blocked = False
                    
                    # No longer the first cycle
                    self.first_cycle = False
                    continue

                # ── State 5: Return to next station
                self.state = 5
                self.log("State 5 ▶ Manipulator returning to next station")
                self.update_logic()
                yield self.env.timeout(self.move_time)
                self.S4, self.S5 = True, False
                self.update_logic()

                # ── State 6: Vacuum OFF
                self.state = 6
                self.log("State 6 ▶ Vacuum OFF")
                self.update_logic()
                yield self.env.timeout(self.vacuum_time) # delay time, 2s to state 1
                self.S6 = False
                self.update_logic()

                # Calculate full cycle time (t1)
                self.t1 = self.env.now - self.cycle_start_time
                self.log(f"Complete cycle time t1 = {self.t1:.1f}s")
                self.first_cycle = False  # No longer the first cycle
                
                # Compare t1 and t2 if t2 has been measured
                if self.t2 > 0:
                    if self.t2 > self.t1:
                        self.log(f"t2 ({self.t2:.1f}s) > t1 ({self.t1:.1f}s): Y1 = !S6 && (!k || !S4)")
                        self.cycle_blocked = True
                    else:
                        self.log(f"t1 ({self.t1:.1f}s) >= t2 ({self.t2:.1f}s): Y1 = !S6")
                        self.cycle_blocked = False

                # Loop back to State 1
                self.state = 1
                self.update_logic()
                
        except simpy.Interrupt:
            # Emergency-stop handling: only done once per emergency
            self.state = 0
            # turn everything off / state
            self.S1 = True; self.S2 = False
            self.S4 = True; self.S5 = False; self.S6 = False
            self.update_logic()
            self.log("Reset to State 0")
            self.emergency_flag = False
            self.start_event = self.env.event()  # reset start

            yield from self.run()


# Add workpieces - modified to implement t2 logic
def blank_generator(env, station):
    """Refill logic based on configurable magazine refill time."""
    while True:
        if not station.S3:
            # Wait exactly magazine_refill_time seconds (configurable)
            yield env.timeout(station.magazine_refill_time)
            
            # Refill the magazine
            station.S3 = True
            station.log(f">>> Magazine refilled after {station.magazine_refill_time:.1f}s")
        else:
            yield env.timeout(1)


def run_gui():
    # SimPy real-time environment
    env = simpy.rt.RealtimeEnvironment(factor=1.0, strict=True)
    station = FestoStation(env)
    # Start the refill process
    env.process(blank_generator(env, station))
    threading.Thread(target=lambda: env.run(), daemon=True).start()

    # Tkinter setup
    root = tk.Tk()
    root.title("Festo Station Simulator")
    root.protocol("WM_DELETE_WINDOW", station.trigger_exit)

    # Matplotlib embedding
    fig, axs = plt.subplots(8, 1, figsize=(6, 10), sharex=True, constrained_layout=True)
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

    # Animation update
    def update(frame):
        t = station.time_history
        if not t:
            return

        # ── 1) State transitions ──
        ax = axs[0]
        ax.cla()
        ax.step(t, station.state_history, where='post')
        ax.set_ylabel('State')
        ax.set_yticks(range(9))
        ax.set_yticklabels([str(i) for i in range(9)])
        ax.set_title('State transitions')

        # annotate current state at right of its axes
        ax.annotate(
            f"State: {station.state}",
            xy=(1.15, 0.65),
            xycoords=ax.transAxes,
            va='center',
            fontsize=12,
            color='tab:blue'
        )

        # Workpiece count subplot
        ax = axs[1]
        ax.cla()
        ax.step(t, station.workpiece_history, where='post')
        ax.set_ylabel('WP Count')
        ax.set_ylim(-0.1, 8.1)
        ax.set_yticks([0, 8])
        ax.set_yticklabels(['0', '8'])
        ax.set_title('Workpiece Count')

        # annotate current count at right of its axes
        ax.annotate(
            f"Workpieces: {station.workpiece_history[-1]}",
            xy=(1.12, 0.65),
            xycoords=ax.transAxes,
            va='center',
            fontsize=12,
            color='tab:green'
        )

        # Cycle time t1 and refill time t2 subplot
        ax = axs[2]
        ax.cla()
        ax.step(t, station.t1_history, where='post', label='t1', color='purple')
        ax.step(t, station.t2_history, where='post', label='t2', color='brown')
        ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1))
        ax.set_ylim(-0.1, 20.1)
        ax.set_yticks([0, 20])
        ax.set_yticklabels(['0', '20'])
        ax.set_ylabel('Time (s)')
        ax.set_title('Cycle time (t1) and Refill time (t2)')
        
        # Display current t1 vs t2 status
        current_t1 = station.t1_history[-1] if station.t1_history else 0
        current_t2 = station.t2_history[-1] if station.t2_history else 10
        condition = "t1 > t2" if current_t1 > current_t2 else "t2 > t1" if current_t2 > current_t1 else "t1 = t2"
        ax.annotate(
            f"{condition}",
            xy=(1.1, 0.65),
            xycoords=ax.transAxes,
            va='center',
            fontsize=12,
            color='black'
        )
        
        # Sensors subplot S1 S2
        ax = axs[3]
        ax.cla()
        ax.step(t, station.sensor_history['S1'], where='post', label='S1', color='red')
        ax.step(t, station.sensor_history['S2'], where='post', label='S2', color='blue')        
        ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1))
        ax.set_ylim(-0.1, 1.1)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['0', '1'])
        ax.set_ylabel('Status')
        ax.set_title('Cylinder status (Sensors S1 and S2)')

        # Sensors subplot S4 S5
        ax = axs[4]
        ax.cla()
        ax.step(t, station.sensor_history['S4'], where='post', label='S4', color='green')
        ax.step(t, station.sensor_history['S5'], where='post', label='S5', color='orange')        
        ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1))
        ax.set_ylim(-0.1, 1.1)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['0', '1'])
        ax.set_ylabel('Status')
        ax.set_title('Manipulator status (Sensors S4 and S5)')

        # Sensors subplot S6
        ax = axs[5]
        ax.cla()
        ax.step(t, station.sensor_history['S6'], where='post', label='S6', color='black')
        ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1))
        ax.set_ylim(-0.1, 1.1)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['0', '1'])
        ax.set_ylabel('Status')
        ax.set_title('Vacuum status (Sensor S6)')

        # Sensors S3 and k subplot
        ax = axs[6]
        ax.cla()
        ax.step(t, station.sensor_history['S3'], where='post', label='S3', color='gold')
        ax.step(t, station.sensor_history['k'], where='post', label='k', color='purple')
        ax.set_ylim(-0.1, 1.1)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['0', '1'])
        ax.set_ylabel('Status')
        ax.set_title('Magazine status (Sensors S3 and k)')
        ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1))

        # Actuators subplot
        ax = axs[7]
        ax.cla()
        for a, hist in station.act_history.items():
            ax.step(t, hist, where='post', label=a, linestyle=':', linewidth=2)
        ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1))
        ax.set_title('Actuators status (Y1, Y2, Y3)')
        ax.set_ylim(-0.1, 1.1)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['0', '1'])
        ax.set_ylabel('Status')
       
        canvas.draw_idle()

    ani = FuncAnimation(fig, update, interval=500, cache_frame_data=False)

    # Control Buttons
    btn_frame = tk.Frame(root)
    btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
    button_font = ('Arial', 12)
    
    # Top row of buttons
    top_btn_frame = tk.Frame(btn_frame)
    top_btn_frame.pack(side=tk.TOP, fill=tk.X)
    tk.Button(top_btn_frame, text="Start", command=station.trigger_start, font=button_font) \
        .pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5, pady=5)
    tk.Button(top_btn_frame, text="Emergency Stop", command=station.trigger_emergency, font=button_font) \
        .pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5, pady=5)
    tk.Button(top_btn_frame, text="Exit", command=station.trigger_exit, font=button_font) \
        .pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5, pady=5)
    
    root.mainloop()


if __name__ == "__main__":
    run_gui() 