#!/usr/bin/env python3
"""
Sentro Knitting Machine Controller
A Python GUI application to control a NEMA 17 stepper motor via Arduino
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import serial
import serial.tools.list_ports
import threading
import time
from queue import Queue, Empty
import json
import os
from datetime import datetime

class KnittingMachineController:
    def __init__(self, root):
        self.root = root
        self.root.title("Sentro Knitting Machine Controller")
        self.root.geometry("800x600")
        
        # Serial connection
        self.arduino = None
        self.is_connected = False
        self.response_queue = Queue()
        
        # Configuration
        self.config_file = "knitting_config.json"
        self.load_config()
        
        # Pattern/script variables
        self.current_pattern = None
        self.pattern_modified = False
        
        # Create GUI
        self.create_gui()
        
        # Start serial monitor thread
        self.monitor_thread = None
        
        # Auto-connect on startup
        self.root.after(100, self.auto_connect)
    
    def load_config(self):
        """Load configuration from file"""
        default_config = {
            "steps_per_needle": 10,  # Calibration value - adjust based on your machine
            "default_speed": 1000,
            "microstepping": 1,
            "com_port": "AUTO"
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
                # Ensure all keys exist
                for key, value in default_config.items():
                    if key not in self.config:
                        self.config[key] = value
            else:
                self.config = default_config
        except:
            self.config = default_config
    
    def save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            messagebox.showerror("Error", f"Could not save config: {e}")
    
    def create_gui(self):
        """Create the main GUI"""
        # Main notebook for tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create console tab first (needed for logging)
        self.create_console_tab(notebook)
        
        # Connection tab
        self.create_connection_tab(notebook)
        
        # Control tab
        self.create_control_tab(notebook)
        
        # Settings tab
        self.create_settings_tab(notebook)
        
        # Script creation tab
        self.create_script_tab(notebook)
    
    def create_connection_tab(self, notebook):
        """Create connection tab"""
        conn_frame = ttk.Frame(notebook)
        notebook.add(conn_frame, text="Connection")
        
        # Port selection
        ttk.Label(conn_frame, text="COM Port:").pack(pady=5)
        self.port_var = tk.StringVar(value=self.config.get("com_port", "AUTO"))
        port_frame = tk.Frame(conn_frame)
        port_frame.pack(pady=5)
        
        self.port_combo = ttk.Combobox(port_frame, textvariable=self.port_var, width=20)
        self.port_combo.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(port_frame, text="Refresh", command=self.refresh_ports).pack(side=tk.LEFT, padx=5)
        
        # Connection buttons
        btn_frame = tk.Frame(conn_frame)
        btn_frame.pack(pady=10)
        
        self.connect_btn = ttk.Button(btn_frame, text="Connect", command=self.connect_arduino)
        self.connect_btn.pack(side=tk.LEFT, padx=5)
        
        self.disconnect_btn = ttk.Button(btn_frame, text="Disconnect", command=self.disconnect_arduino, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, padx=5)
        
        # Status
        self.status_var = tk.StringVar(value="Disconnected")
        ttk.Label(conn_frame, textvariable=self.status_var, font=("Arial", 12, "bold")).pack(pady=10)
        
        # Initialize port list
        self.refresh_ports()
        
        # Select first available port if AUTO is set
        if self.port_var.get() == "AUTO" and len(self.port_combo['values']) > 1:
            self.port_var.set(self.port_combo['values'][1])  # First real port
    
    def create_control_tab(self, notebook):
        """Create control tab"""
        control_frame = ttk.Frame(notebook)
        notebook.add(control_frame, text="Control")
        
        # Manual control section
        manual_frame = ttk.LabelFrame(control_frame, text="Manual Control", padding=10)
        manual_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Direction buttons
        dir_frame = tk.Frame(manual_frame)
        dir_frame.pack(pady=5)
        
        ttk.Button(dir_frame, text="← Turn Left", command=lambda: self.manual_turn("CCW")).pack(side=tk.LEFT, padx=5)
        ttk.Button(dir_frame, text="Turn Right →", command=lambda: self.manual_turn("CW")).pack(side=tk.LEFT, padx=5)
        
        # Step amount
        step_frame = tk.Frame(manual_frame)
        step_frame.pack(pady=5)
        ttk.Label(step_frame, text="Steps:").pack(side=tk.LEFT)
        self.manual_steps_var = tk.StringVar(value="10")
        tk.Entry(step_frame, textvariable=self.manual_steps_var, width=10).pack(side=tk.LEFT, padx=5)
        
        # Needle control section
        needle_frame = ttk.LabelFrame(control_frame, text="Needle Control", padding=10)
        needle_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Number of needles
        needles_input_frame = tk.Frame(needle_frame)
        needles_input_frame.pack(pady=5)
        ttk.Label(needles_input_frame, text="Number of needles:").pack(side=tk.LEFT)
        self.needles_var = tk.StringVar(value="1")
        tk.Entry(needles_input_frame, textvariable=self.needles_var, width=10).pack(side=tk.LEFT, padx=5)
        
        # Needle buttons
        needle_btn_frame = tk.Frame(needle_frame)
        needle_btn_frame.pack(pady=5)
        ttk.Button(needle_btn_frame, text="Move Needles Left", command=lambda: self.move_needles("CCW")).pack(side=tk.LEFT, padx=5)
        ttk.Button(needle_btn_frame, text="Move Needles Right", command=lambda: self.move_needles("CW")).pack(side=tk.LEFT, padx=5)
        
        # Revolution control section
        rev_frame = ttk.LabelFrame(control_frame, text="Revolution Control", padding=10)
        rev_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Revolutions input
        rev_input_frame = tk.Frame(rev_frame)
        rev_input_frame.pack(pady=5)
        ttk.Label(rev_input_frame, text="Revolutions:").pack(side=tk.LEFT)
        self.revolutions_var = tk.StringVar(value="1")
        tk.Entry(rev_input_frame, textvariable=self.revolutions_var, width=10).pack(side=tk.LEFT, padx=5)
        
        # Revolution buttons
        rev_btn_frame = tk.Frame(rev_frame)
        rev_btn_frame.pack(pady=5)
        ttk.Button(rev_btn_frame, text="Turn Left", command=lambda: self.turn_revolutions("CCW")).pack(side=tk.LEFT, padx=5)
        ttk.Button(rev_btn_frame, text="Turn Right", command=lambda: self.turn_revolutions("CW")).pack(side=tk.LEFT, padx=5)
        
        # Emergency stop
        ttk.Button(control_frame, text="🛑 EMERGENCY STOP", command=self.emergency_stop, 
                  style="Emergency.TButton").pack(pady=20)
        
        # Configure emergency button style
        style = ttk.Style()
        style.configure("Emergency.TButton", foreground="red", font=("Arial", 14, "bold"))
    
    def create_settings_tab(self, notebook):
        """Create settings tab"""
        settings_frame = ttk.Frame(notebook)
        notebook.add(settings_frame, text="Settings")
        
        # Calibration section
        cal_frame = ttk.LabelFrame(settings_frame, text="Calibration", padding=10)
        cal_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Steps per needle
        steps_frame = tk.Frame(cal_frame)
        steps_frame.pack(pady=5, fill=tk.X)
        ttk.Label(steps_frame, text="Steps per needle:").pack(side=tk.LEFT)
        self.steps_per_needle_var = tk.StringVar(value=str(self.config["steps_per_needle"]))
        tk.Entry(steps_frame, textvariable=self.steps_per_needle_var, width=10).pack(side=tk.RIGHT)
        
        # Motor settings section
        motor_frame = ttk.LabelFrame(settings_frame, text="Motor Settings", padding=10)
        motor_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Speed setting
        speed_frame = tk.Frame(motor_frame)
        speed_frame.pack(pady=5, fill=tk.X)
        ttk.Label(speed_frame, text="Motor speed (μs):").pack(side=tk.LEFT)
        self.speed_var = tk.StringVar(value=str(self.config["default_speed"]))
        speed_entry = tk.Entry(speed_frame, textvariable=self.speed_var, width=10)
        speed_entry.pack(side=tk.RIGHT)
        
        # Speed buttons
        speed_btn_frame = tk.Frame(motor_frame)
        speed_btn_frame.pack(pady=2)
        ttk.Button(speed_btn_frame, text="Apply Speed", command=self.apply_speed).pack(side=tk.LEFT, padx=2)
        ttk.Label(speed_btn_frame, text="(Lower = Faster)", font=("Arial", 8)).pack(side=tk.LEFT, padx=5)
        
        # Microstepping setting
        micro_frame = tk.Frame(motor_frame)
        micro_frame.pack(pady=5, fill=tk.X)
        ttk.Label(micro_frame, text="Microstepping:").pack(side=tk.LEFT)
        self.micro_var = tk.StringVar(value=str(self.config["microstepping"]))
        micro_combo = ttk.Combobox(micro_frame, textvariable=self.micro_var, values=[1,2,4,8,16], width=8)
        micro_combo.pack(side=tk.RIGHT)
        
        ttk.Button(motor_frame, text="Apply Microstepping", command=self.apply_microstepping).pack(pady=5)
        
        # Arduino commands section
        cmd_frame = ttk.LabelFrame(settings_frame, text="Arduino Commands", padding=10)
        cmd_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(cmd_frame, text="Get Status", command=self.get_status).pack(side=tk.LEFT, padx=5)
        ttk.Button(cmd_frame, text="Save Settings", command=self.save_settings).pack(side=tk.LEFT, padx=5)
    
    def create_script_tab(self, notebook):
        """Create script creation tab"""
        script_frame = ttk.Frame(notebook)
        notebook.add(script_frame, text="Script Creation")
        
        # Create main sections using PanedWindow for resizable layout
        main_paned = ttk.PanedWindow(script_frame, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left panel - Pattern settings and controls
        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=1)
        
        # Right panel - Pattern preview and script
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=2)
        
        # === LEFT PANEL ===
        
        # Pattern Information
        info_frame = ttk.LabelFrame(left_frame, text="Pattern Information", padding=10)
        info_frame.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Label(info_frame, text="Pattern Name:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.pattern_name_var = tk.StringVar(value="New Pattern")
        tk.Entry(info_frame, textvariable=self.pattern_name_var, width=25).grid(row=0, column=1, pady=2, padx=5)
        
        tk.Label(info_frame, text="Description:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.pattern_desc_var = tk.StringVar()
        tk.Entry(info_frame, textvariable=self.pattern_desc_var, width=25).grid(row=1, column=1, pady=2, padx=5)
        
        # Pattern Dimensions
        dim_frame = ttk.LabelFrame(left_frame, text="Pattern Dimensions", padding=10)
        dim_frame.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Label(dim_frame, text="Width (needles):").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.pattern_width_var = tk.StringVar(value="20")
        width_spin = tk.Spinbox(dim_frame, from_=1, to=48, textvariable=self.pattern_width_var, width=10)
        width_spin.grid(row=0, column=1, pady=2, padx=5)
        tk.Label(dim_frame, text="(max 48)").grid(row=0, column=2, sticky=tk.W, padx=2)
        
        tk.Label(dim_frame, text="Length (rows):").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.pattern_length_var = tk.StringVar(value="10")
        length_spin = tk.Spinbox(dim_frame, from_=1, to=1000, textvariable=self.pattern_length_var, width=10)
        length_spin.grid(row=1, column=1, pady=2, padx=5)
        
        # Pattern Type
        type_frame = ttk.LabelFrame(left_frame, text="Knitting Mode", padding=10)
        type_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.pattern_type_var = tk.StringVar(value="circular")
        tk.Radiobutton(type_frame, text="Circular (tube)", variable=self.pattern_type_var, 
                      value="circular").pack(anchor=tk.W)
        tk.Radiobutton(type_frame, text="Flat panel (back & forth)", variable=self.pattern_type_var, 
                      value="flat").pack(anchor=tk.W)
        
        tk.Label(type_frame, text="Note: All stitches are stockinette (knit only)", 
                font=("Arial", 8), fg="gray").pack(anchor=tk.W)
        
        # Knitting Patterns (Sentro-specific)
        pattern_frame = ttk.LabelFrame(left_frame, text="Knitting Patterns", padding=10)
        pattern_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Pattern presets (realistic for Sentro)
        tk.Label(pattern_frame, text="Pattern:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.preset_var = tk.StringVar(value="stockinette")
        preset_combo = ttk.Combobox(pattern_frame, textvariable=self.preset_var, width=20, values=[
            "stockinette", "color_stripes", "custom_rows"
        ])
        preset_combo.grid(row=0, column=1, pady=2, padx=5)
        preset_combo.bind("<<ComboboxSelected>>", self.on_preset_change)
        
        # Color change settings
        tk.Label(pattern_frame, text="Color changes:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.color_change_var = tk.StringVar(value="none")
        color_combo = ttk.Combobox(pattern_frame, textvariable=self.color_change_var, width=20, values=[
            "none", "every_row", "every_2_rows", "every_5_rows", "every_10_rows", "custom"
        ])
        color_combo.grid(row=1, column=1, pady=2, padx=5)
        
        tk.Label(pattern_frame, text="(Manual yarn changes required)", 
                font=("Arial", 8), fg="gray").grid(row=2, column=1, sticky=tk.W, padx=5)
        
        # Speed Settings
        speed_frame = ttk.LabelFrame(left_frame, text="Knitting Speed", padding=10)
        speed_frame.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Label(speed_frame, text="Speed:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.script_speed_var = tk.StringVar(value="1000")
        speed_combo = ttk.Combobox(speed_frame, textvariable=self.script_speed_var, width=15, values=[
            "500", "750", "1000", "1500", "2000", "2500"
        ])
        speed_combo.grid(row=0, column=1, pady=2, padx=5)
        
        tk.Label(speed_frame, text="Pause between rows:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.pause_var = tk.StringVar(value="1")
        tk.Spinbox(speed_frame, from_=0, to=10, textvariable=self.pause_var, width=10, 
                  increment=0.5).grid(row=1, column=1, pady=2, padx=5)
        tk.Label(speed_frame, text="seconds").grid(row=1, column=2, sticky=tk.W, padx=2)
        
        # Action Buttons
        btn_frame = tk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=10)
        
        ttk.Button(btn_frame, text="Generate Pattern", command=self.generate_pattern).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="Save Pattern", command=self.save_pattern).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="Load Pattern", command=self.load_pattern).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="Execute Pattern", command=self.execute_pattern).pack(fill=tk.X, pady=2)
        
        # === RIGHT PANEL ===
        
        # Pattern Preview
        preview_frame = ttk.LabelFrame(right_frame, text="Pattern Preview", padding=5)
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create canvas for pattern visualization
        canvas_frame = tk.Frame(preview_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        self.pattern_canvas = tk.Canvas(canvas_frame, bg="white", height=200)
        canvas_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.pattern_canvas.yview)
        self.pattern_canvas.configure(yscrollcommand=canvas_scrollbar.set)
        
        self.pattern_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Generated Script
        script_frame = ttk.LabelFrame(right_frame, text="Generated Script", padding=5)
        script_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Script text area
        self.script_text = scrolledtext.ScrolledText(script_frame, height=15, width=50, font=("Consolas", 9))
        self.script_text.pack(fill=tk.BOTH, expand=True)
        
        # Script control buttons
        script_btn_frame = tk.Frame(script_frame)
        script_btn_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(script_btn_frame, text="Clear Script", command=self.clear_script).pack(side=tk.LEFT, padx=2)
        ttk.Button(script_btn_frame, text="Save Script", command=self.save_script).pack(side=tk.LEFT, padx=2)
        ttk.Button(script_btn_frame, text="Load Script", command=self.load_script).pack(side=tk.LEFT, padx=2)
    
    def on_preset_change(self, event=None):
        """Handle preset pattern change"""
        preset = self.preset_var.get()
        # Sentro only does stockinette stitch, but can do color patterns
        if preset == "stockinette":
            self.color_change_var.set("none")
        elif preset == "color_stripes":
            self.color_change_var.set("every_2_rows")
        elif preset == "custom_rows":
            self.color_change_var.set("custom")
    
    def generate_pattern(self):
        """Generate knitting pattern based on settings"""
        try:
            width = int(self.pattern_width_var.get())
            length = int(self.pattern_length_var.get())
            pattern_type = self.pattern_type_var.get()
            preset = self.preset_var.get()
            color_pattern = self.color_change_var.get()
            speed = self.script_speed_var.get()
            pause = float(self.pause_var.get())
            
            if width > 48:
                messagebox.showerror("Error", "Maximum width is 48 needles")
                return
            
            # Generate pattern
            script_lines = []
            script_lines.append(f"# Pattern: {self.pattern_name_var.get()}")
            script_lines.append(f"# Description: {self.pattern_desc_var.get()}")
            script_lines.append(f"# Dimensions: {width} needles x {length} rows")
            script_lines.append(f"# Type: {pattern_type} - stockinette (knit only)")
            script_lines.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            script_lines.append("")
            script_lines.append(f"SPEED:{speed}")
            script_lines.append("")
            
            # Color change logic
            color_pattern = self.color_change_var.get()
            color_change_rows = []
            
            if color_pattern == "every_row":
                color_change_rows = list(range(1, length + 1))
            elif color_pattern == "every_2_rows":
                color_change_rows = list(range(2, length + 1, 2))
            elif color_pattern == "every_5_rows":
                color_change_rows = list(range(5, length + 1, 5))
            elif color_pattern == "every_10_rows":
                color_change_rows = list(range(10, length + 1, 10))
            
            # Calculate steps per needle from config
            steps_per_needle = int(self.steps_per_needle_var.get()) if hasattr(self, 'steps_per_needle_var') else 10
            
            for row in range(1, length + 1):
                script_lines.append(f"# Row {row}")
                
                # Add color change instruction if needed
                if row in color_change_rows:
                    script_lines.append(f"# >>> CHANGE YARN COLOR NOW <<<")
                    script_lines.append(f"WAIT:5  # Wait for manual color change")
                
                if pattern_type == "circular":
                    # Circular knitting - always same direction (clockwise)
                    direction = "CW"
                    total_steps = width * steps_per_needle
                    script_lines.append(f"TURN:{total_steps}:{direction}")
                else:
                    # Flat knitting - alternate directions for flat panels
                    direction = "CW" if row % 2 == 1 else "CCW"
                    total_steps = width * steps_per_needle
                    script_lines.append(f"TURN:{total_steps}:{direction}")
                
                # Add pause between rows
                if pause > 0 and row < length:
                    script_lines.append(f"WAIT:{pause}")
                
                script_lines.append("")
            
            script_lines.append("# Pattern complete")
            script_lines.append("STATUS")
            
            # Display script
            script_content = "\n".join(script_lines)
            self.script_text.delete(1.0, tk.END)
            self.script_text.insert(1.0, script_content)
            
            # Draw pattern preview
            self.draw_pattern_preview(width, length, pattern_type, color_pattern)
            
            self.current_pattern = {
                "name": self.pattern_name_var.get(),
                "description": self.pattern_desc_var.get(),
                "width": width,
                "length": length,
                "type": pattern_type,  # Can be circular OR flat
                "preset": preset,
                "color_pattern": color_pattern,
                "speed": speed,
                "pause": pause,
                "script": script_content
            }
            
            self.pattern_modified = True
            self.log_message(f"Pattern generated: {width}x{length} {pattern_type}", "SUCCESS")
            
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid input values: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"Error generating pattern: {e}")
    
    def draw_pattern_preview(self, width, length, pattern_type, color_pattern):
        """Draw visual pattern preview for Sentro machine"""
        self.pattern_canvas.delete("all")
        
        if width == 0 or length == 0:
            return
        
        # Calculate cell size
        canvas_width = self.pattern_canvas.winfo_width() or 400
        canvas_height = 200
        
        cell_width = min(20, (canvas_width - 20) // width)
        cell_height = 15
        
        # Colors for stockinette and color changes
        base_color = '#e6f3ff'  # Light blue for stockinette
        alt_color = '#ffe6e6'   # Light red for alternate color
        
        # Determine color change rows
        color_change_rows = set()
        if color_pattern == "every_row":
            color_change_rows = set(range(1, length + 1, 2))
        elif color_pattern == "every_2_rows":
            color_change_rows = set(range(1, length + 1, 4))  # Every other pair
        elif color_pattern == "every_5_rows":
            color_change_rows = set(range(4, length + 1, 10))  # Rows 5-9, 15-19, etc
        elif color_pattern == "every_10_rows":
            color_change_rows = set(range(9, length + 1, 20))  # Rows 10-19, 30-39, etc
        
        # Draw pattern
        for row in range(min(length, canvas_height // cell_height)):
            y = 10 + row * cell_height
            
            # Determine row color
            color = alt_color if row in color_change_rows else base_color
            
            for col in range(width):
                x = 10 + col * cell_width
                
                # Draw cell
                self.pattern_canvas.create_rectangle(
                    x, y, x + cell_width, y + cell_height,
                    fill=color, outline='gray', width=1
                )
                
                # Add knit symbol (all stitches are knit on Sentro)
                self.pattern_canvas.create_text(
                    x + cell_width//2, y + cell_height//2,
                    text="K", font=("Arial", 8)
                )
        
        # Add pattern type indicator
        type_text = f"Pattern: {pattern_type.title()} Knitting"
        if pattern_type == "flat":
            type_text += " (alternating directions)"
        
        self.pattern_canvas.create_text(10, canvas_height - 40, text=type_text, anchor=tk.W, font=("Arial", 10, "bold"))
        
        # Add legend
        legend_y = min(length, canvas_height // cell_height) * cell_height + 30
        self.pattern_canvas.create_rectangle(10, legend_y, 30, legend_y + 15, 
                                           fill=base_color, outline='gray')
        self.pattern_canvas.create_text(40, legend_y + 7, text="Main color", anchor=tk.W)
        
        if color_change_rows:
            self.pattern_canvas.create_rectangle(120, legend_y, 140, legend_y + 15, 
                                               fill=alt_color, outline='gray')
            self.pattern_canvas.create_text(150, legend_y + 7, text="Alternate color", anchor=tk.W)
        
        # Update scroll region
        self.pattern_canvas.configure(scrollregion=self.pattern_canvas.bbox("all"))
    
    def save_pattern(self):
        """Save current pattern to file"""
        if not self.current_pattern:
            messagebox.showwarning("Warning", "No pattern to save. Generate a pattern first.")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Save Pattern"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    json.dump(self.current_pattern, f, indent=2)
                self.log_message(f"Pattern saved: {filename}", "SUCCESS")
                self.pattern_modified = False
            except Exception as e:
                messagebox.showerror("Error", f"Could not save pattern: {e}")
    
    def load_pattern(self):
        """Load pattern from file"""
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Load Pattern"
        )
        
        if filename:
            try:
                with open(filename, 'r') as f:
                    pattern = json.load(f)
                
                # Load pattern into GUI
                self.pattern_name_var.set(pattern.get("name", ""))
                self.pattern_desc_var.set(pattern.get("description", ""))
                self.pattern_width_var.set(str(pattern.get("width", 20)))
                self.pattern_length_var.set(str(pattern.get("length", 10)))
                self.pattern_type_var.set(pattern.get("type", "circular"))
                self.preset_var.set(pattern.get("preset", "stockinette"))
                self.color_change_var.set(pattern.get("color_pattern", "none"))
                self.script_speed_var.set(str(pattern.get("speed", 1000)))
                self.pause_var.set(str(pattern.get("pause", 1)))
                
                # Load script
                if "script" in pattern:
                    self.script_text.delete(1.0, tk.END)
                    self.script_text.insert(1.0, pattern["script"])
                
                self.current_pattern = pattern
                self.pattern_modified = False
                
                # Regenerate preview
                self.draw_pattern_preview(
                    pattern.get("width", 20),
                    pattern.get("length", 10),
                    pattern.get("type", "circular"),
                    pattern.get("color_pattern", "none")
                )
                
                self.log_message(f"Pattern loaded: {filename}", "SUCCESS")
                
            except Exception as e:
                messagebox.showerror("Error", f"Could not load pattern: {e}")
    
    def save_script(self):
        """Save script to text file"""
        script_content = self.script_text.get(1.0, tk.END).strip()
        if not script_content:
            messagebox.showwarning("Warning", "No script to save.")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Script"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(script_content)
                self.log_message(f"Script saved: {filename}", "SUCCESS")
            except Exception as e:
                messagebox.showerror("Error", f"Could not save script: {e}")
    
    def load_script(self):
        """Load script from text file"""
        filename = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Load Script"
        )
        
        if filename:
            try:
                with open(filename, 'r') as f:
                    script_content = f.read()
                
                self.script_text.delete(1.0, tk.END)
                self.script_text.insert(1.0, script_content)
                self.log_message(f"Script loaded: {filename}", "SUCCESS")
                
            except Exception as e:
                messagebox.showerror("Error", f"Could not load script: {e}")
    
    def clear_script(self):
        """Clear the script text area"""
        self.script_text.delete(1.0, tk.END)
    
    def execute_pattern(self):
        """Execute the current pattern script"""
        script_content = self.script_text.get(1.0, tk.END).strip()
        if not script_content:
            messagebox.showwarning("Warning", "No script to execute. Generate a pattern first.")
            return
        
        if not self.is_connected:
            messagebox.showerror("Error", "Not connected to Arduino")
            return
        
        # Confirm execution
        result = messagebox.askyesno(
            "Execute Pattern", 
            f"Execute pattern: {self.pattern_name_var.get()}\n\nThis will start the knitting process. Continue?",
            icon="question"
        )
        
        if result:
            # Execute script in separate thread
            def execute_script():
                lines = script_content.split('\n')
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if line.startswith('WAIT:'):
                            wait_time = float(line.split(':')[1])
                            self.log_message(f"Waiting {wait_time} seconds...", "INFO")
                            time.sleep(wait_time)
                        else:
                            self.send_command(line)
                            time.sleep(0.1)  # Small delay between commands
                
                self.log_message("Pattern execution completed", "SUCCESS")
            
            # Start execution thread
            execution_thread = threading.Thread(target=execute_script, daemon=True)
            execution_thread.start()
            
            self.log_message("Pattern execution started", "SUCCESS")
    
    def create_console_tab(self, notebook):
        """Create console tab"""
        console_frame = ttk.Frame(notebook)
        notebook.add(console_frame, text="Console")
        
        # Commands reference section
        cmd_ref_frame = ttk.LabelFrame(console_frame, text="Available Arduino Commands", padding=5)
        cmd_ref_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Create commands text
        commands_text = """
