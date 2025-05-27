import threading # multi-threaded
import sys # exit
import simpy # real-time simulation
from simpy.rt import RealtimeEnvironment # real-time simulation, 1s simulation = 1s real-time, if the simulation runs faster than real-time, an exception is raised
import matplotlib.pyplot as plt  # for plotting
from matplotlib.animation import FuncAnimation  # for animation

import tkinter as tk  # for GUI
import tkinter.messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import json
import datetime


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

        # ── Workpiece color management ──
        self.available_colors = ['black', 'red', 'silver']  # Available workpiece colors
        self.workpiece_colors = {
            'black': 3,   # Initial count for black workpieces
            'red': 3,     # Initial count for red workpieces
            'silver': 2   # Initial count for silver workpieces
        }
        self.current_workpiece_color = None  # Color of current workpiece being processed

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

        # ── Performance metrics ──
        self.total_workpieces_processed = 0  # Total workpieces processed
        self.total_cycles_completed = 0  # Total complete cycles
        self.simulation_start_time = 0  # When simulation actually started
        self.total_downtime = 0  # Total time waiting for refill
        self.downtime_start = 0  # When current downtime started
        self.cycle_times = []  # List of individual cycle times
        self.refill_times = []  # List of refill durations
        self.state_durations = {i: 0 for i in range(7)}  # Time spent in each state
        self.last_state_change_time = 0  # Track state change timing

        # ── Color processing statistics ──
        self.processed_colors = {
            'black': 0,   # Count of processed black workpieces
            'red': 0,     # Count of processed red workpieces
            'silver': 0   # Count of processed silver workpieces
        }

        # ── Refill control ──
        self.refill_in_progress = False  # Prevent multiple refill operations
        self.pending_refill_timer = None  # Track active refill timer

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

    def get_next_workpiece_color(self):
        """Get the color of the next workpiece to be processed"""
        # Find the first available color with count > 0
        for color in self.available_colors:
            if self.workpiece_colors[color] > 0:
                return color
        return None

    def eject_workpiece(self):
        """Eject a workpiece and update color inventory"""
        next_color = self.get_next_workpiece_color()
        if next_color:
            self.current_workpiece_color = next_color
            self.workpiece_colors[next_color] -= 1
            self.workpiece_count -= 1
            self.total_workpieces_processed += 1
            # Update color processing statistics
            self.processed_colors[next_color] += 1
            return True
        return False

    def get_color_summary(self):
        """Get a summary string of current color inventory"""
        summary = []
        for color in self.available_colors:
            count = self.workpiece_colors[color]
            summary.append(f"{color}:{count}")
        return " | ".join(summary)

    def update_state_duration(self, new_state):
        """Update the duration spent in the current state"""
        current_time = self.env.now
        if self.last_state_change_time > 0:
            duration = current_time - self.last_state_change_time
            if self.state in self.state_durations:
                self.state_durations[self.state] += duration
        self.last_state_change_time = current_time

    def get_performance_metrics(self):
        """Calculate and return current performance metrics"""
        current_time = self.env.now

        # Calculate total simulation time
        total_sim_time = current_time - self.simulation_start_time if self.simulation_start_time > 0 else 0

        # Calculate throughput (workpieces per hour)
        throughput = (self.total_workpieces_processed / total_sim_time * 3600) if total_sim_time > 0 else 0

        # Calculate average cycle time
        avg_cycle_time = sum(self.cycle_times) / len(self.cycle_times) if self.cycle_times else 0

        # Calculate equipment utilization (active time / total time)
        active_time = total_sim_time - self.total_downtime
        utilization = (active_time / total_sim_time * 100) if total_sim_time > 0 else 0

        # Calculate average refill time
        avg_refill_time = sum(self.refill_times) / len(self.refill_times) if self.refill_times else 0

        return {
            'total_sim_time': total_sim_time,
            'total_workpieces': self.total_workpieces_processed,
            'total_cycles': self.total_cycles_completed,
            'throughput': throughput,
            'avg_cycle_time': avg_cycle_time,
            'utilization': utilization,
            'total_downtime': self.total_downtime,
            'avg_refill_time': avg_refill_time,
            'refill_count': len(self.refill_times),
            'state_durations': self.state_durations.copy(),
            'processed_colors': self.processed_colors.copy()
        }

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

        # Include color information in log output
        color_info = self.get_color_summary()
        print(f"{t:6.1f} | WP={self.workpiece_count:2d} | [{color_info}] | {msg}")

    # Start the simulation
    def trigger_start(self):
        if self.state == 0:
            try:
                self.start_event.succeed()
                # Initialize simulation start time when first started
                if self.simulation_start_time == 0:
                    self.simulation_start_time = self.env.now
                    self.last_state_change_time = self.env.now
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
            self.update_state_duration(0)
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
                    # Start tracking downtime
                    if self.downtime_start == 0:
                        self.downtime_start = self.env.now
                    # self.log("Magazine empty, K signal activated, waiting for manual refill")
                    while not self.S3:
                        yield self.env.timeout(0.5)  # Reduced frequency to minimize time drift
                        self.k = not self.S3
                        self.update_logic()

                    # End tracking downtime
                    if self.downtime_start > 0:
                        downtime_duration = self.env.now - self.downtime_start
                        self.total_downtime += downtime_duration
                        self.refill_times.append(downtime_duration)
                        self.downtime_start = 0

                    self.k = not self.S3
                    self.update_logic()
                    self.cycle_start_time = 0

                    # return to state 0, waiting for manual start
                    self.update_state_duration(0)
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
                self.update_state_duration(1)
                self.state = 1
                self.S1 = False
                self.S2 = False
                self.S3 = False
                self.update_logic()
                self.log("State 1 ▶ Cylinder extending")
                yield self.env.timeout(self.extend_time)

                # ── State 2: Move to magazine ──
                self.update_state_duration(2)
                self.state = 2
                self.S2 = True
                self.S4 = False
                self.update_logic()
                self.log("State 2 ▶ Manipulator moving to magazine")
                yield self.env.timeout(self.move_time)
                self.S5 = True
                self.update_logic()

                # ── State 3: Vacuum ON ──
                self.update_state_duration(3)
                self.state = 3
                self.S6 = True
                self.update_logic()
                self.log("State 3 ▶ Vacuum ON")
                yield self.env.timeout(self.vacuum_time)

                # ── State 4: Retract cylinder ──
                self.update_state_duration(4)
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

                # Use new color-aware workpiece ejection
                if self.eject_workpiece():
                    color = self.current_workpiece_color
                    self.log(f"Workpiece ejected by gravity - Color: {color}")
                else:
                    self.log("No workpieces available to eject")

                self.S3 = (self.workpiece_count > 0)
                self.k = not self.S3
                self.update_logic()

                # 检查料仓是否为空，如果为空则完成当前循环后停止
                if not self.S3:
                    # ── State 5: Manipulator returning to next station ──
                    self.update_state_duration(5)
                    self.state = 5
                    self.S1 = True
                    self.S5 = False
                    self.update_logic()
                    self.log("State 5 ▶ Manipulator returning to next station")
                    yield self.env.timeout(self.move_time)
                    self.S4 = True
                    self.update_logic()

                    # ── State 6: Vacuum OFF ──
                    self.update_state_duration(6)
                    self.state = 6
                    self.S6 = False
                    self.S5 = False
                    self.update_logic()
                    self.log("State 6 ▶ Vacuum OFF")
                    yield self.env.timeout(self.vacuum_time)
                    self.update_logic()

                    # Complete cycle and record cycle time
                    if self.cycle_start_time > 0:
                        cycle_time = self.env.now - self.cycle_start_time
                        self.cycle_times.append(cycle_time)
                        self.total_cycles_completed += 1

                    # 料仓空，跳出循环等待补料
                    self.log("Magazine empty, waiting for manual refill")
                    continue

                # ── State 5: Manipulator returning to next station ──
                self.update_state_duration(5)
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
                self.update_state_duration(6)
                self.state = 6
                self.S6 = False
                self.S5 = False
                self.update_logic()
                self.log("State 6 ▶ Vacuum OFF")
                yield self.env.timeout(self.vacuum_time)
                self.update_logic()

                # Complete cycle and record cycle time
                if self.cycle_start_time > 0:
                    cycle_time = self.env.now - self.cycle_start_time
                    self.cycle_times.append(cycle_time)
                    self.total_cycles_completed += 1

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

    def manual_refill(self, amount, color_distribution=None):
        """Handle manual refill request from control panel"""
        # Check if magazine is empty (S3 is False)
        if self.S3:
            self.log("Manual refill only available when magazine is empty")
            return

        # Check if system is in a valid state for refill
        # Allow refill in State 0 (idle) or State 6 (after last workpiece ejected)
        if self.state != 0 and not (self.state == 6 and not self.S3):
            self.log(f"Manual refill only available when system is idle (State 0) or after last workpiece ejected (State 6 with empty magazine)")
            return

        # Check if refill is already in progress
        if self.refill_in_progress:
            self.log("Refill already in progress, please wait")
            return

        if amount > 0 and amount <= self.max_workpiece_capacity:
            self.refill_in_progress = True
            self.manual_refill_flag = True
            self.manual_refill_amount = amount

            # Record operator response time (time from empty to manual refill click)
            if self.downtime_start > 0:
                operator_response_time = self.env.now - self.downtime_start
                # Round to nearest 0.1s for cleaner display
                rounded_response_time = round(operator_response_time, 1)
                self.log(f"Operator response time: {rounded_response_time:.1f}s")

            # Handle color distribution
            if color_distribution is None:
                # Default distribution: try to balance colors
                self._distribute_colors_evenly(amount)
            else:
                # Use provided color distribution
                self._set_color_distribution(color_distribution)

            # Simulate physical refill time (realistic industrial process)
            physical_refill_time = amount * self.per_workpiece_refill_time
            self.log(f"Starting physical refill: {amount} workpieces × {self.per_workpiece_refill_time}s = {physical_refill_time:.1f}s")

            # Schedule the completion after physical time
            self._schedule_refill_completion(amount, physical_refill_time)

    def _schedule_refill_completion(self, amount, physical_time):
        """Schedule the completion of refill after physical time"""
        import threading

        def complete_refill():
            # Update workpiece count and magazine status
            self.workpiece_count = amount
            self.S3 = True
            self.k = not self.S3  # Immediately update k when S3 changes

            # Reset P signal when refill is completed
            if self.P:
                self.P = False
                self.log("P signal reset - Magazine refilled")

            color_info = self.get_color_summary()
            self.log(f">>> Physical refill completed: {amount} workpieces added [{color_info}]")

            # Return to State 0 Idle, waiting for manual start again
            self.state = 0
            self.S1, self.S3, self.S4 = True, True, True
            self.S2 = False
            self.S5 = False
            self.S6 = False
            self.start_event = self.env.event()
            self.update_logic()

            # Reset refill control flags
            self.refill_in_progress = False
            self.pending_refill_timer = None

        # Cancel any existing timer
        if self.pending_refill_timer:
            self.pending_refill_timer.cancel()

        # Schedule completion after physical time
        self.pending_refill_timer = threading.Timer(physical_time, complete_refill)
        self.pending_refill_timer.start()

    def _distribute_colors_evenly(self, total_amount):
        """Distribute workpieces evenly among available colors"""
        # Reset all colors to 0
        for color in self.available_colors:
            self.workpiece_colors[color] = 0

        # Distribute evenly
        base_amount = total_amount // len(self.available_colors)
        remainder = total_amount % len(self.available_colors)

        for i, color in enumerate(self.available_colors):
            self.workpiece_colors[color] = base_amount
            if i < remainder:  # Distribute remainder to first colors
                self.workpiece_colors[color] += 1

    def _set_color_distribution(self, color_distribution):
        """Set specific color distribution"""
        # Reset all colors to 0
        for color in self.available_colors:
            self.workpiece_colors[color] = 0

        # Set specified distribution
        for color, count in color_distribution.items():
            if color in self.available_colors:
                self.workpiece_colors[color] = count


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
    # SimPy real-time environment with improved precision
    env = simpy.rt.RealtimeEnvironment(factor=1.0, strict=False)
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
        self.root.geometry("600x600")

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
            'width': 20,
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

        # Create two rows of buttons for better layout
        # First row: Start, Emergency Stop
        first_row = tk.Frame(control_frame, bg='#f0f0f0')
        first_row.pack(fill=tk.X, pady=(0, 5))

        # Start button
        tk.Button(first_row,
                 text="Start",
                 command=self.station.trigger_start,
                 bg='#98FB98',
                 **self.button_style).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        # Emergency Stop button
        tk.Button(first_row,
                 text="Emergency Stop",
                 command=self.station.trigger_emergency,
                 bg='#FFB6C1',
                 **self.button_style).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        # Second row: Performance Metrics, Exit
        second_row = tk.Frame(control_frame, bg='#f0f0f0')
        second_row.pack(fill=tk.X)

        # Performance Metrics button
        tk.Button(second_row,
                 text="Performance Metrics",
                 command=self.show_performance_panel,
                 bg='#98FB98',
                 **self.button_style).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        # Exit button - make it more prominent
        tk.Button(second_row,
                 text="Exit",
                 command=self.station.trigger_exit,
                 bg='#FF6B6B',  # Changed to a more prominent red color
                 fg='black',    # White text for better contrast
                 **self.button_style).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

    def create_workpiece_frame(self):
        # Workpiece control frame
        workpiece_frame = tk.LabelFrame(self.root, text="Workpiece Control", padx=10, pady=5, bg='#f0f0f0', font=self.labelframe_font)
        workpiece_frame.pack(fill=tk.X, padx=10, pady=5)

        # Inner frame for grid layout to align with status frame
        inner_wp_frame = tk.Frame(workpiece_frame, bg='#f0f0f0')
        inner_wp_frame.pack(pady=5, fill=tk.X)

        # Color distribution label
        tk.Label(inner_wp_frame,
                text="Color Distribution:",
                bg='#f0f0f0',
                font=self.label_font).grid(row=0, column=0, sticky='w', pady=(0,5))

        # Color input fields in a single row
        color_row_frame = tk.Frame(inner_wp_frame, bg='#f0f0f0')
        color_row_frame.grid(row=1, column=0, columnspan=4, sticky='ew')

        # Color input fields with default values
        self.color_vars = {}
        default_values = {'black': '3', 'red': '3', 'silver': '2'}  # Default balanced distribution

        for i, color in enumerate(self.station.available_colors):
            tk.Label(color_row_frame,
                    text=f"{color.capitalize()}:",
                    bg='#f0f0f0',
                    font=self.label_font).grid(row=0, column=i*2, sticky='w', padx=(0 if i==0 else 10, 0))

            var = tk.StringVar(value=default_values.get(color, "0"))
            self.color_vars[color] = var
            spinbox = tk.Spinbox(color_row_frame,
                               from_=0,
                               to=8,
                               textvariable=var,
                               width=3,
                               font=self.label_font)
            spinbox.grid(row=0, column=i*2+1, sticky='w', padx=(2,0))

        # Manual refill button placed after Silver - aligned with Exit button
        tk.Button(color_row_frame,
                 text="Manual Refill",
                 command=self.manual_refill,
                 bg='#87CEEB',
                 **self.button_style).grid(row=0, column=6, sticky='w', padx=(20,0))

        # Configure column weights for proper expansion
        color_row_frame.columnconfigure(6, weight=1)

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

        tk.Label(general_status_frame, text="Color Distribution:", font=self.label_font, bg='#f0f0f0').grid(row=2, column=0, sticky='w')
        self.color_status_label = tk.Label(general_status_frame, text="N/A", font=self.label_font, bg='#f0f0f0')
        self.color_status_label.grid(row=2, column=1, sticky='w', padx=5)

        tk.Label(general_status_frame, text="Current Color Workpiece:", font=self.label_font, bg='#f0f0f0').grid(row=3, column=0, sticky='w')
        self.current_workpiece_label = tk.Label(general_status_frame, text="N/A", font=self.label_font, bg='#f0f0f0')
        self.current_workpiece_label.grid(row=3, column=1, sticky='w', padx=5)

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
            # Check if magazine is empty
            if self.station.S3:
                tk.messagebox.showwarning("Invalid State", "Manual refill is only available when magazine is empty")
                return

            # Check if system is in a valid state for refill
            # Allow refill in State 0 (idle) or State 6 (after last workpiece ejected)
            if self.station.state != 0 and not (self.station.state == 6 and not self.station.S3):
                tk.messagebox.showwarning("Invalid State",
                                        f"Manual refill only available when:\n"
                                        f"• System is idle (State 0), or\n"
                                        f"• After last workpiece ejected (State 6 with empty magazine)\n\n"
                                        f"Current state: {self.station.state}\n"
                                        f"Magazine empty: {not self.station.S3}")
                return

            # Check if refill is already in progress
            if self.station.refill_in_progress:
                tk.messagebox.showwarning("Refill In Progress", "A refill operation is already in progress. Please wait.")
                return

            # Get color distribution from input fields
            color_distribution = {}
            total_amount = 0

            for color, var in self.color_vars.items():
                count = int(var.get())
                if count > 0:
                    color_distribution[color] = count
                    total_amount += count

            if total_amount == 0:
                tk.messagebox.showwarning("Invalid Input", "Please specify at least one workpiece")
                return

            if total_amount > 8:
                tk.messagebox.showwarning("Invalid Input", "Total workpieces cannot exceed 8")
                return

            # Perform color refill with specified distribution
            self.station.manual_refill(total_amount, color_distribution)

        except ValueError:
            tk.messagebox.showwarning("Invalid Input", "Please enter valid numbers for all colors")

    def show_performance_panel(self):
        """Show the performance metrics panel"""
        try:
            # Check if performance panel already exists
            if hasattr(self, 'performance_panel') and self.performance_panel.root.winfo_exists():
                self.performance_panel.root.lift()  # Bring to front
            else:
                self.performance_panel = PerformancePanel(self.station)
        except tk.TclError:
            # Panel was destroyed, create new one
            self.performance_panel = PerformancePanel(self.station)

    def update_status(self):
        # Update workpiece count and state
        self.workpiece_label.config(text=f"{self.station.workpiece_count}")
        self.state_label.config(text=f"{self.station.state}")

        # Update color distribution
        color_info = self.station.get_color_summary()
        self.color_status_label.config(text=color_info)

        # Update current workpiece color
        current_color = self.station.current_workpiece_color or "None"
        self.current_workpiece_label.config(text=current_color)

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


