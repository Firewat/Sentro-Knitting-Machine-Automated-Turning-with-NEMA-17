#!/usr/bin/env python3
"""
Sentro Knitting Machine Controller
A Python GUI application to control a NEMA 17 stepper motor via Arduino
Complete version with all features
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
import re

class ProgressWindow:
    def __init__(self, parent, total_rows, needles_per_row=48):
        self.parent = parent
        self.total_rows = total_rows
        self.needles_per_row = needles_per_row
        self.current_row = 0
        self.current_needle = 0
        self.current_steps = 0
        self.total_steps_per_row = 0
        self.is_running = False
        self.is_minimized = False
        
        # Calculate total steps per row
        steps_per_needle = int(parent.config.get("steps_per_needle", 1000))
        self.total_steps_per_row = needles_per_row * steps_per_needle
        
        # Create progress window (non-blocking)
        self.window = tk.Toplevel(parent.root)
        self.window.title("Knitting Progress - Non-blocking")
        self.window.geometry("600x500")
        self.window.resizable(True, True)
        self.window.minsize(500, 400)
        
        # Make it independent (non-blocking) - removed grab_set() and transient()
        # Allow user to minimize and use main program
        self.window.protocol("WM_DELETE_WINDOW", self.on_window_close)
        
        # Set window icon and make it stay accessible
        try:
            self.window.iconify()  # Start minimized if preferred
            self.window.deiconify()  # Then show it
        except:
            pass
        
        self.create_progress_ui()
        
    def create_progress_ui(self):
        """Create progress tracking UI with enhanced controls"""
        # Title with minimize/maximize controls
        title_frame = tk.Frame(self.window)
        title_frame.pack(fill=tk.X, pady=5)
        
        title_label = tk.Label(title_frame, text="🧶 Knitting in Progress", 
                              font=("Arial", 16, "bold"))
        title_label.pack(side=tk.LEFT)
        
        # Window control buttons
        control_frame = tk.Frame(title_frame)
        control_frame.pack(side=tk.RIGHT)
        
        self.minimize_btn = ttk.Button(control_frame, text="🗕 Minimize", 
                                      command=self.toggle_minimize, width=12)
        self.minimize_btn.pack(side=tk.LEFT, padx=2)
        
        ttk.Button(control_frame, text="📌 Pin On Top", 
                  command=self.toggle_always_on_top, width=12).pack(side=tk.LEFT, padx=2)
        
        # Progress display
        progress_frame = ttk.LabelFrame(self.window, text="Knitting Progress", padding=10)
        progress_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Row progress
        row_frame = tk.Frame(progress_frame)
        row_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(row_frame, text="Rows:", font=("Arial", 12, "bold")).pack(side=tk.LEFT)
        self.row_label = tk.Label(row_frame, text=f"0 / {self.total_rows}", 
                                 font=("Arial", 12))
        self.row_label.pack(side=tk.RIGHT)
        
        # Row progress bar
        self.row_progress = ttk.Progressbar(progress_frame, length=500, mode='determinate')
        self.row_progress.pack(fill=tk.X, pady=2)
        self.row_progress['maximum'] = self.total_rows
        
        # Needle progress
        needle_frame = tk.Frame(progress_frame)
        needle_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(needle_frame, text="Needles:", font=("Arial", 12, "bold")).pack(side=tk.LEFT)
        self.needle_label = tk.Label(needle_frame, text=f"0 / {self.needles_per_row}", 
                                    font=("Arial", 12))
        self.needle_label.pack(side=tk.RIGHT)
        
        # Needle progress bar
        self.needle_progress = ttk.Progressbar(progress_frame, length=500, mode='determinate')
        self.needle_progress.pack(fill=tk.X, pady=2)
        self.needle_progress['maximum'] = self.needles_per_row
        
        # Step progress (new feature)
        step_frame = tk.Frame(progress_frame)
        step_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(step_frame, text="Steps:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.step_label = tk.Label(step_frame, text=f"0 / {self.total_steps_per_row}", 
                                  font=("Arial", 10))
        self.step_label.pack(side=tk.RIGHT)
        
        # Step progress bar (fine-grained progress)
        self.step_progress = ttk.Progressbar(progress_frame, length=500, mode='determinate')
        self.step_progress.pack(fill=tk.X, pady=2)
        self.step_progress['maximum'] = self.total_steps_per_row
        
        # Status display
        status_frame = ttk.LabelFrame(self.window, text="Current Status", padding=10)
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.status_label = tk.Label(status_frame, text="Initializing...", 
                                   font=("Arial", 11), wraplength=500)
        self.status_label.pack()
        
        # Enhanced control buttons
        control_btn_frame = ttk.LabelFrame(self.window, text="Controls", padding=10)
        control_btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        btn_row1 = tk.Frame(control_btn_frame)
        btn_row1.pack(fill=tk.X, pady=2)
        
        self.pause_btn = ttk.Button(btn_row1, text="⏸️ Pause", command=self.pause_execution)
        self.pause_btn.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        self.stop_btn = ttk.Button(btn_row1, text="🛑 Stop", command=self.stop_execution)
        self.stop_btn.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        btn_row2 = tk.Frame(control_btn_frame)
        btn_row2.pack(fill=tk.X, pady=2)
        
        self.emergency_btn = ttk.Button(btn_row2, text="🚨 EMERGENCY STOP", 
                                       command=self.emergency_stop, 
                                       style="Emergency.TButton")
        self.emergency_btn.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        self.close_btn = ttk.Button(btn_row2, text="✖️ Close", 
                                   command=self.close_window, state=tk.DISABLED)
        self.close_btn.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Configure emergency button style
        style = ttk.Style()
        style.configure("Emergency.TButton", foreground="red", font=("Arial", 10, "bold"))
        
        # Mini console with better layout
        console_frame = ttk.LabelFrame(self.window, text="Activity Log", padding=5)
        console_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Console with scrollbar
        console_container = tk.Frame(console_frame)
        console_container.pack(fill=tk.BOTH, expand=True)
        
        self.console = scrolledtext.ScrolledText(console_container, height=10, 
                                               font=("Consolas", 9), wrap=tk.WORD)
        self.console.pack(fill=tk.BOTH, expand=True)
        
        # Clear console button
        clear_frame = tk.Frame(console_frame)
        clear_frame.pack(fill=tk.X, pady=(5,0))
        
        ttk.Button(clear_frame, text="🗑️ Clear Log", 
                  command=self.clear_console).pack(side=tk.RIGHT)
        
    def update_progress(self, row, needle, status="", steps_completed=None):
        """Update progress display with step tracking"""
        self.current_row = row
        self.current_needle = needle
        
        if steps_completed is not None:
            self.current_steps = steps_completed
        
        # Update labels
        self.row_label.config(text=f"{row} / {self.total_rows}")
        self.needle_label.config(text=f"{needle} / {self.needles_per_row}")
        self.step_label.config(text=f"{self.current_steps} / {self.total_steps_per_row}")
        
        # Update progress bars
        self.row_progress['value'] = row
        self.needle_progress['value'] = needle
        self.step_progress['value'] = self.current_steps
        
        # Update status
        if status:
            self.status_label.config(text=status)
            
        # Update window (non-blocking)
        try:
            self.window.update_idletasks()
        except tk.TclError:
            pass  # Window might be closed
    
    def update_needle_from_steps(self, total_steps):
        """Update needle position based on total steps completed"""
        if self.total_steps_per_row > 0:
            steps_per_needle = int(self.parent.config.get("steps_per_needle", 1000))
            
            # Calculate current position within the row
            steps_in_current_row = total_steps % self.total_steps_per_row
            current_needle = min(int(steps_in_current_row / steps_per_needle), self.needles_per_row)
            
            # Update display
            self.current_needle = current_needle
            self.current_steps = steps_in_current_row
            
            # Update UI
            self.needle_label.config(text=f"{current_needle} / {self.needles_per_row}")
            self.step_label.config(text=f"{steps_in_current_row} / {self.total_steps_per_row}")
            self.needle_progress['value'] = current_needle
            self.step_progress['value'] = steps_in_current_row
            
            # Log progress at certain intervals
            if steps_in_current_row > 0 and steps_in_current_row % (steps_per_needle * 5) == 0:
                self.log_activity(f"📍 Position: Needle {current_needle} ({steps_in_current_row} steps)")
    
    def toggle_minimize(self):
        """Toggle window minimize state"""
        if self.is_minimized:
            self.window.deiconify()
            self.window.lift()
            self.minimize_btn.config(text="🗕 Minimize")
            self.is_minimized = False
            self.log_activity("Progress window restored")
        else:
            self.window.iconify()
            self.minimize_btn.config(text="🗖 Restore")
            self.is_minimized = True
            self.log_activity("Progress window minimized")
    
    def toggle_always_on_top(self):
        """Toggle always on top behavior"""
        try:
            current_state = self.window.attributes('-topmost')
            self.window.attributes('-topmost', not current_state)
            if not current_state:
                self.log_activity("Progress window pinned on top")
            else:
                self.log_activity("Progress window unpinned")
        except:
            pass
    
    def clear_console(self):
        """Clear the activity log"""
        self.console.delete(1.0, tk.END)
        self.log_activity("Activity log cleared")
    
    def on_window_close(self):
        """Handle window close event"""
        # Ask user if they want to minimize instead of close
        if self.is_running:
            response = messagebox.askyesnocancel(
                "Close Progress Window",
                "Knitting is still in progress.\n\n"
                "Yes: Minimize window (recommended)\n"
                "No: Close window (script continues)\n"
                "Cancel: Keep window open"
            )
            if response is True:  # Yes - minimize
                self.toggle_minimize()
            elif response is False:  # No - close
                self.window.withdraw()  # Hide instead of destroy
                self.log_activity("Progress window hidden (script continues)")
            # Cancel - do nothing
        else:
            self.close_window()
    
    def emergency_stop(self):
        """Emergency stop with immediate action"""
        self.log_activity("🚨 EMERGENCY STOP from progress window!")
        self.parent.emergency_stop()  # Use parent's emergency stop
        self.emergency_btn.config(state=tk.DISABLED)
    
    def log_activity(self, message):
        """Log activity to mini console with enhanced formatting"""
        timestamp = time.strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {message}\n"
        
        try:
            self.console.insert(tk.END, formatted_msg)
            self.console.see(tk.END)
            
            # Auto-scroll and limit console size
            lines = int(self.console.index('end-1c').split('.')[0])
            if lines > 500:  # Keep last 500 lines
                self.console.delete(1.0, f"{lines-500}.0")
        except tk.TclError:
            pass  # Window might be closed
        
    def pause_execution(self):
        """Pause execution"""
        self.parent.pause_script = True
        self.pause_btn.config(text="Resume", command=self.resume_execution)
        self.status_label.config(text="Paused - waiting for resume")
        
    def resume_execution(self):
        """Resume execution"""
        self.parent.pause_script = False
        self.pause_btn.config(text="Pause", command=self.pause_execution)
        self.status_label.config(text="Resuming...")
        
    def stop_execution(self):
        """Stop execution"""
        self.parent.stop_script = True
        self.status_label.config(text="Stopping...")
        
        # Send immediate stop command to Arduino
        if self.parent.is_connected and self.parent.arduino:
            try:
                self.parent.arduino.write(b"STOP\n")
                self.parent.arduino.flush()
                self.log_activity("🛑 Stop command sent to Arduino")
            except Exception as e:
                self.log_activity(f"⚠️ Could not send stop command to Arduino: {e}")
        
        # Disable the stop button to prevent multiple clicks
        self.stop_btn.config(state=tk.DISABLED)
        
    def execution_complete(self):
        """Called when execution is complete"""
        self.is_running = False
        self.pause_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        self.emergency_btn.config(state=tk.DISABLED)
        self.close_btn.config(state=tk.NORMAL)
        self.status_label.config(text="🎉 Knitting Complete!")
        self.log_activity("✅ Script execution completed successfully!")
        
        # Flash the window to get user attention
        try:
            for _ in range(3):
                self.window.attributes('-topmost', True)
                self.window.after(200)
                self.window.attributes('-topmost', False)
                self.window.after(200)
        except:
            pass
        
    def close_window(self):
        """Close progress window safely"""
        try:
            self.window.destroy()
        except:
            pass

class KnittingMachineController:
    def __init__(self, root):
        self.root = root
        self.root.title("Sentro Knitting Machine Controller")
        self.root.geometry("1400x800")
        self.root.minsize(1200, 700)
        
        # Configure modern styling
        self.setup_modern_styling()
        
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
        self.uploaded_script = None
        
        # Script execution control
        self.pause_script = False
        self.stop_script = False
        self.progress_window = None
        
        # Create modern GUI
        self.create_modern_gui()
        
        # Start serial monitor thread
        self.monitor_thread = None
        
        # Auto-connect on startup
        self.root.after(100, self.auto_connect)
    
    def setup_modern_styling(self):
        """Setup modern styling for the application"""
        style = ttk.Style()
        
        # Configure modern theme
        style.theme_use('clam')
        
        # Modern color scheme
        self.colors = {
            'primary': '#2196F3',
            'secondary': '#757575', 
            'success': '#4CAF50',
            'warning': '#FF9800',
            'danger': '#F44336',
            'light': '#FAFAFA',
            'dark': '#212121',
            'white': '#FFFFFF',
            'border': '#E0E0E0'
        }
        
        # Configure styles
        style.configure('Header.TFrame', background=self.colors['primary'])
        style.configure('Header.TLabel', background=self.colors['primary'], foreground=self.colors['white'], 
                       font=('Segoe UI', 12, 'bold'))
        style.configure('HeaderButton.TButton', background=self.colors['white'], foreground=self.colors['primary'],
                       font=('Segoe UI', 9), borderwidth=0, focuscolor='none')
        style.configure('Connected.TLabel', foreground=self.colors['success'], font=('Segoe UI', 10, 'bold'))
        style.configure('Disconnected.TLabel', foreground=self.colors['danger'], font=('Segoe UI', 10, 'bold'))
        style.configure('Modern.TButton', font=('Segoe UI', 10), padding=(15, 8))
        style.configure('Action.TButton', font=('Segoe UI', 10, 'bold'), padding=(20, 10))
        style.configure('Emergency.TButton', background=self.colors['danger'], foreground=self.colors['white'],
                       font=('Segoe UI', 11, 'bold'), padding=(15, 8))
        
        # Configure root window
        self.root.configure(bg=self.colors['light'])
        
        # Configure ttk Frame style to match background
        style.configure('TFrame', background=self.colors['light'])
        
        # Configure canvas background
        style.configure('Canvas', background=self.colors['light'])
    
    def load_config(self):
        """Load configuration from file"""
        default_config = {
            "steps_per_needle": 1000,  # Updated for Sentro 48-needle machine with NEMA 17
            "default_speed": 1000,
            "microstepping": 8,
            "com_port": "AUTO",
            "total_needles": 48  # Sentro machine specification
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
    
    def create_console_widget(self, parent):
        """Create console widget for tabs"""
        console_frame = ttk.LabelFrame(parent, text="Console", padding=5)
        console_frame.pack(fill=tk.X, padx=5, pady=5)
        
        console_text = scrolledtext.ScrolledText(console_frame, height=6, font=("Consolas", 9))
        console_text.pack(fill=tk.X)
        
        return console_text
    
    def create_modern_gui(self):
        """Create modern GUI layout"""
        # Create header
        self.create_modern_header()
        
        # Create main content area
        self.create_main_content()
        
        # Create footer console
        self.create_footer_console()
        
        # Initialize ports
        self.refresh_ports()
    
    def create_modern_header(self):
        """Create modern header with connection and settings"""
        header_frame = ttk.Frame(self.root, style='Header.TFrame', padding=(20, 15))
        header_frame.pack(fill=tk.X)
        
        # Left side - App title
        left_frame = ttk.Frame(header_frame, style='Header.TFrame')
        left_frame.pack(side=tk.LEFT, fill=tk.Y)
        
        title_label = ttk.Label(left_frame, text="🧶 Sentro Knitting Controller", 
                               style='Header.TLabel', font=('Segoe UI', 16, 'bold'))
        title_label.pack(side=tk.LEFT)
        
        # Right side - Connection controls and settings
        right_frame = ttk.Frame(header_frame, style='Header.TFrame')
        right_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Steps per needle display
        steps_frame = ttk.Frame(right_frame, style='Header.TFrame')
        steps_frame.pack(side=tk.RIGHT, padx=(0, 20))
        
        ttk.Label(steps_frame, text="Steps/Needle:", style='Header.TLabel').pack(side=tk.LEFT)
        self.steps_per_needle_var = tk.StringVar(value=str(self.config["steps_per_needle"]))
        steps_entry = tk.Entry(steps_frame, textvariable=self.steps_per_needle_var, 
                              width=6, font=('Segoe UI', 10, 'bold'), 
                              bg=self.colors['white'], relief='flat', bd=2)
        steps_entry.pack(side=tk.LEFT, padx=(5, 0))
        steps_entry.bind('<Return>', self.update_steps_per_needle)
        
        # Connection status and controls
        conn_frame = ttk.Frame(right_frame, style='Header.TFrame')
        conn_frame.pack(side=tk.RIGHT, padx=(0, 15))
        
        # Port selection (compact)
        self.port_var = tk.StringVar(value=self.config.get("com_port", "AUTO"))
        self.port_combo = ttk.Combobox(conn_frame, textvariable=self.port_var, 
                                      width=12, font=('Segoe UI', 9))
        self.port_combo.pack(side=tk.LEFT, padx=(0, 5))
        
        # Connection buttons
        self.connect_btn = ttk.Button(conn_frame, text="Connect", 
                                     command=self.connect_arduino, 
                                     style='HeaderButton.TButton')
        self.connect_btn.pack(side=tk.LEFT, padx=2)
        
        self.disconnect_btn = ttk.Button(conn_frame, text="Disconnect", 
                                        command=self.disconnect_arduino,
                                        style='HeaderButton.TButton', state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, padx=2)
        
        self.test_comm_btn = ttk.Button(conn_frame, text="Test", 
                                       command=self.test_arduino_communication,
                                       style='HeaderButton.TButton', state=tk.DISABLED)
        self.test_comm_btn.pack(side=tk.LEFT, padx=2)
        
        # Status indicator
        status_frame = ttk.Frame(right_frame, style='Header.TFrame')
        status_frame.pack(side=tk.RIGHT)
        
        self.status_var = tk.StringVar(value="Disconnected")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, 
                                     style='Disconnected.TLabel')
        self.status_label.pack()
    
    def create_main_content(self):
        """Create main content area with modern sidebar navigation"""
        main_frame = ttk.Frame(self.root, padding=(10, 10))
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create horizontal paned window
        paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True)
        
        # Left sidebar navigation
        sidebar_frame = ttk.Frame(paned_window, padding=(10, 0))
        paned_window.add(sidebar_frame, weight=0)
        
        # Navigation buttons
        nav_frame = ttk.LabelFrame(sidebar_frame, text="Navigation", padding=10)
        nav_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.nav_buttons = {}
        nav_items = [
            ("🎮 Manual Control", "control"),
            ("⚙️ Settings", "settings"), 
            ("📝 Create Script", "create"),
            ("📁 Upload Script", "upload")
        ]
        
        for text, key in nav_items:
            btn = ttk.Button(nav_frame, text=text, style='Modern.TButton',
                           command=lambda k=key: self.show_content_panel(k))
            btn.pack(fill=tk.X, pady=2)
            self.nav_buttons[key] = btn
        
        # Quick actions
        quick_frame = ttk.LabelFrame(sidebar_frame, text="Quick Actions", padding=10)
        quick_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(quick_frame, text="🛑 Emergency Stop", 
                  command=self.emergency_stop, 
                  style='Emergency.TButton').pack(fill=tk.X, pady=2)
        
        ttk.Button(quick_frame, text="📊 Get Status", 
                  command=self.get_status,
                  style='Modern.TButton').pack(fill=tk.X, pady=2)
        
        # Main content area
        content_frame = ttk.Frame(paned_window, padding=(10, 0))
        paned_window.add(content_frame, weight=1)
        
        # Content panels container
        self.content_container = ttk.Frame(content_frame)
        self.content_container.pack(fill=tk.BOTH, expand=True)
        
        # Create all content panels
        self.create_content_panels()
        
        # Show default panel
        self.show_content_panel("control")
    
    def create_footer_console(self):
        """Create modern footer console"""
        footer_frame = ttk.Frame(self.root, padding=(10, 5))
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        console_frame = ttk.LabelFrame(footer_frame, text="System Console", padding=5)
        console_frame.pack(fill=tk.X)
        
        # Console with modern styling
        self.console_text = scrolledtext.ScrolledText(
            console_frame, 
            height=6, 
            font=("Consolas", 9),
            bg=self.colors['dark'],
            fg=self.colors['white'],
            insertbackground=self.colors['white'],
            selectbackground=self.colors['primary'],
            relief='flat',
            bd=0
        )
        self.console_text.pack(fill=tk.X)
    
    def update_steps_per_needle(self, event=None):
        """Update steps per needle configuration"""
        try:
            steps = int(self.steps_per_needle_var.get())
            self.config["steps_per_needle"] = steps
            self.save_config()
            self.log_message(f"✓ Steps per needle updated to {steps}")
        except ValueError:
            self.steps_per_needle_var.set(str(self.config["steps_per_needle"]))
            self.log_message("❌ Invalid steps per needle value")
    
    def show_content_panel(self, panel_name):
        """Show the specified content panel"""
        # Hide all panels
        for widget in self.content_container.winfo_children():
            widget.pack_forget()
        
        # Update button states
        for key, btn in self.nav_buttons.items():
            if key == panel_name:
                btn.state(['pressed'])
            else:
                btn.state(['!pressed'])
        
        # Show selected panel
        if panel_name in self.content_panels:
            self.content_panels[panel_name].pack(fill=tk.BOTH, expand=True)
    
    def create_content_panels(self):
        """Create all content panels"""
        self.content_panels = {}
        
        # Manual Control Panel
        self.content_panels["control"] = self.create_control_panel()
        
        # Settings Panel
        self.content_panels["settings"] = self.create_settings_panel()
        
        # Script Creation Panel
        self.content_panels["create"] = self.create_script_creation_panel()
        
        # Script Upload Panel
        self.content_panels["upload"] = self.create_upload_panel()
    
    def create_control_panel(self):
        """Create modern manual control panel"""
        control_frame = ttk.Frame(self.content_container)
        
        # Title
        title_label = ttk.Label(control_frame, text="Manual Control", 
                               font=('Segoe UI', 18, 'bold'))
        title_label.pack(pady=(0, 20))
        
        # Create control sections in a grid
        sections_frame = ttk.Frame(control_frame)
        sections_frame.pack(fill=tk.BOTH, expand=True, padx=20)
        
        # Manual turning section
        manual_frame = ttk.LabelFrame(sections_frame, text="Manual Turning", 
                                     padding=20)
        manual_frame.grid(row=0, column=0, padx=10, pady=10, sticky='ew')
        
        # Step input
        step_input_frame = ttk.Frame(manual_frame)
        step_input_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(step_input_frame, text="Steps:", font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)
        self.manual_steps_var = tk.StringVar(value="1000")
        step_entry = tk.Entry(step_input_frame, textvariable=self.manual_steps_var, 
                             width=8, font=('Segoe UI', 11), justify='center')
        step_entry.pack(side=tk.RIGHT)
        
        # Direction buttons
        btn_frame = ttk.Frame(manual_frame)
        btn_frame.pack(fill=tk.X)
        
        ttk.Button(btn_frame, text="⬅ Turn Left", 
                  command=lambda: self.manual_turn("CCW"),
                  style='Action.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(btn_frame, text="Turn Right ➡", 
                  command=lambda: self.manual_turn("CW"),
                  style='Action.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Needle control section
        needle_frame = ttk.LabelFrame(sections_frame, text="Needle Control", 
                                     padding=20)
        needle_frame.grid(row=0, column=1, padx=10, pady=10, sticky='ew')
        
        # Needle input
        needle_input_frame = ttk.Frame(needle_frame)
        needle_input_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(needle_input_frame, text="Needles:", font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)
        self.needles_var = tk.StringVar(value="1")
        needle_entry = tk.Entry(needle_input_frame, textvariable=self.needles_var, 
                               width=8, font=('Segoe UI', 11), justify='center')
        needle_entry.pack(side=tk.RIGHT)
        
        # Needle direction buttons
        needle_btn_frame = ttk.Frame(needle_frame)
        needle_btn_frame.pack(fill=tk.X)
        
        ttk.Button(needle_btn_frame, text="⬅ Move Left", 
                  command=lambda: self.move_needles("CCW"),
                  style='Action.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(needle_btn_frame, text="Move Right ➡", 
                  command=lambda: self.move_needles("CW"),
                  style='Action.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Revolution control section
        rev_frame = ttk.LabelFrame(sections_frame, text="Revolution Control", 
                                  padding=20)
        rev_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky='ew')
        
        # Revolution input
        rev_input_frame = ttk.Frame(rev_frame)
        rev_input_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Label(rev_input_frame, text="Revolutions:", font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)
        self.revolutions_var = tk.StringVar(value="1")
        rev_entry = tk.Entry(rev_input_frame, textvariable=self.revolutions_var, 
                            width=8, font=('Segoe UI', 11), justify='center')
        rev_entry.pack(side=tk.LEFT, padx=(10, 0))
        
        # Revolution buttons
        rev_btn_frame = ttk.Frame(rev_frame)
        rev_btn_frame.pack(side=tk.RIGHT)
        
        ttk.Button(rev_btn_frame, text="⬅ Turn Left", 
                  command=lambda: self.turn_revolutions("CCW"),
                  style='Action.TButton').pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(rev_btn_frame, text="Turn Right ➡", 
                  command=lambda: self.turn_revolutions("CW"),
                  style='Action.TButton').pack(side=tk.LEFT)
        
        # Configure grid weights
        sections_frame.grid_columnconfigure(0, weight=1)
        sections_frame.grid_columnconfigure(1, weight=1)
        
        return control_frame
    
    def create_settings_panel(self):
        """Create modern settings panel"""
        settings_frame = ttk.Frame(self.content_container)
        
        # Title
        title_label = ttk.Label(settings_frame, text="Machine Settings", 
                               font=('Segoe UI', 18, 'bold'))
        title_label.pack(pady=(0, 20))
        
        # Settings sections
        sections_frame = ttk.Frame(settings_frame)
        sections_frame.pack(fill=tk.BOTH, expand=True, padx=20)
        
        # Motor settings section
        motor_frame = ttk.LabelFrame(sections_frame, text="Motor Configuration", 
                                    padding=20)
        motor_frame.grid(row=0, column=0, padx=10, pady=10, sticky='ew')
        
        # Speed setting
        speed_frame = ttk.Frame(motor_frame)
        speed_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(speed_frame, text="Motor Speed (μs):", font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)
        self.speed_var = tk.StringVar(value=str(self.config["default_speed"]))
        speed_entry = tk.Entry(speed_frame, textvariable=self.speed_var, 
                              width=8, font=('Segoe UI', 11), justify='center')
        speed_entry.pack(side=tk.RIGHT)
        
        ttk.Button(motor_frame, text="Apply Speed", 
                  command=self.apply_speed,
                  style='Modern.TButton').pack(fill=tk.X, pady=(0, 10))
        
        # Microstepping
        micro_frame = ttk.Frame(motor_frame)
        micro_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(micro_frame, text="Microstepping:", font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)
        self.micro_var = tk.StringVar(value=str(self.config["microstepping"]))
        micro_combo = ttk.Combobox(micro_frame, textvariable=self.micro_var, 
                                  values=[1,2,4,8,16,32], width=6, state="readonly")
        micro_combo.pack(side=tk.RIGHT)
        
        ttk.Button(motor_frame, text="Apply Microstepping", 
                  command=self.apply_microstepping,
                  style='Modern.TButton').pack(fill=tk.X)
        
        # Timing settings section
        timing_frame = ttk.LabelFrame(sections_frame, text="Communication & Timing", 
                                     padding=20)
        timing_frame.grid(row=0, column=1, padx=10, pady=10, sticky='ew')
        
        # Timeout setting
        timeout_frame = ttk.Frame(timing_frame)
        timeout_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(timeout_frame, text="Arduino Timeout (s):", font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)
        self.timeout_var = tk.StringVar(value="30")
        timeout_entry = tk.Entry(timeout_frame, textvariable=self.timeout_var, 
                                width=6, font=('Segoe UI', 11), justify='center')
        timeout_entry.pack(side=tk.RIGHT)
        
        # Command delay
        delay_frame = ttk.Frame(timing_frame)
        delay_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(delay_frame, text="Command Delay (ms):", font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT)
        self.command_delay_var = tk.StringVar(value="200")
        delay_entry = tk.Entry(delay_frame, textvariable=self.command_delay_var, 
                              width=6, font=('Segoe UI', 11), justify='center')
        delay_entry.pack(side=tk.RIGHT)
        
        # Wait for confirmation
        self.wait_confirmation_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(timing_frame, text="Wait for Arduino confirmation", 
                       variable=self.wait_confirmation_var).pack(anchor='w', pady=(0, 10))
        
        ttk.Button(timing_frame, text="Save All Settings", 
                  command=self.save_settings,
                  style='Action.TButton').pack(fill=tk.X)
        
        # Configure grid weights
        sections_frame.grid_columnconfigure(0, weight=1)
        sections_frame.grid_columnconfigure(1, weight=1)
        
        return settings_frame
    
    def create_script_creation_panel(self):
        """Create modern script creation panel"""
        create_frame = ttk.Frame(self.content_container)
        
        # Title
        title_label = ttk.Label(create_frame, text="Create Knitting Script", 
                               font=('Segoe UI', 18, 'bold'))
        title_label.pack(pady=(0, 20))
        
        # Main container with scrollable frame
        main_container = ttk.Frame(create_frame)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))
        
        # Create scrollable text widget for the entire panel
        canvas = tk.Canvas(main_container, bg=self.colors['light'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Add mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Create simple two-column layout
        content_frame = ttk.Frame(scrollable_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left column - Settings
        left_column = ttk.Frame(content_frame)
        left_column.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # Pattern information
        info_frame = ttk.LabelFrame(left_column, text="Pattern Information", 
                                   padding=15)
        info_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Pattern name
        name_frame = ttk.Frame(info_frame)
        name_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(name_frame, text="Pattern Name:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.pattern_name_var = tk.StringVar(value="New Pattern")
        tk.Entry(name_frame, textvariable=self.pattern_name_var, font=('Segoe UI', 10)).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))
        
        # Pattern description
        desc_frame = ttk.Frame(info_frame)
        desc_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(desc_frame, text="Description:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.pattern_desc_var = tk.StringVar(value="Basic knitting pattern")
        tk.Entry(desc_frame, textvariable=self.pattern_desc_var, font=('Segoe UI', 10)).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))
        
        # Pattern dimensions
        dim_frame = ttk.LabelFrame(left_column, text="Dimensions", 
                                  padding=15)
        dim_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Width
        width_frame = ttk.Frame(dim_frame)
        width_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(width_frame, text="Width (needles):", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.pattern_width_var = tk.StringVar(value="48")
        tk.Spinbox(width_frame, from_=1, to=48, textvariable=self.pattern_width_var, 
                  width=8, font=('Segoe UI', 10), justify='center').pack(side=tk.RIGHT)
        
        # Length
        length_frame = ttk.Frame(dim_frame)
        length_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(length_frame, text="Length (rows):", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.pattern_length_var = tk.StringVar(value="10")
        tk.Spinbox(length_frame, from_=1, to=1000, textvariable=self.pattern_length_var, 
                  width=8, font=('Segoe UI', 10), justify='center').pack(side=tk.RIGHT)
        
        # Calculation display
        self.motor_calc_label = ttk.Label(dim_frame, text="Total steps: 480,000", 
                                         font=('Segoe UI', 9), foreground=self.colors['primary'])
        self.motor_calc_label.pack(pady=(5, 0))
        
        # Pattern type
        type_frame = ttk.LabelFrame(left_column, text="Knitting Mode", 
                                   padding=15)
        type_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.pattern_type_var = tk.StringVar(value="circular")
        ttk.Radiobutton(type_frame, text="Circular (tube)", variable=self.pattern_type_var, 
                       value="circular").pack(anchor=tk.W, pady=2)
        ttk.Radiobutton(type_frame, text="Flat panel", variable=self.pattern_type_var, 
                       value="flat").pack(anchor=tk.W, pady=2)
        
        # Pattern presets and color changes
        pattern_frame = ttk.LabelFrame(left_column, text="Pattern Options", 
                                      padding=15)
        pattern_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Pattern preset
        preset_frame = ttk.Frame(pattern_frame)
        preset_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(preset_frame, text="Preset:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.preset_var = tk.StringVar(value="stockinette")
        preset_combo = ttk.Combobox(preset_frame, textvariable=self.preset_var, 
                                   values=["stockinette", "color_stripes", "custom_rows"], 
                                   width=15, state="readonly")
        preset_combo.pack(side=tk.RIGHT)
        preset_combo.bind('<<ComboboxSelected>>', self.on_preset_change)
        
        # Color changes
        color_frame = ttk.Frame(pattern_frame)
        color_frame.pack(fill=tk.X)
        ttk.Label(color_frame, text="Color Changes:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.color_change_var = tk.StringVar(value="none")
        color_combo = ttk.Combobox(color_frame, textvariable=self.color_change_var, 
                                  values=["none", "every_row", "every_2_rows", "every_5_rows", "every_10_rows"], 
                                  width=15, state="readonly")
        color_combo.pack(side=tk.RIGHT)
        
        # Speed settings
        speed_frame = ttk.LabelFrame(left_column, text="Speed & Timing", 
                                    padding=15)
        speed_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Script speed
        script_speed_frame = ttk.Frame(speed_frame)
        script_speed_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(script_speed_frame, text="Speed (μs):", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.script_speed_var = tk.StringVar(value="1000")
        ttk.Combobox(script_speed_frame, textvariable=self.script_speed_var, 
                    values=["500", "750", "1000", "1500", "2000"], 
                    width=8, state="readonly").pack(side=tk.RIGHT)
        
        # Pause between rows
        pause_frame = ttk.Frame(speed_frame)
        pause_frame.pack(fill=tk.X)
        ttk.Label(pause_frame, text="Row pause (s):", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.pause_var = tk.StringVar(value="1")
        tk.Spinbox(pause_frame, from_=0, to=10, textvariable=self.pause_var, 
                  width=8, font=('Segoe UI', 10), justify='center', increment=0.5).pack(side=tk.RIGHT)
        
        # Action buttons
        action_frame = ttk.Frame(left_column)
        action_frame.pack(fill=tk.X, pady=10)
        
        ttk.Button(action_frame, text="🎯 Generate Script", 
                  command=self.generate_pattern,
                  style='Action.TButton').pack(fill=tk.X, pady=2)
        
        btn_row = ttk.Frame(action_frame)
        btn_row.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(btn_row, text="💾 Save", 
                  command=self.save_pattern,
                  style='Modern.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        
        ttk.Button(btn_row, text="📁 Load", 
                  command=self.load_pattern,
                  style='Modern.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
        
        # Right column - Script preview and controls
        right_column = ttk.Frame(content_frame)
        right_column.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        
        # Script display
        script_label_frame = ttk.LabelFrame(right_column, text="Generated Script", 
                                           padding=10)
        script_label_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.script_text = scrolledtext.ScrolledText(
            script_label_frame, 
            font=("Consolas", 10),
            bg=self.colors['light'],
            relief='flat',
            bd=1
        )
        self.script_text.pack(fill=tk.BOTH, expand=True)
        
        # Script controls
        script_controls = ttk.Frame(right_column)
        script_controls.pack(fill=tk.X)
        
        ttk.Button(script_controls, text="▶️ Execute Script", 
                  command=self.execute_script,
                  style='Action.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(script_controls, text="💾 Save Script", 
                  command=self.save_script,
                  style='Modern.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Update calculation when dimensions change
        def update_calculation(*args):
            try:
                width = int(self.pattern_width_var.get())
                length = int(self.pattern_length_var.get())
                steps_per_needle = int(self.steps_per_needle_var.get())
                total_steps = width * length * steps_per_needle
                self.motor_calc_label.config(text=f"Total steps: {total_steps:,}")
            except:
                self.motor_calc_label.config(text="Enter valid numbers")
        
        self.pattern_width_var.trace('w', update_calculation)
        self.pattern_length_var.trace('w', update_calculation)
        self.steps_per_needle_var.trace('w', update_calculation)
        
        return create_frame
    
    def create_upload_panel(self):
        """Create modern script upload panel"""
        upload_frame = ttk.Frame(self.content_container)
        
        # Title
        title_label = ttk.Label(upload_frame, text="Upload & Execute Script", 
                               font=('Segoe UI', 18, 'bold'))
        title_label.pack(pady=(0, 20))
        
        # Main scrollable content
        main_container = ttk.Frame(upload_frame)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))
        
        # Create scrollable area
        canvas = tk.Canvas(main_container, bg=self.colors['light'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        content_frame = ttk.Frame(canvas)
        
        content_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=content_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Add mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Upload section
        upload_section = ttk.LabelFrame(content_frame, text="File Upload", 
                                       padding=20)
        upload_section.pack(fill=tk.X, pady=(10, 10))
        
        # Upload controls
        upload_controls = ttk.Frame(upload_section)
        upload_controls.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(upload_controls, text="📁 Browse & Upload Script", 
                  command=self.upload_script_file,
                  style='Action.TButton').pack(side=tk.LEFT)
        
        self.upload_status_label = ttk.Label(upload_controls, text="No file uploaded", 
                                           foreground=self.colors['secondary'])
        self.upload_status_label.pack(side=tk.LEFT, padx=(15, 0))
        
        # Validation controls
        validation_controls = ttk.Frame(upload_section)
        validation_controls.pack(fill=tk.X)
        
        ttk.Button(validation_controls, text="✓ Validate Script", 
                  command=self.validate_uploaded_script,
                  style='Modern.TButton').pack(side=tk.LEFT)
        
        # Script display section (simplified)
        display_section = ttk.LabelFrame(content_frame, text="Script Content", 
                                        padding=15)
        display_section.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Script text area
        self.uploaded_script_text = scrolledtext.ScrolledText(
            display_section, 
            font=("Consolas", 10),
            bg=self.colors['white'],
            relief='flat',
            bd=1,
            height=15
        )
        self.uploaded_script_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Validation results (simplified)
        validation_label = ttk.Label(display_section, text="Validation Results:", 
                                     font=('Segoe UI', 11, 'bold'))
        validation_label.pack(anchor='w', pady=(5, 5))
        
        self.validation_result = scrolledtext.ScrolledText(
            display_section, 
            height=4,
            font=("Consolas", 9),
            bg=self.colors['white'],
            relief='flat',
            bd=1
        )
        self.validation_result.pack(fill=tk.X, pady=(0, 10))
        
        # Execute section
        execute_section = ttk.Frame(content_frame)
        execute_section.pack(fill=tk.X)
        
        ttk.Button(execute_section, text="▶️ Execute Uploaded Script", 
                  command=self.execute_uploaded_script,
                  style='Action.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(execute_section, text="🗑️ Clear", 
                  command=self.clear_uploaded_script,
                  style='Modern.TButton').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        return upload_frame
    
    def refresh_ports(self):
        """Refresh list of available COM ports"""
        ports = ["AUTO"]
        for port in serial.tools.list_ports.comports():
            ports.append(f"{port.device} - {port.description}")
        
        self.port_combo['values'] = ports
    
    def auto_connect(self):
        """Automatically connect to Arduino if AUTO is selected"""
        if self.port_var.get() == "AUTO":
            self.connect_arduino()
    
    def connect_arduino(self):
        """Connect to Arduino with improved reliability"""
        try:
            if self.port_var.get() == "AUTO":
                # Auto-detect Arduino with improved detection
                for port in serial.tools.list_ports.comports():
                    if ('arduino' in port.description.lower() or 
                        'ch340' in port.description.lower() or 
                        'ch341' in port.description.lower() or
                        'usb' in port.description.lower() or
                        'serial' in port.description.lower()):
                        try:
                            # Try to connect with proper settings
                            self.arduino = serial.Serial(
                                port=port.device, 
                                baudrate=9600, 
                                timeout=3,  # Increased timeout for initial connection
                                write_timeout=3,
                                bytesize=serial.EIGHTBITS,
                                parity=serial.PARITY_NONE,
                                stopbits=serial.STOPBITS_ONE
                            )
                            self.log_message(f"Testing connection on {port.device}")
                            break
                        except Exception as e:
                            self.log_message(f"Failed to connect to {port.device}: {e}")
                            continue
                else:
                    # If no Arduino found, try first available port
                    ports = list(serial.tools.list_ports.comports())
                    if ports:
                        self.arduino = serial.Serial(
                            port=ports[0].device, 
                            baudrate=9600, 
                            timeout=3,
                            write_timeout=3,
                            bytesize=serial.EIGHTBITS,
                            parity=serial.PARITY_NONE,
                            stopbits=serial.STOPBITS_ONE
                        )
                        self.log_message(f"Using first available port: {ports[0].device}")
                    else:
                        raise Exception("No COM ports available")
            else:
                # Use selected port
                port_device = self.port_var.get().split(' - ')[0]
                self.arduino = serial.Serial(
                    port=port_device, 
                    baudrate=9600, 
                    timeout=3,
                    write_timeout=3,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE
                )
            
            # Wait for Arduino to initialize (Arduino resets on connection)
            time.sleep(3)
            
            # Clear any initial boot messages
            self.arduino.reset_input_buffer()
            self.arduino.reset_output_buffer()
            
            # Test connection with multiple attempts
            connection_verified = False
            for attempt in range(3):
                try:
                    self.log_message(f"Connection test attempt {attempt + 1}/3")
                    self.arduino.write(b"STATUS\n")
                    
                    # Read response with timeout
                    start_time = time.time()
                    response_lines = []
                    while time.time() - start_time < 5:  # 5 second timeout
                        if self.arduino.in_waiting:
                            line = self.arduino.readline().decode('utf-8', errors='ignore').strip()
                            if line:
                                response_lines.append(line)
                                self.log_message(f"Arduino: {line}")
                                # Check for "OK" confirmation at end of STATUS
                                if line == "OK":
                                    connection_verified = True
                                    break
                        time.sleep(0.1)
                    
                    if connection_verified:
                        break
                    else:
                        time.sleep(1)  # Wait before retry
                        
                except Exception as e:
                    self.log_message(f"Connection test {attempt + 1} failed: {e}")
                    time.sleep(1)
            
            if not connection_verified:
                self.log_message("Warning: Arduino connection could not be fully verified")
                # But continue anyway - some Arduinos may not respond to STATUS immediately
            
            self.is_connected = True
            self.status_var.set("Connected")
            self.status_label.config(style='Connected.TLabel')
            self.connect_btn.config(state=tk.DISABLED)
            self.disconnect_btn.config(state=tk.NORMAL)
            self.test_comm_btn.config(state=tk.NORMAL)
            
            self.log_message(f"✓ Connected to Arduino on {self.arduino.port}")
            
            # Start monitoring thread
            self.monitor_thread = threading.Thread(target=self.monitor_arduino, daemon=True)
            self.monitor_thread.start()
            
        except Exception as e:
            self.log_message(f"Connection failed: {e}")
            if hasattr(self, 'arduino') and self.arduino:
                try:
                    self.arduino.close()
                except:
                    pass
            messagebox.showerror("Connection Error", f"Could not connect to Arduino: {e}\n\nTry:\n1. Check Arduino is connected\n2. Close other programs using COM port\n3. Try a different COM port\n4. Restart Arduino")
    
    def disconnect_arduino(self):
        """Disconnect from Arduino with proper cleanup"""
        try:
            self.is_connected = False  # Stop monitoring thread first
            
            if self.arduino and self.arduino.is_open:
                # Send a safe stop command before disconnecting
                try:
                    self.arduino.write(b"STOP\n")
                    self.arduino.flush()
                    time.sleep(0.5)  # Give Arduino time to process
                except:
                    pass
                
                self.arduino.close()
                self.log_message("✓ Arduino connection closed safely")
            
            self.status_var.set("Disconnected")
            self.status_label.config(style='Disconnected.TLabel')
            self.connect_btn.config(state=tk.NORMAL)
            self.disconnect_btn.config(state=tk.DISABLED)
            self.test_comm_btn.config(state=tk.DISABLED)
            
            # Clean up monitoring thread
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=1.0)
            
        except Exception as e:
            self.log_message(f"Disconnect error: {e}")
            # Force cleanup even if error occurred
            self.is_connected = False
            self.status_var.set("Disconnected")
            self.status_label.config(style='Disconnected.TLabel')
            self.connect_btn.config(state=tk.NORMAL)
            self.disconnect_btn.config(state=tk.DISABLED)
            self.test_comm_btn.config(state=tk.DISABLED)
    
    def monitor_arduino(self):
        """Monitor Arduino responses with improved reliability and step tracking"""
        while self.is_connected:
            try:
                if self.arduino and self.arduino.is_open and self.arduino.in_waiting:
                    response = self.arduino.readline().decode('utf-8', errors='ignore').strip()
                    if response:
                        self.response_queue.put(response)
                        
                        # Check for step progress updates from Arduino
                        if response.startswith("Arduino:") and "steps" in response.lower():
                            self.process_arduino_step_update(response)
                        
                        # Only log non-empty, meaningful responses
                        if (response and not response.startswith("Progress:") and 
                            len(response) > 0 and response != ""):
                            self.log_message(f"Arduino: {response}")
                time.sleep(0.05)  # Reduced polling interval for better responsiveness
            except Exception as e:
                if self.is_connected:  # Only log if we're supposed to be connected
                    self.log_message(f"Monitor error: {e}")
                break
    
    def process_arduino_step_update(self, response):
        """Process Arduino step updates and update progress window"""
        try:
            # Extract step information from Arduino response
            # Expected format: "Arduino: steps_completed" or "Arduino: Step 1234/5000"
            if self.progress_window:
                # Try to extract step numbers from various formats
                import re
                
                # Pattern for "Step X/Y" or "X steps"
                step_match = re.search(r'(\d+)\s*(?:steps?|/)', response.lower())
                if step_match:
                    steps_completed = int(step_match.group(1))
                    self.progress_window.update_needle_from_steps(steps_completed)
                
                # Pattern for "Arduino: X" where X is a number (step count)
                arduino_match = re.search(r'arduino:\s*(\d+)', response.lower())
                if arduino_match:
                    steps_completed = int(arduino_match.group(1))
                    self.progress_window.update_needle_from_steps(steps_completed)
                    
        except Exception as e:
            # Don't log this error as it's not critical
            pass
    
    def is_valid_arduino_response(self, response):
        """Check if Arduino response is valid and not corrupted"""
        if not response or len(response) < 2:
            return False
        
        # Check for garbled responses (common patterns from corruption)
        corruption_indicators = [
            # Garbled text with random characters
            'DU:Poesn', 'omn:', 'EBG', 'rcsigcmad',
            # Responses with control characters or invalid encoding
            '\x00', '\xff', '\xfe',
            # Responses that are clearly malformed
            'TUN400C', "'CW'", '"', "'"
        ]
        
        # Check for corruption indicators
        for indicator in corruption_indicators:
            if indicator in response:
                self.log_message(f"⚠ Corrupted response detected: {response}")
                return False
        
        # Check for reasonable ASCII content
        try:
            # Should be mostly printable ASCII
            printable_chars = sum(1 for c in response if c.isprintable())
            if len(response) > 0 and printable_chars / len(response) < 0.8:
                self.log_message(f"⚠ Non-printable response detected: {response}")
                return False
        except:
            return False
        
        # Valid responses should contain known keywords or be simple status
        valid_patterns = [
            'DONE', 'COMPLETE', 'OK', 'FINISHED', 'ERROR', 'FAIL', 'INVALID',
            'READY', 'STARTED', 'STOPPED', 'MOVING', 'POSITION', 'STATUS'
        ]
        
        response_upper = response.upper()
        if any(pattern in response_upper for pattern in valid_patterns):
            return True
        
        # Allow simple numeric responses or short status messages
        if len(response) <= 10 and (response.isdigit() or response.isalnum()):
            return True
        
        # If none of the above, might be corrupted
        self.log_message(f"⚠ Suspicious response format: {response}")
        return False
    
    def test_arduino_communication(self):
        """Test Arduino communication quality before sending large commands"""
        if not self.is_connected or not self.arduino:
            return False
        
        self.log_message("Testing Arduino communication quality...")
        
        # Send a simple test command
        test_commands = ["STATUS", "PING", "TEST"]
        successful_responses = 0
        
        for cmd in test_commands:
            try:
                # Clear any pending data
                while self.arduino.in_waiting:
                    self.arduino.readline()
                
                # Send test command
                self.arduino.write(f"{cmd}\n".encode('utf-8'))
                self.arduino.flush()
                
                # Wait for response
                start_time = time.time()
                while (time.time() - start_time) < 2:  # 2 second timeout
                    if self.arduino.in_waiting:
                        response = self.arduino.readline().decode('utf-8', errors='ignore').strip()
                        if response and self.is_valid_arduino_response(response):
                            successful_responses += 1
                            self.log_message(f"✓ Test command '{cmd}' responded: {response}")
                            break
                    time.sleep(0.1)
                else:
                    self.log_message(f"⚠ Test command '{cmd}' timed out")
                    
            except Exception as e:
                self.log_message(f"❌ Test command '{cmd}' failed: {e}")
        
        communication_quality = successful_responses / len(test_commands)
        
        if communication_quality >= 0.7:
            self.log_message(f"✓ Communication quality good ({communication_quality:.1%})")
            return True
        else:
            self.log_message(f"⚠ Communication quality poor ({communication_quality:.1%}) - consider reconnecting")
            return False
    
    def send_command(self, command):
        """Send command to Arduino and wait for completion with enhanced reliability"""
        if not self.is_connected or not self.arduino:
            self.log_message("Error: Not connected to Arduino")
            return False
        
        # Check if this is a large TURN command that needs chunking
        if command.upper().startswith('TURN:'):
            try:
                parts = command.split(':')
                if len(parts) >= 3:
                    steps = int(parts[1])
                    direction = parts[2]
                    
                    # If steps > 10000, break into chunks
                    if steps > 10000:
                        self.log_message(f"Breaking large command into chunks: {command}")
                        return self.send_chunked_turn_command(steps, direction)
            except (ValueError, IndexError):
                pass  # Fall through to normal command processing
        
        return self.send_single_command(command)
    
    def send_chunked_turn_command(self, total_steps, direction):
        """Send large TURN commands in smaller chunks to prevent Arduino buffer overflow"""
        # Test communication quality before sending large command sequence
        if not self.test_arduino_communication():
            self.log_message("❌ Communication test failed - aborting large command")
            return False
        
        chunk_size = 5000  # Send max 5000 steps at a time
        remaining_steps = total_steps
        chunk_number = 1
        total_chunks = (total_steps + chunk_size - 1) // chunk_size
        
        self.log_message(f"Sending {total_steps} steps in {total_chunks} chunks of max {chunk_size} steps each")
        
        while remaining_steps > 0:
            current_chunk_steps = min(chunk_size, remaining_steps)
            chunk_command = f"TURN:{current_chunk_steps}:{direction}"
            
            self.log_message(f"Chunk {chunk_number}/{total_chunks}: {chunk_command}")
            
            # Send this chunk
            success = self.send_single_command(chunk_command)
            if not success:
                self.log_message(f"❌ Failed on chunk {chunk_number}, aborting remaining chunks")
                return False
            
            remaining_steps -= current_chunk_steps
            chunk_number += 1
            
            # Small delay between chunks to let Arduino process
            if remaining_steps > 0:
                time.sleep(0.2)
        
        self.log_message(f"✓ Completed all {total_chunks} chunks for {total_steps} total steps")
        return True
    
    def send_single_command(self, command):
        """Send a single command to Arduino and wait for completion"""
        if not self.is_connected or not self.arduino:
            self.log_message("Error: Not connected to Arduino")
            return False
        
        try:
            # Ensure Arduino connection is still active
            if not self.arduino.is_open:
                self.log_message("Error: Arduino connection lost")
                self.is_connected = False
                return False
            
            # Clear any pending responses to avoid confusion
            while self.arduino.in_waiting:
                old_response = self.arduino.readline().decode('utf-8', errors='ignore').strip()
                if old_response:
                    self.log_message(f"Cleared old response: {old_response}")
            
            # Clear the response queue
            while not self.response_queue.empty():
                try:
                    self.response_queue.get_nowait()
                except:
                    break
            
            # Send command with proper encoding
            command_bytes = f"{command}\n".encode('utf-8')
            self.arduino.write(command_bytes)
            self.arduino.flush()  # Ensure command is sent immediately
            self.log_message(f"Sent: {command}")
            
            # Check if we should wait for confirmation
            wait_for_confirmation = getattr(self, 'wait_confirmation_var', None)
            if wait_for_confirmation and not wait_for_confirmation.get():
                time.sleep(0.1)  # Small delay even if not waiting for confirmation
                return True
            
            # Get timeout setting (default 30 seconds)
            try:
                timeout_seconds = float(getattr(self, 'timeout_var', None).get() if hasattr(self, 'timeout_var') else 30)
            except:
                timeout_seconds = 30
            
            # Wait for Arduino confirmation with improved response detection
            start_time = time.time()
            responses_received = []
            confirmation_received = False
            
            while (time.time() - start_time) < timeout_seconds:
                # Check for immediate Arduino response
                if self.arduino.in_waiting:
                    response = self.arduino.readline().decode('utf-8', errors='ignore').strip()
                    if response:
                        # Validate response before processing
                        if self.is_valid_arduino_response(response):
                            responses_received.append(response)
                            self.log_message(f"Arduino: {response}")
                            
                            # Check for completion confirmations (case insensitive)
                            response_upper = response.upper()
                            if any(keyword in response_upper for keyword in ["DONE", "COMPLETE", "OK", "FINISHED"]):
                                confirmation_received = True
                                break
                            
                            # Check for error responses
                            elif any(keyword in response_upper for keyword in ["ERROR", "FAIL", "INVALID"]):
                                self.log_message(f"❌ Arduino reported error: {response}")
                                return False
                        else:
                            # Skip corrupted responses but continue waiting
                            self.log_message(f"❌ Ignoring corrupted response: {response}")
                            continue
                
                # Also check the response queue
                try:
                    queued_response = self.response_queue.get_nowait()
                    if queued_response and queued_response not in responses_received:
                        # Validate queued response too
                        if self.is_valid_arduino_response(queued_response):
                            responses_received.append(queued_response)
                            response_upper = queued_response.upper()
                            if any(keyword in response_upper for keyword in ["DONE", "COMPLETE", "OK", "FINISHED"]):
                                confirmation_received = True
                                break
                            elif any(keyword in response_upper for keyword in ["ERROR", "FAIL", "INVALID"]):
                                self.log_message(f"❌ Arduino reported error: {queued_response}")
                                return False
                        else:
                            self.log_message(f"❌ Ignoring corrupted queued response: {queued_response}")
                except:
                    pass
                
                time.sleep(0.05)  # Check every 50ms for better responsiveness
            
            if confirmation_received:
                elapsed_time = time.time() - start_time
                self.log_message(f"✓ Command '{command}' completed in {elapsed_time:.2f}s")
                return True
            else:
                # If we get here, Arduino didn't respond in time
                self.log_message(f"⚠ Warning: Arduino did not confirm completion of '{command}' within {timeout_seconds} seconds")
                self.log_message(f"   Responses received: {responses_received}")
                
                # For critical commands, consider this a failure
                if command.upper().startswith(('TURN:', 'REV:')):
                    self.log_message(f"⚠ Movement command may not have completed properly")
                
                return True  # Continue anyway, but log the issue
            
        except serial.SerialException as e:
            self.log_message(f"Serial communication error: {e}")
            self.is_connected = False
            self.status_var.set("Disconnected - Serial Error")
            return False
        except Exception as e:
            self.log_message(f"Send command error: {e}")
            return False
    
    def log_message(self, message):
        """Log message to console with timestamp and color coding"""
        timestamp = time.strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {message}\n"
        
        # Insert in thread-safe way
        def insert_message():
            self.console_text.insert(tk.END, formatted_msg)
            self.console_text.see(tk.END)
            
            # Auto-scroll and limit console size
            lines = int(self.console_text.index('end-1c').split('.')[0])
            if lines > 1000:  # Keep last 1000 lines
                self.console_text.delete(1.0, f"{lines-1000}.0")
        
        # Execute in main thread
        if threading.current_thread() is threading.main_thread():
            insert_message()
        else:
            self.root.after_idle(insert_message)
    
    def check_arduino_connection(self):
        """Check if Arduino connection is still active"""
        if not self.is_connected or not self.arduino:
            return False
        
        try:
            if not self.arduino.is_open:
                self.log_message("Arduino connection lost - port closed")
                self.is_connected = False
                self.status_var.set("Disconnected - Port Closed")
                return False
            return True
        except Exception as e:
            self.log_message(f"Connection check failed: {e}")
            self.is_connected = False
            self.status_var.set("Disconnected - Error")
            return False
    
    def manual_turn(self, direction):
        """Manual turn control with connection verification"""
        if not self.check_arduino_connection():
            messagebox.showerror("Connection Error", "Arduino connection lost. Please reconnect.")
            return
            
        try:
            steps = int(self.manual_steps_var.get())
            if steps <= 0:
                raise ValueError("Steps must be positive")
            command = f"TURN:{steps}:{direction}"
            success = self.send_command(command)
            if not success:
                messagebox.showwarning("Command Failed", f"Manual turn command may have failed: {command}")
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number of steps")
    
    def move_needles(self, direction):
        """Move specific number of needles with connection verification"""
        if not self.check_arduino_connection():
            messagebox.showerror("Connection Error", "Arduino connection lost. Please reconnect.")
            return
            
        try:
            needles = int(self.needles_var.get())
            if needles <= 0:
                raise ValueError("Needles must be positive")
            steps_per_needle = int(self.steps_per_needle_var.get())
            total_steps = needles * steps_per_needle
            command = f"TURN:{total_steps}:{direction}"
            success = self.send_command(command)
            if success:
                self.log_message(f"✓ Moved {needles} needles ({total_steps} steps) {direction}")
            else:
                messagebox.showwarning("Command Failed", f"Needle movement command may have failed")
        except ValueError:
            messagebox.showerror("Error", "Please enter valid positive numbers")
    
    def turn_revolutions(self, direction):
        """Turn specific number of revolutions with connection verification"""
        if not self.check_arduino_connection():
            messagebox.showerror("Connection Error", "Arduino connection lost. Please reconnect.")
            return
            
        try:
            revolutions = float(self.revolutions_var.get())
            if revolutions <= 0:
                raise ValueError("Revolutions must be positive")
            command = f"REV:{revolutions}:{direction}"
            success = self.send_command(command)
            if success:
                self.log_message(f"✓ Completed {revolutions} revolutions {direction}")
            else:
                messagebox.showwarning("Command Failed", f"Revolution command may have failed")
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number of revolutions")
    
    def emergency_stop(self):
        """Emergency stop with immediate action"""
        self.log_message("🛑 EMERGENCY STOP ACTIVATED!")
        
        # Set stop flags immediately
        self.stop_script = True
        if self.progress_window:
            self.progress_window.stop_execution()
        
        # Try to send stop command to Arduino
        if self.is_connected and self.arduino:
            try:
                # Send emergency stop immediately, don't wait for confirmation
                self.arduino.write(b"STOP\n")
                self.arduino.flush()
                self.log_message("Emergency stop command sent to Arduino")
            except Exception as e:
                self.log_message(f"Could not send emergency stop to Arduino: {e}")
        
        messagebox.showwarning("Emergency Stop", "Emergency stop activated! All operations halted.")
    
    def apply_speed(self):
        """Apply speed setting with validation"""
        if not self.check_arduino_connection():
            messagebox.showerror("Connection Error", "Arduino connection lost. Please reconnect.")
            return
            
        try:
            speed = int(self.speed_var.get())
            if speed < 500 or speed > 3000:
                raise ValueError("Speed must be between 500-3000 microseconds")
            self.config["default_speed"] = speed
            command = f"SPEED:{speed}"
            success = self.send_command(command)
            if success:
                self.log_message(f"✓ Motor speed set to {speed} microseconds")
            else:
                messagebox.showwarning("Command Failed", "Speed change command may have failed")
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid speed value: {e}")
    
    def apply_microstepping(self):
        """Apply microstepping setting with validation"""
        if not self.check_arduino_connection():
            messagebox.showerror("Connection Error", "Arduino connection lost. Please reconnect.")
            return
            
        try:
            micro = int(self.micro_var.get())
            valid_values = [1, 2, 4, 8, 16, 32]
            if micro not in valid_values:
                raise ValueError(f"Microstepping must be one of: {valid_values}")
            self.config["microstepping"] = micro
            command = f"MICRO:{micro}"
            success = self.send_command(command)
            if success:
                self.log_message(f"✓ Microstepping set to 1/{micro}")
                messagebox.showinfo("Microstepping Changed", 
                                  f"Microstepping set to 1/{micro}\n\nIMPORTANT: Ensure your driver jumpers match this setting!")
            else:
                messagebox.showwarning("Command Failed", "Microstepping change command may have failed")
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid microstepping value: {e}")
    
    def get_status(self):
        """Get Arduino status with connection verification"""
        if not self.check_arduino_connection():
            messagebox.showerror("Connection Error", "Arduino connection lost. Please reconnect.")
            return
            
        success = self.send_command("STATUS")
        if not success:
            messagebox.showwarning("Command Failed", "Status request may have failed")
    
    def save_settings(self):
        """Save current settings"""
        try:
            self.config["steps_per_needle"] = int(self.steps_per_needle_var.get())
            self.config["default_speed"] = int(self.speed_var.get())
            self.config["microstepping"] = int(self.micro_var.get())
            self.config["com_port"] = self.port_var.get()
            self.save_config()
            self.log_message("Settings saved")
            messagebox.showinfo("Success", "Settings saved successfully")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save settings: {e}")
    
    def on_preset_change(self, event=None):
        """Handle preset pattern change"""
        preset = self.preset_var.get()
        if preset == "color_stripes":
            self.color_change_var.set("every_2_rows")
        elif preset == "custom_rows":
            self.color_change_var.set("custom")
        else:
            self.color_change_var.set("none")
    
    def generate_pattern(self):
        """Generate knitting pattern script"""
        try:
            width = int(self.pattern_width_var.get())
            length = int(self.pattern_length_var.get())
            pattern_type = self.pattern_type_var.get()
            speed = self.script_speed_var.get()
            pause = float(self.pause_var.get())
            
            # Calculate steps per row using correct Sentro calibration
            steps_per_needle = int(self.steps_per_needle_var.get())
            steps_per_row = width * steps_per_needle
            total_steps = steps_per_row * length
            
            # Generate script with calculation info
            script_lines = []
            script_lines.append(f"# Generated Pattern: {self.pattern_name_var.get()}")
            script_lines.append(f"# Description: {self.pattern_desc_var.get()}")
            script_lines.append(f"# Width: {width} needles, Length: {length} rows")
            script_lines.append(f"# Type: {pattern_type}")
            script_lines.append(f"# Calculation: {steps_per_needle} steps/needle × {width} needles × {length} rows = {total_steps:,} total steps")
            script_lines.append("")
            script_lines.append(f"SPEED:{speed}")
            script_lines.append("")
            
            for row in range(1, length + 1):
                if pattern_type == "circular":
                    # Circular knitting - always same direction
                    script_lines.append(f"# Row {row}")
                    script_lines.append(f"TURN:{steps_per_row}:CW")
                else:
                    # Flat knitting - alternate directions
                    direction = "CW" if row % 2 == 1 else "CCW"
                    script_lines.append(f"# Row {row}")
                    script_lines.append(f"TURN:{steps_per_row}:{direction}")
                
                # Add pause between rows
                if pause > 0:
                    script_lines.append(f"WAIT:{pause}")
                
                # Handle color changes
                color_change = self.color_change_var.get()
                if color_change != "none":
                    if ((color_change == "every_row") or
                        (color_change == "every_2_rows" and row % 2 == 0) or
                        (color_change == "every_5_rows" and row % 5 == 0) or
                        (color_change == "every_10_rows" and row % 10 == 0)):
                        script_lines.append("# PAUSE FOR COLOR CHANGE")
                        script_lines.append("WAIT:5")
                
                script_lines.append("")
            
            # Display generated script
            script_content = "\n".join(script_lines)
            self.script_text.delete(1.0, tk.END)
            self.script_text.insert(1.0, script_content)
            
            # Update pattern visualization
            self.draw_pattern_preview(width, length, pattern_type)
            
            self.current_pattern = {
                'name': self.pattern_name_var.get(),
                'description': self.pattern_desc_var.get(),
                'width': width,
                'length': length,
                'type': pattern_type,
                'script': script_content
            }
            self.pattern_modified = False
            
            # Update status labels
            if hasattr(self, 'pattern_status_label'):
                self.pattern_status_label.config(text=f"Pattern generated: {width}×{length} {pattern_type}", fg="green")
            if hasattr(self, 'script_status_label'):
                self.script_status_label.config(text=f"Script ready ({len(script_lines)} commands)", fg="green")
            
            self.log_message(f"Pattern generated: {width}x{length} {pattern_type}")
            
        except ValueError as e:
            messagebox.showerror("Error", "Please enter valid numbers for dimensions")
            if hasattr(self, 'pattern_status_label'):
                self.pattern_status_label.config(text="Error: Invalid input values", fg="red")
        except Exception as e:
            messagebox.showerror("Error", f"Could not generate pattern: {e}")
            if hasattr(self, 'pattern_status_label'):
                self.pattern_status_label.config(text="Error generating pattern", fg="red")
    
    def draw_pattern_preview(self, width, length, pattern_type):
        """Draw pattern preview on canvas"""
        self.pattern_canvas.delete("all")
        
        # Canvas dimensions
        canvas_width = self.pattern_canvas.winfo_width() if self.pattern_canvas.winfo_width() > 1 else 400
        canvas_height = max(200, length * 10)
        
        self.pattern_canvas.config(scrollregion=(0, 0, canvas_width, canvas_height))
        
        # Calculate cell size
        cell_width = max(5, min(20, canvas_width // width))
        cell_height = 8
        
        # Draw grid
        for row in range(length):
            y = row * cell_height + 10
            for col in range(width):
                x = col * cell_width + 10
                
                # Color coding based on pattern type
                if pattern_type == "circular":
                    color = "#87CEEB"  # Light blue for circular
                else:
                    # Alternate colors for flat knitting to show direction changes
                    color = "#87CEEB" if row % 2 == 0 else "#98FB98"  # Light blue/green
                
                self.pattern_canvas.create_rectangle(
                    x, y, x + cell_width, y + cell_height,
                    fill=color, outline="gray", width=1
                )
        
        # Add labels
        self.pattern_canvas.create_text(10, canvas_height - 30, anchor="w", 
                                       text=f"Pattern: {width} needles × {length} rows ({pattern_type})")
    
    def save_pattern(self):
        """Save pattern to file"""
        if not self.current_pattern:
            messagebox.showwarning("Warning", "No pattern to save")
            return
        
        filename = filedialog.asksaveasfilename(
            title="Save Pattern",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                # Save as text format for easy reading and uploading
                with open(filename, 'w') as f:
                    f.write("# SENTRO KNITTING PATTERN\n")
                    f.write("# ========================\n\n")
                    f.write(f"# Pattern Name: {self.current_pattern.get('name', 'Unnamed')}\n")
                    f.write(f"# Description: {self.current_pattern.get('description', '')}\n")
                    f.write(f"# Width: {self.current_pattern.get('width', 0)} needles\n")
                    f.write(f"# Length: {self.current_pattern.get('length', 0)} rows\n")
                    f.write(f"# Type: {self.current_pattern.get('type', 'circular')}\n")
                    f.write(f"# Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write("# SCRIPT:\n")
                    f.write("# -------\n")
                    f.write(self.current_pattern.get('script', ''))
                    
                    # Also save as JSON format in the same file for complete data
                    f.write("\n\n# PATTERN DATA (JSON):\n")
                    f.write("# " + "="*50 + "\n")
                    json_data = json.dumps(self.current_pattern, indent=2)
                    for line in json_data.split('\n'):
                        f.write(f"# {line}\n")
                
                self.log_message(f"Pattern saved: {filename}")
                if hasattr(self, 'pattern_status_label'):
                    self.pattern_status_label.config(text="Pattern saved successfully", fg="green")
                messagebox.showinfo("Success", "Pattern saved successfully as text file")
            except Exception as e:
                if hasattr(self, 'pattern_status_label'):
                    self.pattern_status_label.config(text="Error saving pattern", fg="red")
                messagebox.showerror("Error", f"Could not save pattern: {e}")
    
    def load_pattern(self):
        """Load pattern from file"""
        filename = filedialog.askopenfilename(
            title="Load Pattern",
            filetypes=[("Text files", "*.txt"), ("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'r') as f:
                    content = f.read()
                
                pattern = None
                
                # Try to load as text format first
                if filename.endswith('.txt') or '# SENTRO KNITTING PATTERN' in content:
                    pattern = self.parse_text_pattern(content)
                else:
                    # Try to load as JSON
                    try:
                        pattern = json.loads(content)
                    except json.JSONDecodeError:
                        # If JSON fails, try to parse as text
                        pattern = self.parse_text_pattern(content)
                
                if pattern:
                    # Load pattern data into GUI
                    self.pattern_name_var.set(pattern.get('name', 'Loaded Pattern'))
                    self.pattern_desc_var.set(pattern.get('description', ''))
                    self.pattern_width_var.set(str(pattern.get('width', 20)))
                    self.pattern_length_var.set(str(pattern.get('length', 10)))
                    self.pattern_type_var.set(pattern.get('type', 'circular'))
                    
                    # Display script
                    self.script_text.delete(1.0, tk.END)
                    self.script_text.insert(1.0, pattern.get('script', ''))
                    
                    # Update preview
                    self.draw_pattern_preview(pattern.get('width', 20), pattern.get('length', 10), pattern.get('type', 'circular'))
                    
                    self.current_pattern = pattern
                    self.pattern_modified = False
                    
                    if hasattr(self, 'pattern_status_label'):
                        self.pattern_status_label.config(text="Pattern loaded successfully", fg="green")
                    if hasattr(self, 'script_status_label'):
                        self.script_status_label.config(text="Script loaded and ready", fg="green")
                    
                    self.log_message(f"Pattern loaded: {filename}")
                    messagebox.showinfo("Success", "Pattern loaded successfully")
                else:
                    raise Exception("Could not parse pattern file")
                
            except Exception as e:
                if hasattr(self, 'pattern_status_label'):
                    self.pattern_status_label.config(text="Error loading pattern", fg="red")
                messagebox.showerror("Error", f"Could not load pattern: {e}")
    
    def parse_text_pattern(self, content):
        """Parse text format pattern file"""
        pattern = {}
        script_lines = []
        in_script = False
        in_json = False
        json_lines = []
        
        for line in content.split('\n'):
            if '# Pattern Name:' in line:
                pattern['name'] = line.split(':', 1)[1].strip()
            elif '# Description:' in line:
                pattern['description'] = line.split(':', 1)[1].strip()
            elif '# Width:' in line:
                try:
                    pattern['width'] = int(line.split(':')[1].split()[0])
                except:
                    pattern['width'] = 20
            elif '# Length:' in line:
                try:
                    pattern['length'] = int(line.split(':')[1].split()[0])
                except:
                    pattern['length'] = 10
            elif '# Type:' in line:
                pattern['type'] = line.split(':', 1)[1].strip()
            elif '# SCRIPT:' in line:
                in_script = True
                continue
            elif '# PATTERN DATA (JSON):' in line:
                in_script = False
                in_json = True
                continue
            elif in_json and line.startswith('# {'):
                # Try to extract JSON data
                try:
                    json_start = content.find('# {')
                    if json_start != -1:
                        json_content = content[json_start:]
                        # Remove '# ' from each line
                        clean_json = '\n'.join(line[2:] if line.startswith('# ') else line 
                                             for line in json_content.split('\n') 
                                             if line.strip() and not line.startswith('# ='))
                        json_data = json.loads(clean_json)
                        return json_data
                except:
                    pass
                break
            elif in_script and not line.startswith('#'):
                if line.strip():
                    script_lines.append(line)
        
        # Build script from collected lines
        pattern['script'] = '\n'.join(script_lines)
        
        # Set defaults for missing values
        pattern.setdefault('name', 'Imported Pattern')
        pattern.setdefault('description', '')
        pattern.setdefault('width', 20)
        pattern.setdefault('length', 10)
        pattern.setdefault('type', 'circular')
        
        return pattern
    
    def execute_script(self):
        """Execute the generated script"""
        script_content = self.script_text.get(1.0, tk.END).strip()
        if not script_content:
            messagebox.showwarning("Warning", "No script to execute")
            return
        
        self.execute_knitting_script(script_content)
    
    def save_script(self):
        """Save script to file"""
        script_content = self.script_text.get(1.0, tk.END).strip()
        if not script_content:
            messagebox.showwarning("Warning", "No script to save")
            return
        
        filename = filedialog.asksaveasfilename(
            title="Save Script",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    # Add header information
                    f.write("# SENTRO KNITTING MACHINE SCRIPT\n")
                    f.write("# ===============================\n\n")
                    
                    # Add pattern information if available
                    if self.current_pattern:
                        f.write(f"# Pattern: {self.current_pattern.get('name', 'Unnamed')}\n")
                        f.write(f"# Description: {self.current_pattern.get('description', '')}\n")
                        f.write(f"# Dimensions: {self.current_pattern.get('width', 'N/A')} needles × {self.current_pattern.get('length', 'N/A')} rows\n")
                        f.write(f"# Type: {self.current_pattern.get('type', 'N/A')}\n")
                    else:
                        f.write("# Custom Script\n")
                    
                    f.write(f"# Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"# Device: Sentro Knitting Machine\n\n")
                    
                    # Add usage instructions
                    f.write("# INSTRUCTIONS:\n")
                    f.write("# 1. Connect your Arduino to the Sentro machine\n")
                    f.write("# 2. Load this script in the Sentro controller software\n")
                    f.write("# 3. Ensure your yarn is properly threaded\n")
                    f.write("# 4. Click 'Execute Script' to start knitting\n\n")
                    
                    # Add command reference
                    f.write("# COMMAND REFERENCE:\n")
                    f.write("# TURN:<steps>:<CW|CCW> - Turn motor specific steps\n")
                    f.write("# REV:<revolutions>:<CW|CCW> - Turn motor revolutions\n")
                    f.write("# SPEED:<microseconds> - Set motor step delay\n")
                    f.write("# WAIT:<seconds> - Pause execution\n")
                    f.write("# Lines starting with # are comments\n\n")
                    
                    f.write("# SCRIPT START:\n")
                    f.write("# " + "="*40 + "\n\n")
                    
                    # Write the actual script
                    f.write(script_content)
                    
                    # Add footer
                    f.write(f"\n\n# SCRIPT END\n")
                    f.write("# Generated by Sentro Knitting Machine Controller\n")
                
                self.log_message(f"Script saved: {filename}")
                if hasattr(self, 'script_status_label'):
                    self.script_status_label.config(text="Script saved successfully", fg="green")
                messagebox.showinfo("Success", "Script saved successfully with instructions")
            except Exception as e:
                if hasattr(self, 'script_status_label'):
                    self.script_status_label.config(text="Error saving script", fg="red")
                messagebox.showerror("Error", f"Could not save script: {e}")
    
    def clear_script(self):
        """Clear the script text area"""
        self.script_text.delete(1.0, tk.END)
        self.pattern_canvas.delete("all")
        self.current_pattern = None
        if hasattr(self, 'script_status_label'):
            self.script_status_label.config(text="Script cleared", fg="gray")
    
    def copy_script_to_clipboard(self):
        """Copy script to clipboard"""
        script_content = self.script_text.get(1.0, tk.END).strip()
        if not script_content:
            messagebox.showwarning("Warning", "No script to copy")
            return
        
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(script_content)
            if hasattr(self, 'script_status_label'):
                self.script_status_label.config(text="Script copied to clipboard", fg="green")
            self.log_message("Script copied to clipboard")
        except Exception as e:
            messagebox.showerror("Error", f"Could not copy to clipboard: {e}")
    
    def export_for_sharing(self):
        """Export script in a shareable format"""
        script_content = self.script_text.get(1.0, tk.END).strip()
        if not script_content:
            messagebox.showwarning("Warning", "No script to export")
            return
        
        filename = filedialog.asksaveasfilename(
            title="Export for Sharing",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    # Create a comprehensive sharing document
                    f.write("SENTRO KNITTING MACHINE - SHARED PATTERN\n")
                    f.write("="*50 + "\n\n")
                    
                    if self.current_pattern:
                        f.write(f"PATTERN: {self.current_pattern.get('name', 'Unnamed Pattern')}\n")
                        if self.current_pattern.get('description'):
                            f.write(f"DESCRIPTION: {self.current_pattern.get('description')}\n")
                        f.write(f"DIMENSIONS: {self.current_pattern.get('width', 'N/A')} needles × {self.current_pattern.get('length', 'N/A')} rows\n")
                        f.write(f"TYPE: {self.current_pattern.get('type', 'N/A').title()}\n")
                    else:
                        f.write("CUSTOM SCRIPT\n")
                    
                    f.write(f"SHARED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    
                    f.write("WHAT YOU NEED:\n")
                    f.write("- Sentro knitting machine (22 or 48 needle)\n")
                    f.write("- Arduino with stepper motor driver\n")
                    f.write("- Sentro controller software\n")
                    f.write("- Appropriate yarn for your project\n\n")
                    
                    f.write("HOW TO USE:\n")
                    f.write("1. Set up your Sentro machine with Arduino controller\n")
                    f.write("2. Thread your yarn through all needles\n")
                    f.write("3. Load this script in the Sentro controller software\n")
                    f.write("4. Connect to your Arduino and execute the script\n")
                    f.write("5. Monitor the knitting process and change colors as prompted\n\n")
                    
                    f.write("KNITTING SCRIPT:\n")
                    f.write("-" * 20 + "\n")
                    f.write(script_content)
                    f.write("\n" + "-" * 20 + "\n\n")
                    
                    f.write("TROUBLESHOOTING:\n")
                    f.write("- If stitches are dropped, check needle alignment\n")
                    f.write("- If motor skips, reduce speed or check belt tension\n")
                    f.write("- For color changes, pause and manually switch yarn\n\n")
                    
                    f.write("Generated by Sentro Knitting Machine Controller\n")
                    f.write("Open source project - customize as needed!\n")
                
                self.log_message(f"Pattern exported for sharing: {filename}")
                if hasattr(self, 'script_status_label'):
                    self.script_status_label.config(text="Pattern exported successfully", fg="green")
                messagebox.showinfo("Success", "Pattern exported with instructions for easy sharing!")
                
            except Exception as e:
                messagebox.showerror("Error", f"Could not export pattern: {e}")
    
    def show_templates(self):
        """Show template selection dialog"""
        template_window = tk.Toplevel(self.root)
        template_window.title("Quick Start Templates")
        template_window.geometry("600x400")
        template_window.resizable(False, False)
        template_window.transient(self.root)
        template_window.grab_set()
        
        # Center the window
        template_window.geometry("+%d+%d" % (self.root.winfo_rootx() + 50, self.root.winfo_rooty() + 50))
        
        # Title
        title_label = tk.Label(template_window, text="Quick Start Templates", 
                              font=("Arial", 16, "bold"))
        title_label.pack(pady=10)
        
        # Template list
        templates_frame = ttk.LabelFrame(template_window, text="Choose a Template", padding=10)
        templates_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Template options
        templates = [
            ("Simple Tube", "Basic circular knitting - great for beginners", 
             {"name": "Simple Tube", "width": 48, "length": 20, "type": "circular", "description": "Basic tube pattern using all 48 needles"}),
            ("Small Hat", "Circular pattern for a simple beanie", 
             {"name": "Simple Hat", "width": 48, "length": 30, "type": "circular", "description": "Basic hat pattern"}),
            ("Dishcloth", "Flat rectangular pattern for kitchen use", 
             {"name": "Dishcloth", "width": 48, "length": 25, "type": "flat", "description": "Square dishcloth"}),
            ("Scarf", "Long flat pattern perfect for scarves", 
             {"name": "Scarf", "width": 48, "length": 100, "type": "flat", "description": "Long scarf pattern"}),
            ("Color Stripes", "Tube with regular color changes", 
             {"name": "Striped Tube", "width": 48, "length": 40, "type": "circular", "description": "Colorful striped pattern"}),
            ("Test Pattern", "Small pattern for testing your setup", 
             {"name": "Test", "width": 24, "length": 5, "type": "circular", "description": "Quick test pattern using half needles"})
        ]
        
        def load_template(template_data):
            # Load template data into GUI
            self.pattern_name_var.set(template_data["name"])
            self.pattern_desc_var.set(template_data["description"])
            self.pattern_width_var.set(str(template_data["width"]))
            self.pattern_length_var.set(str(template_data["length"]))
            self.pattern_type_var.set(template_data["type"])
            
            # Set appropriate preset for striped pattern
            if "stripe" in template_data["name"].lower():
                self.preset_var.set("color_stripes")
                self.color_change_var.set("every_2_rows")
            else:
                self.preset_var.set("stockinette")
                self.color_change_var.set("none")
            
            # Update status
            if hasattr(self, 'pattern_status_label'):
                self.pattern_status_label.config(text=f"Template loaded: {template_data['name']}", fg="blue")
            
            template_window.destroy()
            self.log_message(f"Template loaded: {template_data['name']}")
        
        # Create buttons for each template
        for i, (name, description, data) in enumerate(templates):
            template_frame = tk.Frame(templates_frame)
            template_frame.pack(fill=tk.X, pady=2)
            
            btn = ttk.Button(template_frame, text=name, 
                           command=lambda d=data: load_template(d))
            btn.pack(side=tk.LEFT, padx=5)
            
            desc_label = tk.Label(template_frame, text=description, 
                                 font=("Arial", 9), fg="gray")
            desc_label.pack(side=tk.LEFT, padx=10)
        
        # Close button
        ttk.Button(template_window, text="Close", 
                  command=template_window.destroy).pack(pady=10)
    
    def upload_script_file(self):
        """Upload a script file"""
        filename = filedialog.askopenfilename(
            title="Upload Script File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'r') as f:
                    content = f.read()
                
                # Parse the content to extract just the script commands
                script_content = self.extract_script_from_text(content)
                
                self.uploaded_script = script_content
                self.uploaded_script_text.delete(1.0, tk.END)
                self.uploaded_script_text.insert(1.0, script_content)
                
                self.upload_status_label.config(text=f"Uploaded: {os.path.basename(filename)}", fg="green")
                if hasattr(self, 'upload_execution_status'):
                    self.upload_execution_status.config(text="Script uploaded - ready to validate and execute", fg="blue")
                self.log_message(f"Script uploaded: {filename}")
                
                # Auto-validate the uploaded script
                self.validate_uploaded_script()
                
            except Exception as e:
                messagebox.showerror("Error", f"Could not upload script: {e}")
    
    def extract_script_from_text(self, content):
        """Extract script commands from text file, removing headers and comments"""
        lines = content.split('\n')
        script_lines = []
        in_script_section = False
        
        for line in lines:
            # Skip empty lines and pure comment lines at the start
            if not line.strip():
                if script_lines:  # Keep empty lines within the script
                    script_lines.append(line)
                continue
                
            # Check for script start markers
            if '# SCRIPT START:' in line or '# SCRIPT:' in line:
                in_script_section = True
                continue
            elif '# SCRIPT END' in line:
                break
            elif line.startswith('# ') and not in_script_section:
                # Skip header comments before script starts
                continue
            
            # Once we find the first command or we're in script section, include everything
            if (line.strip().startswith(('TURN:', 'REV:', 'SPEED:', 'MICRO:', 'WAIT:', 'STOP', 'STATUS')) or 
                line.startswith('#') and not line.startswith('# ') or 
                in_script_section):
                script_lines.append(line)
                in_script_section = True
        
        return '\n'.join(script_lines).strip()
    
    def validate_uploaded_script(self):
        """Validate the uploaded script"""
        if not self.uploaded_script:
            messagebox.showwarning("Warning", "No script uploaded")
            return
        
        validation_result = self.validate_script(self.uploaded_script)
        
        self.validation_result.delete(1.0, tk.END)
        if validation_result['valid']:
            self.validation_result.insert(1.0, "✓ Script is valid!\n\nScript contains:\n")
            for command, count in validation_result['commands'].items():
                self.validation_result.insert(tk.END, f"- {count} {command} commands\n")
        else:
            self.validation_result.insert(1.0, "✗ Script has errors:\n\n")
            for error in validation_result['errors']:
                self.validation_result.insert(tk.END, f"- {error}\n")
    
    def validate_script(self, script_content):
        """Validate script syntax"""
        lines = script_content.strip().split('\n')
        errors = []
        commands = {}
        
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if line and not line.startswith('#'):
                # Validate command syntax
                if line.startswith('TURN:'):
                    if not re.match(r'^TURN:\d+:(CW|CCW)$', line):
                        errors.append(f"Line {i}: Invalid TURN command format - '{line}'")
                        # Debug: Log the specific issue
                        self.log_message(f"🔍 Debug: TURN validation failed for line {i}: '{line}'")
                    else:
                        commands['TURN'] = commands.get('TURN', 0) + 1
                        # Debug: Log successful TURN command validation
                        if commands['TURN'] <= 3:  # Only log first 3 to avoid spam
                            self.log_message(f"🔍 Debug: TURN command validated successfully: '{line}'")
                elif line.startswith('REV:'):
                    if not re.match(r'^REV:\d*\.?\d+:(CW|CCW)$', line):
                        errors.append(f"Line {i}: Invalid REV command format - '{line}'")
                    else:
                        commands['REV'] = commands.get('REV', 0) + 1
                elif line.startswith('SPEED:'):
                    if not re.match(r'^SPEED:\d+$', line):
                        errors.append(f"Line {i}: Invalid SPEED command format")
                    else:
                        commands['SPEED'] = commands.get('SPEED', 0) + 1
                elif line.startswith('MICRO:'):
                    if not re.match(r'^MICRO:[1-9]\d*$', line):
                        errors.append(f"Line {i}: Invalid MICRO command format")
                    else:
                        commands['MICRO'] = commands.get('MICRO', 0) + 1
                elif line.startswith('WAIT:'):
                    if not re.match(r'^WAIT:\d*\.?\d+$', line):
                        errors.append(f"Line {i}: Invalid WAIT command format")
                    else:
                        commands['WAIT'] = commands.get('WAIT', 0) + 1
                elif line == 'STOP':
                    commands['STOP'] = commands.get('STOP', 0) + 1
                elif line == 'STATUS':
                    commands['STATUS'] = commands.get('STATUS', 0) + 1
                else:
                    errors.append(f"Line {i}: Unknown command '{line}'")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'commands': commands
        }
    
    def execute_uploaded_script(self):
        """Execute the uploaded script"""
        if not self.uploaded_script:
            messagebox.showwarning("Warning", "No script uploaded")
            if hasattr(self, 'upload_execution_status'):
                self.upload_execution_status.config(text="No script to execute - upload a file first", fg="red")
            return
        
        if hasattr(self, 'upload_execution_status'):
            self.upload_execution_status.config(text="Starting script execution...", fg="green")
        self.execute_knitting_script(self.uploaded_script)
    
    def clear_uploaded_script(self):
        """Clear uploaded script"""
        self.uploaded_script = None
        self.uploaded_script_text.delete(1.0, tk.END)
        self.validation_result.delete(1.0, tk.END)
        self.upload_status_label.config(text="No file uploaded", fg="gray")
        if hasattr(self, 'upload_execution_status'):
            self.upload_execution_status.config(text="Upload a script file to begin", fg="gray")
    
    def execute_knitting_script(self, script_content):
        """Execute a knitting script with progress tracking and robust error handling"""
        if not self.check_arduino_connection():
            messagebox.showerror("Connection Error", "Arduino connection lost. Please reconnect before executing script.")
            return
        
        # Debug: Log script content size
        self.log_message(f"🔍 Debug: Script content length: {len(script_content)} characters")
        
        # Validate script first
        validation = self.validate_script(script_content)
        self.log_message(f"🔍 Debug: Script validation - Valid: {validation['valid']}, Errors: {len(validation.get('errors', []))}")
        
        if not validation['valid']:
            result = messagebox.askyesno("Script Errors", 
                                       f"Script has {len(validation['errors'])} errors:\n\n" +
                                       "\n".join(validation['errors'][:5]) + 
                                       ("\n... and more" if len(validation['errors']) > 5 else "") +
                                       "\n\nExecute anyway?")
            if not result:
                self.log_message("🔍 Debug: User cancelled execution due to validation errors")
                return
        
        # Count total rows for progress tracking
        lines = script_content.strip().split('\n')
        turn_commands = sum(1 for line in lines if line.strip().startswith('TURN:'))
        rev_commands = sum(1 for line in lines if line.strip().startswith('REV:'))
        total_rows = turn_commands + rev_commands
        
        self.log_message(f"🔍 Debug: Found {turn_commands} TURN commands, {rev_commands} REV commands = {total_rows} total rows")
        
        if total_rows == 0:
            messagebox.showwarning("Empty Script", "No knitting commands found in script")
            self.log_message("🔍 Debug: No knitting commands found in script")
            return
        
        # Debug: Show sample commands
        sample_commands = [line.strip() for line in lines[:5] if line.strip() and not line.strip().startswith('#')]
        self.log_message(f"🔍 Debug: Sample commands: {sample_commands}")
        
        # Final confirmation
        estimated_time = total_rows * 2  # Rough estimate: 2 minutes per row
        result = messagebox.askyesno("Start Knitting", 
                                   f"Ready to start knitting:\n\n"
                                   f"• {total_rows} rows to knit\n"
                                   f"• Estimated time: {estimated_time} minutes\n"
                                   f"• Arduino connected: {self.arduino.port if self.arduino else 'Unknown'}\n\n"
                                   f"Make sure your knitting machine is ready.\n\n"
                                   f"Start knitting now?")
        if not result:
            self.log_message("🔍 Debug: User cancelled execution at confirmation dialog")
            return
        
        # Create progress window
        self.log_message("🔍 Debug: Creating progress window...")
        self.progress_window = ProgressWindow(self, total_rows)
        self.progress_window.is_running = True  # Mark as running
        
        # Reset control flags
        self.pause_script = False
        self.stop_script = False
        
        self.log_message("🔍 Debug: Starting execution thread...")
        
        # Execute script in separate thread
        script_thread = threading.Thread(
            target=self._execute_script_thread, 
            args=(script_content, total_rows),
            daemon=True
        )
        script_thread.start()
        
        self.log_message("🔍 Debug: Script execution thread started successfully!")
    
    def _execute_script_thread(self, script_content, total_rows):
        """Execute script in separate thread with enhanced error handling"""
        lines = script_content.strip().split('\n')
        current_row = 0
        current_needle = 0
        failed_commands = 0
        max_failures = 5  # Stop execution if too many commands fail
        
        # Debug: Log thread start
        self.root.after(0, self.log_message, "🔍 Debug: Script execution thread started")
        
        try:
            self.root.after(0, self.progress_window.log_activity, "🚀 Starting knitting script execution...")
            
            # Debug: Log script size and commands
            valid_commands = [l for l in lines if l.strip() and not l.strip().startswith('#')]
            self.root.after(0, self.progress_window.log_activity, f"Total commands to process: {len(valid_commands)}")
            self.root.after(0, self.log_message, f"🔍 Debug: Processing {len(valid_commands)} commands from {len(lines)} total lines")
            
            for line_num, line in enumerate(lines, 1):
                # Check for stop signal
                if self.stop_script:
                    self.root.after(0, self.progress_window.log_activity, "❌ Script execution stopped by user")
                    break
                
                # Check for pause signal
                while self.pause_script and not self.stop_script:
                    time.sleep(0.1)
                
                line = line.strip()
                if not line or line.startswith('#'):
                    continue  # Skip empty lines and comments
                
                # Verify Arduino connection before each command
                if not self.check_arduino_connection():
                    self.root.after(0, self.progress_window.log_activity, "❌ Arduino connection lost during execution")
                    self.root.after(0, lambda: messagebox.showerror("Connection Lost", "Arduino connection lost during script execution!"))
                    break
                
                # Update progress for movement commands
                if line.startswith('TURN:') or line.startswith('REV:'):
                    current_row += 1
                    current_needle = 0
                    
                    # Get pattern width for progress calculation
                    width = int(self.pattern_width_var.get()) if hasattr(self, 'pattern_width_var') else 48
                    
                    self.root.after(0, self.progress_window.update_progress, 
                                  current_row, current_needle, f"Starting Row {current_row}: {line}")
                    self.root.after(0, self.progress_window.log_activity, f"📍 Row {current_row}/{total_rows}: {line}")
                    
                    # Send command to Arduino and wait for completion
                    command_start_time = time.time()
                    command_success = self.send_command(line)
                    command_duration = time.time() - command_start_time
                    
                    if command_success and not self.stop_script:
                        # Simulate knitting progress for visual feedback
                        try:
                            if line.startswith('TURN:'):
                                steps = int(line.split(':')[1])
                                steps_per_needle = int(self.steps_per_needle_var.get()) if hasattr(self, 'steps_per_needle_var') else 1000
                                estimated_needles = min(width, steps // steps_per_needle)
                            else:
                                estimated_needles = width
                            
                            # Visual progress update every few needles
                            progress_interval = max(1, estimated_needles // 10)  # Update 10 times per row
                            
                            for needle in range(1, estimated_needles + 1, progress_interval):
                                if self.stop_script:
                                    break
                                
                                current_needle = needle
                                self.root.after(0, self.progress_window.update_progress, 
                                              current_row, current_needle, f"Row {current_row}: Needle {needle}/{estimated_needles}")
                                
                                # Small delay for visual feedback (don't delay actual Arduino operation)
                                time.sleep(0.02)
                            
                            # Final update for completed row
                            self.root.after(0, self.progress_window.update_progress, 
                                          current_row, estimated_needles, f"Row {current_row} completed")
                            self.root.after(0, self.progress_window.log_activity, 
                                          f"✅ Row {current_row} completed successfully in {command_duration:.1f}s")
                            
                        except Exception as e:
                            self.root.after(0, self.progress_window.log_activity, f"⚠ Progress calculation error: {e}")
                    
                    elif not command_success:
                        failed_commands += 1
                        self.root.after(0, self.progress_window.log_activity, 
                                      f"❌ Row {current_row} FAILED - Command: {line}")
                        
                        if failed_commands >= max_failures:
                            self.root.after(0, self.progress_window.log_activity, 
                                          f"❌ Too many failures ({failed_commands}). Stopping execution for safety.")
                            self.root.after(0, lambda: messagebox.showerror("Execution Failed", 
                                          f"Script execution stopped due to {failed_commands} failed commands.\n\nCheck Arduino connection and try again."))
                            break
                        else:
                            self.root.after(0, self.progress_window.log_activity, 
                                          f"⚠ Continuing despite failure ({failed_commands}/{max_failures} failures)")
                
                else:
                    # Other commands (SPEED, WAIT, etc.)
                    self.root.after(0, self.progress_window.log_activity, f"🔧 Command: {line}")
                    command_success = self.send_command(line)
                    
                    if not command_success:
                        failed_commands += 1
                        self.root.after(0, self.progress_window.log_activity, f"❌ Command failed: {line}")
                    
                    # Handle wait commands with real timing
                    if line.startswith('WAIT:'):
                        try:
                            wait_time = float(line.split(':')[1])
                            self.root.after(0, self.progress_window.update_progress, 
                                          current_row, current_needle, f"Waiting {wait_time} seconds...")
                            
                            # Count down the wait time for user feedback
                            for remaining in range(int(wait_time), 0, -1):
                                if self.stop_script:
                                    break
                                self.root.after(0, self.progress_window.update_progress, 
                                              current_row, current_needle, f"Waiting {remaining} seconds...")
                                time.sleep(1)
                            
                            if wait_time % 1 > 0:  # Handle fractional seconds
                                time.sleep(wait_time % 1)
                            
                            self.root.after(0, self.progress_window.log_activity, f"⏰ Wait completed ({wait_time}s)")
                                
                        except Exception as e:
                            self.root.after(0, self.progress_window.log_activity, f"❌ Wait command error: {e}")
                            time.sleep(1)  # Default 1 second wait on error
                
                # Add configurable delay between commands for Arduino processing
                try:
                    delay_ms = float(getattr(self, 'command_delay_var', None).get() if hasattr(self, 'command_delay_var') else 200)
                    time.sleep(delay_ms / 1000.0)  # Convert milliseconds to seconds
                except:
                    time.sleep(0.2)  # Default 200ms delay
            
            # Script completed
            if not self.stop_script:
                if failed_commands == 0:
                    self.root.after(0, self.progress_window.execution_complete)
                    self.root.after(0, self.progress_window.log_activity, "🎉 Script execution completed successfully!")
                    self.root.after(0, self.progress_window.log_activity, f"✅ Total rows completed: {current_row}")
                    self.root.after(0, lambda: messagebox.showinfo("Success", f"Knitting completed successfully!\n\n{current_row} rows knitted with no errors."))
                else:
                    self.root.after(0, self.progress_window.execution_complete)
                    self.root.after(0, self.progress_window.log_activity, f"⚠ Script completed with {failed_commands} warnings/errors")
                    self.root.after(0, self.progress_window.log_activity, f"📊 Total rows completed: {current_row}")
                    self.root.after(0, lambda: messagebox.showwarning("Completed with Warnings", 
                                  f"Knitting completed but with {failed_commands} command failures.\n\nPlease check your work."))
            
        except Exception as e:
            self.root.after(0, self.progress_window.log_activity, f"❌ Critical execution error: {e}")
            self.log_message(f"Script execution error: {e}")
            self.root.after(0, lambda: messagebox.showerror("Execution Error", f"Critical error during script execution:\n\n{e}"))
        
        finally:
            # Clean up
            self.stop_script = False
            self.pause_script = False

def main():
    """Main function to run the application with proper cleanup"""
    root = tk.Tk()
    app = KnittingMachineController(root)
    
    # Handle window closing with proper cleanup
    def on_closing():
        try:
            # Stop any running scripts
            app.stop_script = True
            
            # Disconnect Arduino safely
            if app.is_connected:
                app.log_message("Shutting down - disconnecting Arduino...")
                app.disconnect_arduino()
            
            # Close progress window if open
            if hasattr(app, 'progress_window') and app.progress_window:
                try:
                    app.progress_window.window.destroy()
                except:
                    pass
            
            # Save configuration
            try:
                app.save_config()
                app.log_message("Configuration saved")
            except Exception as e:
                print(f"Could not save config on exit: {e}")
            
            app.log_message("Application shutting down safely")
            time.sleep(0.1)  # Give time for final log messages
            
        except Exception as e:
            print(f"Error during shutdown: {e}")
        finally:
            root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    # Set window icon and title
    root.title("Sentro Knitting Machine Controller - Ready")
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("Application interrupted by user")
        on_closing()
    except Exception as e:
        print(f"Application error: {e}")
        on_closing()

if __name__ == "__main__":
    main()
