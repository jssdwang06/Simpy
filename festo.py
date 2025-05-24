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
        self.P = False  # memory unit for empty magazine notification

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
        self.first_cycle = True  # flag for first cycle

        # Histories for plotting
        self.time_history = []
        self.state_history = []
        self.workpiece_history = []
        self.sensor_history = {s: [] for s in ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'k', 'P']}
        self.act_history = {a: [] for a in ['Y1', 'Y2', 'Y3']}

        # Kick off process
        self.process = env.process(self.run())

        self.time_tolerance = 0.1  # 允许0.1秒的误差范围
        self.last_logic_state = None  # 用于跟踪逻辑状态变化

    # Update logic expression
    def update_logic(self):
        self.k = not self.S3  # k is always the inverse of S3

        # Actuator Logic
        if self.state == 0:  # Idle State
            self.Y1 = False
            self.Y2 = False
            self.Y3 = False
        else: # Active States (1-6)
            # Y1 = S2 or ((not S6) and k)
            self.Y1 = self.S2 or ((not self.S6) and self.k)
            # Y2 = (not S1) and (not S4)
            self.Y2 = (not self.S1) and (not self.S4)
            # Y3 = (not S4) and (((not S1) and S5) or (S1 and (not S5)))
            self.Y3 = (not self.S4) and (((not self.S1) and self.S5) or (self.S1 and (not self.S5)))

    # Record the history during simulation and output information
    def log(self, msg):  # formatted log output
        t = self.env.now
        # Ensure k is always up to date with S3 before logging
        self.k = not self.S3

        # record history
        self.time_history.append(t)
        self.state_history.append(self.state)
        self.workpiece_history.append(self.workpiece_count)
        for s in self.sensor_history:    self.sensor_history[s].append(getattr(self, s))
        for a in self.act_history:       self.act_history[a].append(getattr(self, a))
        print(f"{t:6.1f} | WP={self.workpiece_count:2d} | {msg}")

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
            self.S2 = False
            self.S5 = False
            self.S6 = False
            self.k = not self.S3
            # P signal remains as initialized (False for full magazine)
            self.cycle_start_time = 0
            self.update_logic()
            self.log("State 0 ▶ Idle (awaiting Start)")
            yield self.start_event

            while True:
                if self.emergency_flag:
                    raise simpy.Interrupt()
                self.k = not self.S3
                if not self.S3:
                    # self.log("Magazine empty, K signal activated, waiting for manual refill")
                    while not self.S3:
                        yield self.env.timeout(0.1)
                        self.k = not self.S3
                        self.update_logic()
                    self.k = not self.S3
                    self.update_logic()
                    self.cycle_start_time = 0

                    # return to state 0, waiting for manual start
                    self.state = 0
                    self.S1, self.S3, self.S4 = True, True, True
                    self.S2 = False
                    self.S5 = False
                    self.S6 = False
                    self.start_event = self.env.event()
                    self.update_logic()
                    self.log("State 0 ▶ Idle (awaiting Start)")
                    yield self.start_event
                    continue
                if self.cycle_start_time == 0:
                    self.cycle_start_time = self.env.now

                # ── State 1: Extend cylinder ──
                self.state = 1
                self.S1 = False
                self.S2 = False
                self.S3 = False
                self.update_logic()
                self.log("State 1 ▶ Cylinder extending")
                yield self.env.timeout(self.extend_time)

                # ── State 2: Move to magazine ──
                self.state = 2
                self.S2 = True
                self.S4 = False
                self.update_logic()
                self.log("State 2 ▶ Manipulator moving to magazine")
                yield self.env.timeout(self.move_time)
                self.S5 = True
                self.update_logic()

                # ── State 3: Vacuum ON ──
                self.state = 3
                self.S6 = True
                self.update_logic()
                self.log("State 3 ▶ Vacuum ON")
                yield self.env.timeout(self.vacuum_time)

                # ── State 4: Retract cylinder ──
                self.state = 4
                self.S1 = False
                self.S2 = False
                self.S3 = False
                self.S4 = False
                self.update_logic()
                self.log("State 4 ▶ Cylinder retracting")
                yield self.env.timeout(self.extend_time)

                # 工件在气缸收回后因重力掉落
                if self.workpiece_count == 1:  # 弹出前是最后一个工件
                    self.P = True  # 置位P信号
                    self.log("Last workpiece ejected - P signal activated")

                self.workpiece_count -= 1
                self.S3 = (self.workpiece_count > 0)
                self.k = not self.S3
                self.update_logic()
                # self.log(f"Workpiece ejected by gravity - Count: {self.workpiece_count}")

                # 检查料仓是否为空，如果为空则完成当前循环后停止
                if not self.S3:
                    # ── State 5: Manipulator returning to next station ──
                    self.state = 5
                    self.S1 = True
                    self.S5 = False
                    self.update_logic()
                    self.log("State 5 ▶ Manipulator returning to next station")
                    yield self.env.timeout(self.move_time)
                    self.S4 = True
                    self.update_logic()

                    # ── State 6: Vacuum OFF ──
                    self.state = 6
                    self.S6 = False
                    self.S5 = False
                    self.update_logic()
                    self.log("State 6 ▶ Vacuum OFF")
                    yield self.env.timeout(self.vacuum_time)
                    self.update_logic()

                    # 料仓空，跳出循环等待补料
                    self.log("Magazine empty, waiting for manual refill")
                    continue

                # ── State 5: Manipulator returning to next station ──
                self.state = 5
                self.S1 = True
                # S3 should already be correctly set based on workpiece_count in State 4
                self.S5 = False
                self.update_logic()
                self.log("State 5 ▶ Manipulator returning to next station")
                yield self.env.timeout(self.move_time)
                self.S4 = True
                self.update_logic()

                # ── State 6: Vacuum OFF ──
                self.state = 6
                self.S6 = False
                self.S5 = False
                self.update_logic()
                self.log("State 6 ▶ Vacuum OFF")
                yield self.env.timeout(self.vacuum_time)
                self.update_logic()

                # Reset cycle start time for next cycle
                self.cycle_start_time = self.env.now

        except simpy.Interrupt:
            self.state = 0
            self.S1, self.S3, self.S4 = True, True, True
            self.S2 = False
            self.S5 = False
            self.S6 = False
            self.k = False
            self.P = False  # Reset P signal on emergency stop
            self.update_logic()
            self.log("Reset to State 0")
            self.emergency_flag = False
            self.start_event = self.env.event()
            self.cycle_start_time = 0
            yield from self.run()

    def manual_refill(self, amount):
        """Handle manual refill request from control panel"""
        # Check if magazine is empty (S3 is False)
        if self.S3:
            self.log("Manual refill only available when magazine is empty")
            return
        if amount > 0 and amount <= self.max_workpiece_capacity:
            self.manual_refill_flag = True
            self.manual_refill_amount = amount
            # Update workpiece count and magazine status
            self.workpiece_count = amount
            self.S3 = True
            self.k = not self.S3  # Immediately update k when S3 changes

            # Reset P signal when refill is completed
            if self.P:
                self.P = False
                self.log("P signal reset - Magazine refilled")

            self.log(f">>> Manual refill completed: {amount} workpieces added")
            # 回到Idle，等待人工再次启动
            self.state = 0
            self.S1, self.S3, self.S4 = True, True, True
            self.S2 = False
            self.S5 = False
            self.S6 = False
            self.start_event = self.env.event()
            self.update_logic()
            # Note: State 0 log will be output by the main loop