class PerformancePanel:
    def __init__(self, station):
        self.station = station
        self.root = tk.Toplevel()
        self.root.title("Performance Metrics")
        self.root.geometry("800x950")
        self.root.configure(bg='#f0f0f0')

        # Style configuration - Increased font sizes for better readability
        self.label_font = ('Arial', 14)        # Increased from 11 to 14
        self.value_font = ('Arial', 14, 'bold') # Increased from 11 to 14
        self.title_font = ('Arial', 16, 'bold') # Increased from 13 to 16

        # Create main frame with scrollbar
        main_frame = tk.Frame(self.root, bg='#f0f0f0')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Create performance metrics display
        self.create_metrics_display(main_frame)

        # Create export button
        export_frame = tk.Frame(main_frame, bg='#f0f0f0')
        export_frame.pack(fill=tk.X, pady=(5, 0))

        tk.Button(export_frame,
                 text="Export Performance Report",
                 command=self.export_report,
                 bg='#87CEEB',
                 font=self.label_font,
                 width=25,
                 pady=5).pack(side=tk.LEFT)

        tk.Button(export_frame,
                 text="Reset Metrics",
                 command=self.reset_metrics,
                 bg='#FFB6C1',
                 font=self.label_font,
                 width=25,
                 pady=5).pack(side=tk.LEFT, padx=(10, 0))

        # Start the update loop
        self.update_metrics()

    def create_metrics_display(self, parent):
        # Production Metrics
        prod_frame = tk.LabelFrame(parent, text="Production Metrics",
                                  font=self.title_font, bg='#f0f0f0', padx=10, pady=10)
        prod_frame.pack(fill=tk.X, pady=(0, 10))

        # Create labels for production metrics
        self.total_workpieces_label = self.create_metric_row(prod_frame, "Total Workpieces Processed:", "0", 0)
        self.total_cycles_label = self.create_metric_row(prod_frame, "Total Cycles Completed:", "0", 1)
        self.throughput_label = self.create_metric_row(prod_frame, "Throughput (pieces/hour):", "0.0", 2)

        # Color processing metrics
        self.black_processed_label = self.create_metric_row(prod_frame, "Black Workpieces Processed:", "0", 3)
        self.red_processed_label = self.create_metric_row(prod_frame, "Red Workpieces Processed:", "0", 4)
        self.silver_processed_label = self.create_metric_row(prod_frame, "Silver Workpieces Processed:", "0", 5)

        # Time Metrics
        time_frame = tk.LabelFrame(parent, text="Time Analysis",
                                  font=self.title_font, bg='#f0f0f0', padx=10, pady=10)
        time_frame.pack(fill=tk.X, pady=(0, 10))

        self.sim_time_label = self.create_metric_row(time_frame, "Total Simulation Time:", "0.0 s", 0)
        self.avg_cycle_time_label = self.create_metric_row(time_frame, "Average Cycle Time:", "0.0 s", 1)
        self.total_downtime_label = self.create_metric_row(time_frame, "Total Downtime:", "0.0 s", 2)
        self.utilization_label = self.create_metric_row(time_frame, "Equipment Utilization:", "0.0%", 3)

        # Refill Metrics
        refill_frame = tk.LabelFrame(parent, text="Refill Analysis",
                                    font=self.title_font, bg='#f0f0f0', padx=10, pady=10)
        refill_frame.pack(fill=tk.X, pady=(0, 10))

        self.refill_count_label = self.create_metric_row(refill_frame, "Number of Refills:", "0", 0)
        self.avg_refill_time_label = self.create_metric_row(refill_frame, "Average Total Refill Time:", "0.0 s", 1)

        # Add note about refill time composition
        note_label = tk.Label(refill_frame,
                             text="(Includes: Operator Response + Physical Refill Time)",
                             font=('Arial', 9, 'italic'),
                             bg='#f0f0f0',
                             fg='#666666')
        note_label.grid(row=2, column=0, columnspan=2, sticky='w', padx=(0, 10), pady=(2, 0))

        # State Duration Analysis
        state_frame = tk.LabelFrame(parent, text="State Duration Analysis",
                                   font=self.title_font, bg='#f0f0f0', padx=10, pady=10)
        state_frame.pack(fill=tk.X, pady=(0, 10))

        self.state_labels = {}
        state_names = ["Idle", "Cylinder Extend", "Move to Magazine", "Vacuum ON",
                      "Cylinder Retract", "Return to Station", "Vacuum OFF"]

        for i, name in enumerate(state_names):
            self.state_labels[i] = self.create_metric_row(state_frame, f"State {i} ({name}):", "0.0 s", i)

    def create_metric_row(self, parent, label_text, value_text, row):
        # Create label with fixed width for consistent alignment
        label = tk.Label(parent, text=label_text, font=self.label_font, bg='#f0f0f0',
                        width=35, anchor='w')
        label.grid(row=row, column=0, sticky='w', padx=(0, 5), pady=2)

        # Create value label with fixed width and right alignment
        value_label = tk.Label(parent, text=value_text, font=self.value_font,
                              bg='#f0f0f0', fg='#0066cc', width=12, anchor='e')
        value_label.grid(row=row, column=1, sticky='w', pady=2, padx=(0, 10))

        return value_label

    def update_metrics(self):
        metrics = self.station.get_performance_metrics()

        # Update production metrics
        self.total_workpieces_label.config(text=str(metrics['total_workpieces']))
        self.total_cycles_label.config(text=str(metrics['total_cycles']))
        self.throughput_label.config(text=f"{metrics['throughput']:.1f}")

        # Update color processing metrics
        processed_colors = metrics['processed_colors']
        self.black_processed_label.config(text=str(processed_colors['black']))
        self.red_processed_label.config(text=str(processed_colors['red']))
        self.silver_processed_label.config(text=str(processed_colors['silver']))

        # Update time metrics with industrial-standard formatting
        self.sim_time_label.config(text=f"{int(round(metrics['total_sim_time']))} s")
        self.avg_cycle_time_label.config(text=f"{metrics['avg_cycle_time']:.1f} s")
        self.total_downtime_label.config(text=f"{metrics['total_downtime']:.1f} s")
        self.utilization_label.config(text=f"{metrics['utilization']:.1f}%")

        # Update refill metrics
        self.refill_count_label.config(text=str(metrics['refill_count']))
        self.avg_refill_time_label.config(text=f"{metrics['avg_refill_time']:.1f} s")

        # Update state duration metrics
        for state_id, duration in metrics['state_durations'].items():
            if state_id in self.state_labels:
                self.state_labels[state_id].config(text=f"{duration:.1f} s")

        # Schedule next update
        self.root.after(1000, self.update_metrics)

    def export_report(self):
        try:
            metrics = self.station.get_performance_metrics()
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"performance_report_{timestamp}.json"

            # Add timestamp to metrics
            metrics['export_timestamp'] = datetime.datetime.now().isoformat()
            metrics['cycle_times_list'] = self.station.cycle_times
            metrics['refill_times_list'] = self.station.refill_times

            with open(filename, 'w') as f:
                json.dump(metrics, f, indent=2)

            tk.messagebox.showinfo("Export Successful", f"Performance report exported to {filename}")
        except Exception as e:
            tk.messagebox.showerror("Export Error", f"Failed to export report: {str(e)}")

    def reset_metrics(self):
        if tk.messagebox.askyesno("Reset Metrics", "Are you sure you want to reset all performance metrics?"):
            # Reset all performance metrics
            self.station.total_workpieces_processed = 0
            self.station.total_cycles_completed = 0
            self.station.simulation_start_time = self.station.env.now
            self.station.total_downtime = 0
            self.station.downtime_start = 0
            self.station.cycle_times = []
            self.station.refill_times = []
            self.station.state_durations = {i: 0 for i in range(7)}
            self.station.last_state_change_time = self.station.env.now
            # Reset color processing statistics
            self.station.processed_colors = {'black': 0, 'red': 0, 'silver': 0}
            # Reset refill control flags
            self.station.refill_in_progress = False
            if self.station.pending_refill_timer:
                self.station.pending_refill_timer.cancel()
                self.station.pending_refill_timer = None
            tk.messagebox.showinfo("Reset Complete", "All performance metrics have been reset.")


if __name__ == "__main__":
    run_gui()