TURN:<steps>:<direction>     - Turn specific steps (direction: CW/CCW)
REV:<revolutions>:<direction> - Turn full revolutions (direction: CW/CCW)
SPEED:<microseconds>         - Set step delay (500-3000, lower = faster)
MICRO:<value>               - Set microstepping (1, 2, 4, 8, 16)
STOP                        - Emergency stop and re-enable motor
STATUS                      - Get current motor settings and configuration

Examples:
TURN:100:CW    - Turn 100 steps clockwise
REV:2.5:CCW    - Turn 2.5 revolutions counter-clockwise
SPEED:800      - Set speed to 800 microseconds (faster)
MICRO:8        - Set microstepping to 1/8 step
        """
        
        # Commands display (read-only)
        cmd_display = tk.Text(cmd_ref_frame, height=8, width=80, wrap=tk.WORD, 
                             font=("Consolas", 9), bg="#f0f0f0", fg="#333333", 
                             relief=tk.FLAT, state=tk.DISABLED)
        cmd_display.pack(fill=tk.X, padx=5, pady=2)
        
        # Insert commands text
        cmd_display.config(state=tk.NORMAL)
        cmd_display.insert(tk.END, commands_text.strip())
        cmd_display.config(state=tk.DISABLED)
        
        # Console output
        self.console_text = scrolledtext.ScrolledText(console_frame, height=15, width=80)
        self.console_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Command input
        cmd_input_frame = tk.Frame(console_frame)
        cmd_input_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(cmd_input_frame, text="Command:").pack(side=tk.LEFT)
        self.cmd_var = tk.StringVar()
        cmd_entry = tk.Entry(cmd_input_frame, textvariable=self.cmd_var)
        cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        cmd_entry.bind("<Return>", lambda e: self.send_custom_command())
        
        ttk.Button(cmd_input_frame, text="Send", command=self.send_custom_command).pack(side=tk.LEFT)
        ttk.Button(cmd_input_frame, text="Clear", command=self.clear_console).pack(side=tk.LEFT, padx=5)
    
    def log_message(self, message, msg_type="INFO"):
        """Log message to console"""
        timestamp = time.strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {msg_type}: {message}\n"
        
        # Check if console exists (for early initialization)
        if hasattr(self, 'console_text'):
            self.console_text.insert(tk.END, formatted_msg)
            self.console_text.see(tk.END)
            
            # Color coding
            if msg_type == "ERROR":
                self.console_text.tag_add("error", f"end-{len(formatted_msg)}c", "end-1c")
                self.console_text.tag_config("error", foreground="red")
            elif msg_type == "SUCCESS":
                self.console_text.tag_add("success", f"end-{len(formatted_msg)}c", "end-1c")
                self.console_text.tag_config("success", foreground="green")
        else:
            # Fallback to print if console not ready
            print(formatted_msg.strip())
    
    def refresh_ports(self):
        """Refresh available COM ports"""
        try:
            ports = [port.device for port in serial.tools.list_ports.comports()]
            ports.insert(0, "AUTO")
            self.port_combo['values'] = ports
            
            if len(ports) <= 1:  # Only "AUTO" in list
                self.log_message("No COM ports found", "ERROR")
            else:
                self.log_message(f"Found {len(ports)-1} COM port(s)", "INFO")
        except Exception as e:
            self.log_message(f"Error refreshing ports: {e}", "ERROR")
    
    def auto_connect(self):
        """Try to auto-connect to Arduino"""
        if self.port_var.get() == "AUTO":
            # Try to find Arduino automatically
            for port in serial.tools.list_ports.comports():
                if "arduino" in port.description.lower() or "ch340" in port.description.lower() or "cp210" in port.description.lower():
                    self.port_var.set(port.device)
                    self.connect_arduino()
                    return
        else:
            self.connect_arduino()
    
    def connect_arduino(self):
        """Connect to Arduino"""
        if self.is_connected:
            return
        
        port = self.port_var.get()
        if port == "AUTO" or not port:
            messagebox.showerror("Error", "Please select a COM port")
            return
        
        try:
            self.arduino = serial.Serial(port, 9600, timeout=1)
            time.sleep(2)  # Wait for Arduino reset
            
            # Test connection
            self.arduino.write(b"STATUS\n")
            response = self.arduino.readline().decode().strip()
            
            if response:
                self.is_connected = True
                self.status_var.set(f"Connected to {port}")
                self.connect_btn.config(state=tk.DISABLED)
                self.disconnect_btn.config(state=tk.NORMAL)
                
                # Start monitoring thread
                self.start_monitor_thread()
                
                self.log_message(f"Connected to Arduino on {port}", "SUCCESS")
                self.log_message(f"Arduino response: {response}", "INFO")
                
                # Apply initial settings
                self.apply_speed()
                self.apply_microstepping()
            else:
                raise Exception("No response from Arduino")
                
        except Exception as e:
            messagebox.showerror("Connection Error", f"Could not connect to {port}\nError: {e}")
            self.log_message(f"Connection failed: {e}", "ERROR")
            if self.arduino:
                self.arduino.close()
                self.arduino = None
    
    def disconnect_arduino(self):
        """Disconnect from Arduino"""
        if self.arduino:
            self.arduino.close()
            self.arduino = None
        
        self.is_connected = False
        self.status_var.set("Disconnected")
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        
        self.log_message("Disconnected from Arduino", "INFO")
    
    def start_monitor_thread(self):
        """Start thread to monitor Arduino responses"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        
        self.monitor_thread = threading.Thread(target=self.monitor_arduino, daemon=True)
        self.monitor_thread.start()
    
    def monitor_arduino(self):
        """Monitor Arduino responses in background thread"""
        while self.is_connected and self.arduino:
            try:
                if self.arduino.in_waiting > 0:
                    response = self.arduino.readline().decode().strip()
                    if response:
                        self.root.after(0, lambda: self.log_message(f"Arduino: {response}", "INFO"))
                time.sleep(0.1)
            except:
                break
    
    def send_command(self, command):
        """Send command to Arduino"""
        if not self.is_connected or not self.arduino:
            messagebox.showerror("Error", "Not connected to Arduino")
            return False
        
        try:
            self.arduino.write((command + "\n").encode())
            self.log_message(f"Sent: {command}", "SUCCESS")
            return True
        except Exception as e:
            self.log_message(f"Send error: {e}", "ERROR")
            return False
    
    def manual_turn(self, direction):
        """Manual turn with specified steps"""
        try:
            steps = int(self.manual_steps_var.get())
            command = f"TURN:{steps}:{direction}"
            self.send_command(command)
        except ValueError:
            messagebox.showerror("Error", "Invalid number of steps")
    
    def move_needles(self, direction):
        """Move by number of needles"""
        try:
            needles = int(self.needles_var.get())
            steps_per_needle = int(self.steps_per_needle_var.get())
            total_steps = needles * steps_per_needle
            command = f"TURN:{total_steps}:{direction}"
            self.send_command(command)
        except ValueError:
            messagebox.showerror("Error", "Invalid input values")
    
    def turn_revolutions(self, direction):
        """Turn by revolutions"""
        try:
            revolutions = float(self.revolutions_var.get())
            command = f"REV:{revolutions}:{direction}"
            self.send_command(command)
        except ValueError:
            messagebox.showerror("Error", "Invalid number of revolutions")
    
    def emergency_stop(self):
        """Emergency stop"""
        if self.send_command("STOP"):
            self.log_message("EMERGENCY STOP ACTIVATED", "ERROR")
    
    def apply_speed(self):
        """Apply speed setting"""
        try:
            speed = int(self.speed_var.get())
            command = f"SPEED:{speed}"
            self.send_command(command)
        except ValueError:
            messagebox.showerror("Error", "Invalid speed value")
    
    def apply_microstepping(self):
        """Apply microstepping setting"""
        try:
            micro = int(self.micro_var.get())
            command = f"MICRO:{micro}"
            self.send_command(command)
        except ValueError:
            messagebox.showerror("Error", "Invalid microstepping value")
    
    def get_status(self):
        """Get Arduino status"""
        self.send_command("STATUS")
    
    def send_custom_command(self):
        """Send custom command"""
        command = self.cmd_var.get().strip()
        if command:
            self.send_command(command)
            self.cmd_var.set("")
    
    def clear_console(self):
        """Clear console output"""
        self.console_text.delete(1.0, tk.END)
    
    def save_settings(self):
        """Save current settings to config"""
        try:
            self.config["steps_per_needle"] = int(self.steps_per_needle_var.get())
            self.config["default_speed"] = int(self.speed_var.get())
            self.config["microstepping"] = int(self.micro_var.get())
            self.config["com_port"] = self.port_var.get()
            
            self.save_config()
            self.log_message("Settings saved successfully", "SUCCESS")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save settings: {e}")
    
    def on_closing(self):
        """Handle application closing"""
        self.disconnect_arduino()
        self.save_settings()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = KnittingMachineController(root)
    
    # Handle window closing
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    # Start the GUI
    root.mainloop()

if __name__ == "__main__":
    main()
