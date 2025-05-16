import threading # multi-threaded
import sys # exit
import simpy # real-time simulation
from simpy.rt import RealtimeEnvironment # real-time simulation, 1s simulation = 1s real-time, if the simulation runs faster than real-time, an exception is raised
import matplotlib.pyplot as plt  # for plotting
from matplotlib.animation import FuncAnimation  # for animation

import tkinter as tk  # for GUI
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class FestoStation:
    def __init__(self, env):
        self.env = env
        # ── Time parameters ──
        self.extend_time = 2   # cylinder extend/retract time
        self.move_time = 3     # manipulator movement time
        self.vacuum_time = 2   # vacuum gripper action time
        self.per_workpiece_refill_time = 2  # time needed to refill one workpiece
        self.max_workpiece_capacity = 8  # maximum magazine capacity

        # ── Workpiece & magazine flag ──
        self.workpiece_count = 8  # initial workpiece count
        self.refill_workpiece_count = 0  # number of workpieces to be refilled
        self.manual_refill_flag = False  # flag for manual refill
        self.manual_refill_amount = 0  # amount for manual refill
        self.S3 = True  # magazine non-empty
        self.k = False  # need refill

        # ── Position sensors ──
        self.S1 = True   # cylinder retracted
        self.S2 = False  # cylinder extended
        self.S4 = True   # manipulator at next station
        self.S5 = False  # manipulator at magazine
        self.S6 = False  # vacuum engaged

        # ── Actuator outputs ──
        self.Y1 = False  # cylinder control
        self.Y2 = False  # manipulator control
        self.Y3 = False  # vacuum control

        # ── FSM state & control events ──
        self.state = 0  # initial state
        self.emergency_flag = False     # emergency stop
        self.start_event = env.event()  # start event
        
        # ── Timing measurements ──
        self.cycle_start_time = 0  # Tracks when a cycle begins to calculate cycle time
        self.t1 = 0  # cycle time (full normal cycle)
        self.t2 = 0  # store the magazine refill time
        self.t2_start_marker = 0  # to mark when we start measuring t2
        self.first_cycle = True  # flag for first cycle
        self.cycle_blocked = False  # flag to block cycle when t2 > t1
        self.measuring_t2 = False  # flag to track if we're measuring t2

        # Histories for plotting
        self.time_history = []
        self.state_history = []
        self.workpiece_history = []
        self.sensor_history = {s: [] for s in ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'k']}
        self.act_history = {a: [] for a in ['Y1', 'Y2', 'Y3']}
        
        # New timing cycle histories
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
            # Using default expression for first cycle
            self.Y1 = (not self.S6)
        elif self.t1 > self.t2:
            self.Y1 = (not self.S6)
            # Normal operation when t1 > t2
        else:
            # When t2 > t1, the operation is blocked by magazine refill
            self.Y1 = (not self.S6) and ((not self.k) or (not self.S4))

        self.Y2 = self.S2 or ((not self.S1) and (not self.S4))
        self.Y3 = self.S5 or (self.S1 and (not self.S4))

    # Record the history during simulation and output information
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

    # Start the simulation
    def trigger_start(self):
        if self.state == 0:
            try:
                self.start_event.succeed()
                print(">>> System start!")

            except RuntimeError:
                pass
        else:
            print(">>> Start ignored; system already running.")

    # Emergency stop
    def trigger_emergency(self):
        # Only trigger once until reset
        if self.state != 0 and not self.emergency_flag:
            print(">>> Emergency Stop triggered!")
            self.emergency_flag = True
            self.process.interrupt()

    def trigger_exit(self):
        print(">>> Exiting...")
        plt.close('all')
        sys.exit()

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
                
                # check here workpiece has or not
                if not self.S3:  # if not
                    self.log("Magazine empty at startup, waiting for refill")

                    # start measuring t2
                    self.t2_start_marker = self.env.now
                    self.measuring_t2 = True

                    self.state = 7
                    self.log("State 7 ▶ Magazine empty, waiting refill")
                    self.update_logic()

                    # Wait for manual refill
                    while not self.S3:
                        yield self.env.timeout(1)

                    # wait for 3s to start cycle
                    self.state = 8
                    self.log("State 8 ▶ Refilled, after 3s starting cycle")
                    yield self.env.timeout(3)
                
                # ── Begin normal cycle - record start time for t1 calculation ──
                self.cycle_start_time = self.env.now
                
                # ── State 1: Extend cylinder
                self.state = 1
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
                    self.t2_start_marker = self.env.now  # 开始测量t2
                    self.measuring_t2 = True
                    self.log("Magazine became empty, starting t2 measurement")
                self.update_logic()

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

                # Calculate full cycle time (t1) - only on first complete cycle
                if self.first_cycle:
                    self.t1 = self.env.now - self.cycle_start_time
                    self.log(f"First complete cycle time t1 = {self.t1:.1f}s")
                    self.first_cycle = False  # No longer the first cycle
                
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

    def manual_refill(self, amount):
        """Handle manual refill request from control panel"""
        # Only allow manual refill in state 7 (waiting for refill)
        if self.state != 7:
            self.log("Manual refill only available when magazine is empty (State 7)")
            return
            
        if amount > 0 and amount <= self.max_workpiece_capacity:
            self.manual_refill_flag = True
            self.manual_refill_amount = amount
            
            # Calculate refill time
            refill_time = amount * self.per_workpiece_refill_time
            
            # Update workpiece count and magazine status
            self.workpiece_count = amount
            self.S3 = True
            self.k = not self.S3  # Update k flag
            
            # If we're measuring t2, update it
            if self.measuring_t2:
                self.t2 = refill_time
                self.measuring_t2 = False
                self.log(f"Manual refill: t2 = {refill_time:.1f}s for {amount} workpieces")
            
            self.log(f">>> Manual refill completed: {amount} workpieces added")
            
            # Update logic after refill
            self.update_logic()