# Add workpieces
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
    fig, axs = plt.subplots(7, 1, figsize=(6, 12), sharex=True, constrained_layout=True)
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

        # Sensors subplot S1 S2
        ax = axs[2]
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
        ax = axs[3]
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
        ax = axs[4]
        ax.cla()
        ax.step(t, station.sensor_history['S6'], where='post', label='S6', color='black')
        ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1))
        ax.set_ylim(-0.1, 1.1)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['0', '1'])
        ax.set_ylabel('Status')
        ax.set_title('Vacuum status (Sensor S6)')

        # Sensors S3, k and P subplot
        ax = axs[5]
        ax.cla()
        ax.step(t, station.sensor_history['S3'], where='post', label='S3', color='gold')
        ax.step(t, station.sensor_history['k'], where='post', label='k', color='purple')
        ax.step(t, station.sensor_history['P'], where='post', label='P', color='red', linestyle='--', linewidth=2)
        ax.set_ylim(-0.1, 1.1)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['0', '1'])
        ax.set_ylabel('Status')
        ax.set_title('Magazine status (Sensors S3, k and P)')
        ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1))

        # Actuators subplot
        ax = axs[6]
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
        self.root.geometry("600x500")

        # Style configuration
        self.style_config()

        # Indicator storage
        self.sensor_indicators = {}
        self.actuator_indicators = {}
        self.workpiece_label = None # Initialize
        self.state_label = None     # Initialize

        # Create frames
        self.create_control_frame()
        self.create_workpiece_frame()
        self.create_combined_status_frame() # Renamed and will be modified

        # Start the status update loop
        self.root.after(500, self.update_status)

    def style_config(self):
        # Configure style
        self.root.configure(bg='#f0f0f0')
        self.button_style = {
            'font': ('Arial', 14), # Further increased button font size
            'width': 15,
            'pady': 5,
            'bd': 2,
            'relief': 'raised'
        }
        self.label_font = ('Arial', 12) # Further increased standard label font
        self.labelframe_font = ('Arial', 13, 'bold') # Further increased LabelFrame title font

    def create_control_frame(self):
        # Control buttons frame
        control_frame = tk.LabelFrame(self.root, text="Control", padx=10, pady=5, bg='#f0f0f0', font=self.labelframe_font)
        control_frame.pack(fill=tk.X, padx=10, pady=5)

        # Start button
        tk.Button(control_frame,
                 text="Start",
                 command=self.station.trigger_start,
                 bg='#90EE90',
                 **self.button_style).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5, pady=5)

        # Emergency Stop button
        tk.Button(control_frame,
                 text="Emergency Stop",
                 command=self.station.trigger_emergency,
                 bg='#FFB6C1',
                 **self.button_style).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5, pady=5)

        # Exit button
        tk.Button(control_frame,
                 text="Exit",
                 command=self.station.trigger_exit,
                 bg='#D3D3D3',
                 **self.button_style).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5, pady=5)

    def create_workpiece_frame(self):
        # Workpiece control frame
        workpiece_frame = tk.LabelFrame(self.root, text="Workpiece Control", padx=10, pady=5, bg='#f0f0f0', font=self.labelframe_font)
        workpiece_frame.pack(fill=tk.X, padx=10, pady=5)

        # Inner frame for grid layout to align with status frame
        inner_wp_frame = tk.Frame(workpiece_frame, bg='#f0f0f0')
        inner_wp_frame.pack(pady=5, fill=tk.X)

        # Refill amount selection - using grid layout for alignment
        tk.Label(inner_wp_frame,
                text="Refill Amount:",
                bg='#f0f0f0',
                font=self.label_font).grid(row=0, column=0, sticky='w')

        self.refill_var = tk.StringVar(value="8")
        refill_spinbox = tk.Spinbox(inner_wp_frame,
                                  from_=1,
                                  to=8,
                                  textvariable=self.refill_var,
                                  width=5,
                                  font=self.label_font)
        refill_spinbox.grid(row=0, column=1, sticky='w', padx=5)

        # Manual refill button
        tk.Button(inner_wp_frame,
                 text="Manual Refill",
                 command=self.manual_refill,
                 bg='#87CEEB',
                 **self.button_style).grid(row=0, column=2, sticky='ew', padx=(10,0))

        # Configure column weights for proper expansion
        inner_wp_frame.columnconfigure(2, weight=1)

    def create_combined_status_frame(self): # Was create_io_status_frame
        combined_status_frame = tk.LabelFrame(self.root, text="Status", padx=10, pady=10, bg='#f0f0f0', font=self.labelframe_font) # Changed title
        combined_status_frame.pack(fill=tk.X, padx=10, pady=5)

        # --- General Status (Workpieces, State) ---
        general_status_frame = tk.Frame(combined_status_frame, bg='#f0f0f0')
        general_status_frame.pack(fill=tk.X, pady=(0,10))

        tk.Label(general_status_frame, text="Current Workpieces:", font=self.label_font, bg='#f0f0f0').grid(row=0, column=0, sticky='w')
        self.workpiece_label = tk.Label(general_status_frame, text="N/A", font=self.label_font, bg='#f0f0f0')
        self.workpiece_label.grid(row=0, column=1, sticky='w', padx=5)

        tk.Label(general_status_frame, text="Current State:", font=self.label_font, bg='#f0f0f0').grid(row=1, column=0, sticky='w')
        self.state_label = tk.Label(general_status_frame, text="N/A", font=self.label_font, bg='#f0f0f0')
        self.state_label.grid(row=1, column=1, sticky='w', padx=5)

        # --- Sensors ---
        sensors_frame = tk.Frame(combined_status_frame, bg='#f0f0f0') # Changed parent to combined_status_frame
        sensors_frame.pack(fill=tk.X)

        tk.Label(sensors_frame, text="Sensors:", font=self.labelframe_font, bg='#f0f0f0').grid(row=0, column=0, columnspan=8, sticky='w', pady=(0,5))

        sensor_list_row1 = ['S1', 'S2', 'S3', 'S4']
        sensor_list_row2 = ['S5', 'S6', 'k', 'P']

        for i, s_name in enumerate(sensor_list_row1):
            tk.Label(sensors_frame, text=f"{s_name}:", font=self.label_font, bg='#f0f0f0').grid(row=1, column=i*2, sticky='e', padx=(5,0))
            indicator = tk.Label(sensors_frame, text="  ", bg="red", width=2, relief="sunken", borderwidth=1)
            indicator.grid(row=1, column=i*2+1, sticky='w', padx=(2,10))
            self.sensor_indicators[s_name] = indicator

        for i, s_name in enumerate(sensor_list_row2):
            tk.Label(sensors_frame, text=f"{s_name}:", font=self.label_font, bg='#f0f0f0').grid(row=2, column=i*2, sticky='e', padx=(5,0), pady=(5,0))
            indicator = tk.Label(sensors_frame, text="  ", bg="red", width=2, relief="sunken", borderwidth=1)
            indicator.grid(row=2, column=i*2+1, sticky='w', padx=(2,10), pady=(5,0))
            self.sensor_indicators[s_name] = indicator

        # --- Actuators ---
        actuators_frame = tk.Frame(combined_status_frame, bg='#f0f0f0')
        actuators_frame.pack(fill=tk.X, pady=(10,0))

        tk.Label(actuators_frame, text="Actuators:", font=self.labelframe_font, bg='#f0f0f0').grid(row=0, column=0, columnspan=6, sticky='w', pady=(0,5))

        actuator_list = ['Y1', 'Y2', 'Y3']
        for i, a_name in enumerate(actuator_list):
            tk.Label(actuators_frame, text=f"{a_name}:", font=self.label_font, bg='#f0f0f0').grid(row=1, column=i*2, sticky='e', padx=(5,0))
            indicator = tk.Label(actuators_frame, text="  ", bg="red", width=2, relief="sunken", borderwidth=1)
            indicator.grid(row=1, column=i*2+1, sticky='w', padx=(2,10))
            self.actuator_indicators[a_name] = indicator

    def manual_refill(self):
        try:
            refill_amount = int(self.refill_var.get())
            if self.station.S3:  # Changed condition to check S3 directly
                tk.messagebox.showwarning("Invalid State", "Manual refill is only available when magazine is empty")
                return

            if 1 <= refill_amount <= 8:
                self.station.manual_refill(refill_amount)
            else:
                tk.messagebox.showwarning("Invalid Input", "Please enter a number between 1 and 8")
        except ValueError:
            tk.messagebox.showwarning("Invalid Input", "Please enter a valid number")

    def update_status(self):
        # Update workpiece count and state
        self.workpiece_label.config(text=f"{self.station.workpiece_count}")
        self.state_label.config(text=f"{self.station.state}")

        # Update sensor indicators
        for s_name, indicator_label in self.sensor_indicators.items():
            status = getattr(self.station, s_name, False) # Default to False if attr not found
            color = "green" if status else "red"
            indicator_label.config(bg=color)

        # Update actuator indicators
        for a_name, indicator_label in self.actuator_indicators.items():
            status = getattr(self.station, a_name, False) # Default to False if attr not found
            color = "green" if status else "red"
            indicator_label.config(bg=color)

        # Schedule next update
        self.root.after(100, self.update_status)


if __name__ == "__main__":
    run_gui()