# Add workpieces - modified to implement t2 logic
def blank_generator(env, station):
    """Refill logic based on number of workpieces needed."""
    while True:
        # Only check for empty magazine, don't do automatic refill
        if not station.S3 and not station.manual_refill_flag:
            yield env.timeout(1)  # Just wait for manual refill
        else:
            yield env.timeout(1)
            # Reset manual refill flag after one cycle
            station.manual_refill_flag = False


def run_gui():
    # SimPy real-time environment
    env = simpy.rt.RealtimeEnvironment(factor=1.0, strict=True)
    station = FestoStation(env)
    # Start the refill process
    env.process(blank_generator(env, station))
    threading.Thread(target=lambda: env.run(), daemon=True).start()

    # Tkinter setup for main window
    root = tk.Tk()
    root.title("Festo Station Simulator")
    root.protocol("WM_DELETE_WINDOW", station.trigger_exit)

    # Create control panel
    control_panel = ControlPanel(station)

    # Matplotlib embedding
    fig, axs = plt.subplots(8, 1, figsize=(6, 12), sharex=True, constrained_layout=True)
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
    
    root.mainloop()


class ControlPanel:
    def __init__(self, station):
        self.station = station
        self.root = tk.Toplevel()
        self.root.title("Festo Station Control Panel")
        self.root.geometry("300x400")
        
        # Style configuration
        self.style_config()
        
        # Create frames
        self.create_control_frame()
        self.create_workpiece_frame()
        self.create_status_frame()
        
    def style_config(self):
        # Configure style
        self.root.configure(bg='#f0f0f0')
        self.button_style = {
            'font': ('Arial', 12),
            'width': 15,
            'pady': 5,
            'bd': 2,
            'relief': 'raised'
        }
        
    def create_control_frame(self):
        # Control buttons frame
        control_frame = tk.LabelFrame(self.root, text="Control", padx=10, pady=5, bg='#f0f0f0')
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Start button
        tk.Button(control_frame, 
                 text="Start",
                 command=self.station.trigger_start,
                 bg='#90EE90',
                 **self.button_style).pack(pady=5)
        
        # Emergency Stop button
        tk.Button(control_frame,
                 text="Emergency Stop",
                 command=self.station.trigger_emergency,
                 bg='#FFB6C1',
                 **self.button_style).pack(pady=5)
        
        # Exit button
        tk.Button(control_frame,
                 text="Exit",
                 command=self.station.trigger_exit,
                 bg='#D3D3D3',
                 **self.button_style).pack(pady=5)
    
    def create_workpiece_frame(self):
        # Workpiece control frame
        workpiece_frame = tk.LabelFrame(self.root, text="Workpiece Control", padx=10, pady=5, bg='#f0f0f0')
        workpiece_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Refill amount selection
        tk.Label(workpiece_frame, 
                text="Refill Amount:",
                bg='#f0f0f0',
                font=('Arial', 10)).pack(pady=2)
        
        self.refill_var = tk.StringVar(value="8")
        refill_spinbox = tk.Spinbox(workpiece_frame,
                                  from_=1,
                                  to=8,
                                  textvariable=self.refill_var,
                                  width=10,
                                  font=('Arial', 12))
        refill_spinbox.pack(pady=5)
        
        # Manual refill button
        tk.Button(workpiece_frame,
                 text="Manual Refill",
                 command=self.manual_refill,
                 bg='#87CEEB',
                 **self.button_style).pack(pady=5)
    
    def create_status_frame(self):
        # Status frame
        status_frame = tk.LabelFrame(self.root, text="Status", padx=10, pady=5, bg='#f0f0f0')
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Current workpiece count
        self.workpiece_label = tk.Label(status_frame,
                                      text=f"Current Workpieces: {self.station.workpiece_count}",
                                      bg='#f0f0f0',
                                      font=('Arial', 10))
        self.workpiece_label.pack(pady=2)
        
        # Update status periodically
        self.root.after(500, self.update_status)
    
    def manual_refill(self):
        try:
            refill_amount = int(self.refill_var.get())
            if self.station.state != 7:
                tk.messagebox.showwarning("Invalid State", "Manual refill is only available when magazine is empty (State 7)")
                return
                
            if 1 <= refill_amount <= 8:
                self.station.manual_refill(refill_amount)
            else:
                tk.messagebox.showwarning("Invalid Input", "Please enter a number between 1 and 8")
        except ValueError:
            tk.messagebox.showwarning("Invalid Input", "Please enter a valid number")
    
    def update_status(self):
        # Update workpiece count and state
        self.workpiece_label.config(
            text=f"Current Workpieces: {self.station.workpiece_count}\nCurrent State: {self.station.state}"
        )
        # Schedule next update
        self.root.after(500, self.update_status)


if __name__ == "__main__":
    run_gui()
    
