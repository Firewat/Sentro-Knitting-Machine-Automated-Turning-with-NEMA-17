#!/usr/bin/env python3
"""
Sentro Knitting Machine Controller - PyQt6 Version
Modern, Professional GUI for Arduino-based knitting machine control
"""

import sys
import json
import serial
import serial.tools.list_ports
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QGridLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox, 
    QSpinBox, QProgressBar, QFileDialog, QMessageBox, QTabWidget,
    QScrollArea, QFrame, QSplitter, QGroupBox, QDialog, QDialogButtonBox
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, pyqtSlot
)
from PyQt6.QtGui import QFont, QPalette, QColor, QIcon


class SerialWorker(QThread):
    """Worker thread for Arduino communication"""
    
    # Signals
    response_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    progress_updated = pyqtSignal(int, int)  # current, total
    operation_completed = pyqtSignal()
    
    def __init__(self, chunk_size: int = 16000):  # Reduced from 32000 for smoother progress
        super().__init__()
        self.serial_port: Optional[serial.Serial] = None
        self.commands_queue: List[str] = []
        self.is_running = False
        self.should_stop = False
        self.chunk_size = chunk_size
        
    def update_chunk_size(self, chunk_size: int):
        """Update the chunk size for command splitting"""
        self.chunk_size = chunk_size
        
    def connect_arduino(self, port: str, baudrate: int = 9600) -> bool:
        """Connect to Arduino"""
        try:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
                
            # More robust serial connection with proper timeouts
            self.serial_port = serial.Serial(
                port=port, 
                baudrate=baudrate, 
                timeout=2,
                write_timeout=2,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            
            # Wait for Arduino to reset and stabilize
            time.sleep(3)
            
            # Clear any startup messages
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()
            
            return True
        except Exception as e:
            self.error_occurred.emit(f"Connection failed: {str(e)}")
            return False
            
    def disconnect_arduino(self):
        """Disconnect from Arduino"""
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            
    def send_distance_command_lightweight(self):
        """Send distance command with minimal blocking"""
        if not self.serial_port or not self.serial_port.is_open:
            return False
            
        try:
            # Clear any pending input first
            if self.serial_port.in_waiting > 0:
                self.serial_port.reset_input_buffer()
            
            # Send command quickly
            self.serial_port.write(b"DISTANCE\n")
            self.serial_port.flush()
            return True
        except Exception as e:
            self.error_occurred.emit(f"Distance command failed: {str(e)}")
            return False
    
    def check_distance_response(self):
        """Check for distance response without blocking"""
        if not self.serial_port or not self.serial_port.is_open:
            return None
            
        try:
            if self.serial_port.in_waiting > 0:
                line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    return line
        except Exception as e:
            pass
        return None
    
    def send_command_async(self, command: str):
        """Send command asynchronously without blocking UI"""
        if not self.serial_port or not self.serial_port.is_open:
            self.error_occurred.emit("Arduino not connected")
            return
            
        try:
            # Send command immediately without blocking
            self.serial_port.write(f"{command}\n".encode('ascii'))
            self.serial_port.flush()
            
            # Start background thread to read response
            self.start()  # This will trigger run() method
            
        except Exception as e:
            self.error_occurred.emit(f"Command send failed: {str(e)}")
    
    def send_command(self, command: str) -> bool:
        """Send single command to Arduino"""
        if not self.serial_port or not self.serial_port.is_open:
            self.error_occurred.emit("Arduino not connected")
            return False
            
        try:
            # Debug: Log the exact command being sent
            print(f"DEBUG: Sending command: {command}")
            
            # Clear buffers to prevent corruption
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()
            
            # Small delay to ensure buffers are cleared
            time.sleep(0.2)
            
            # Send command with proper encoding
            self.serial_port.write(f"{command}\n".encode('ascii'))
            self.serial_port.flush()
            
            # Wait a bit for Arduino to process
            time.sleep(0.5)
            
            # Read response with proper error handling
            responses = []
            execution_started = False
            debug_received = False
            start_time = time.time()
            
            while time.time() - start_time < 8.0:  # 8 second timeout
                try:
                    if self.serial_port.in_waiting > 0:
                        # Read line with better encoding handling
                        try:
                            line = self.serial_port.readline().decode('utf-8', errors='replace').strip()
                        except UnicodeDecodeError:
                            line = self.serial_port.readline().decode('ascii', errors='replace').strip()
                        
                        if line:
                            print(f"DEBUG: Arduino says: '{line}'")
                            responses.append(line)
                            self.response_received.emit(line)
                            
                            # Check for key responses
                            if "Executing:" in line:
                                execution_started = True
                                print("DEBUG: Command execution confirmed")
                                return True
                            elif "DONE" in line:
                                print("DEBUG: Command completion confirmed")
                                return True
                            elif "ERROR:" in line:
                                self.error_occurred.emit(f"Arduino error: {line}")
                                return False
                            elif "DEBUG: Processing command:" in line:
                                debug_received = True
                                print("DEBUG: Arduino received command")
                                
                    time.sleep(0.1)  # Small delay to prevent busy waiting
                    
                except UnicodeDecodeError:
                    print("DEBUG: Received corrupted data, continuing...")
                    continue
                    
            # If we get here without clear confirmation, check what we got
            if execution_started:
                print("DEBUG: Execution started, assuming success")
                return True
            elif debug_received:
                print("DEBUG: Command received by Arduino, assuming success")
                return True
            elif any("DEBUG: Processing command:" in r for r in responses):
                print("DEBUG: Command processing confirmed, assuming success")
                return True
            else:
                print(f"DEBUG: No clear response. Got: {responses}")
                # For large commands, assume success if we got any response
                if command.startswith("TURN:") and responses:
                    print("DEBUG: Assuming TURN command succeeded based on partial response")
                    return True
                return False
                
        except Exception as e:
            print(f"DEBUG: Communication error: {e}")
            self.error_occurred.emit(f"Communication error: {str(e)}")
            return False
            
    def queue_commands(self, commands: List[str]):
        """Queue multiple commands for execution"""
        self.commands_queue = commands.copy()
        self.should_stop = False
        
    def run(self):
        """Execute queued commands"""
        if not self.commands_queue:
            return
            
        self.is_running = True
        total_commands = len(self.commands_queue)
        
        print(f"DEBUG: Starting script execution with {total_commands} commands")
        
        # Process each command, chunking large ones
        processed_commands = []
        for command in self.commands_queue:
            if command.startswith("TURN:"):
                # Check if command needs chunking
                chunks = self._chunk_large_command(command)
                processed_commands.extend(chunks)
            else:
                processed_commands.append(command)
        
        print(f"DEBUG: After chunking: {len(processed_commands)} total commands to execute")
        
        for i, command in enumerate(processed_commands):
            if self.should_stop:
                print("DEBUG: Script execution stopped by user")
                break
                
            print(f"DEBUG: Executing command {i+1}/{len(processed_commands)}: {command}")
            
            # Send command and wait for proper response
            success = False
            for attempt in range(3):  # Try up to 3 times
                print(f"DEBUG: Attempt {attempt + 1} for command: {command}")
                
                if self.send_command(command):
                    success = True
                    break
                else:
                    print(f"DEBUG: Attempt {attempt + 1} failed, retrying...")
                    time.sleep(1)  # Wait before retry
                    
            if not success:
                print(f"DEBUG: Command failed after 3 attempts: {command}")
                self.error_occurred.emit(f"Failed to execute command: {command}")
                break
                
            # Wait for movement to complete
            if command.startswith("TURN:"):
                print("DEBUG: Waiting for Arduino to complete movement...")
                self._wait_for_completion(command)
            else:
                time.sleep(0.5)  # Shorter delay for non-movement commands
                
            # Update progress based on original command count
            original_progress = int((i + 1) * total_commands / len(processed_commands))
            self.progress_updated.emit(original_progress, total_commands)
            
            # Add delay between commands to prevent overwhelming Arduino
            print("DEBUG: Waiting before next command...")
            time.sleep(1)  # 1 second delay between commands
            
        print("DEBUG: Script execution completed")
        self.is_running = False
        self.operation_completed.emit()
        
    def _chunk_large_command(self, command: str) -> List[str]:
        """Break large TURN commands into smaller chunks"""
        try:
            parts = command.split(":")
            if len(parts) >= 3:
                steps = int(parts[1])
                direction = parts[2]
                
                # Use configurable chunk size
                max_chunk_size = self.chunk_size
                
                if steps <= max_chunk_size:
                    return [command]  # No chunking needed
                    
                # Calculate chunks
                chunks = []
                remaining_steps = steps
                chunk_number = 1
                total_chunks = (steps + max_chunk_size - 1) // max_chunk_size
                
                print(f"DEBUG: Chunking {steps} steps into {total_chunks} chunks of max {max_chunk_size} steps")
                
                while remaining_steps > 0:
                    current_chunk = min(max_chunk_size, remaining_steps)
                    chunk_command = f"TURN:{current_chunk}:{direction}"
                    chunks.append(chunk_command)
                    print(f"DEBUG: Chunk {chunk_number}/{total_chunks}: {chunk_command}")
                    remaining_steps -= current_chunk
                    chunk_number += 1
                    
                return chunks
            else:
                return [command]  # Malformed command, return as-is
                
        except (ValueError, IndexError):
            print(f"DEBUG: Could not parse command for chunking: {command}")
            return [command]  # Return original if parsing fails
        
    def _wait_for_completion(self, command: str):
        """Wait for Arduino to complete a TURN command"""
        try:
            # Calculate estimated time based on steps
            parts = command.split(":")
            if len(parts) >= 2:
                steps = int(parts[1])
                # Estimate time: motor speed is 1000 microseconds per step
                # That's about 1000 steps per second, so steps/1000 seconds
                estimated_time = max(1.0, steps / 1000.0)
                print(f"DEBUG: Estimated movement time: {estimated_time:.1f} seconds")
                
                # Simple fixed wait - more reliable than trying to read during movement
                print("DEBUG: Waiting for movement to complete...")
                time.sleep(estimated_time)
                
                # Try to read any final responses
                for _ in range(5):  # Try up to 5 times
                    try:
                        if self.serial_port and self.serial_port.in_waiting > 0:
                            try:
                                line = self.serial_port.readline().decode('utf-8', errors='replace').strip()
                            except UnicodeDecodeError:
                                line = self.serial_port.readline().decode('ascii', errors='replace').strip()
                            
                            if line:
                                print(f"DEBUG: Final Arduino response: '{line}'")
                                self.response_received.emit(line)
                                if "DONE" in line:
                                    print("DEBUG: Arduino confirmed completion")
                                    return
                    except Exception as e:
                        print(f"DEBUG: Serial read error: {e}")
                        pass
                    time.sleep(0.1)
                    
                print("DEBUG: Movement wait completed")
            else:
                # Fallback for malformed commands
                time.sleep(0.5)
        except Exception as e:
            print(f"DEBUG: Error waiting for completion: {e}")
            time.sleep(0.5)
        
    def _send_chunked_command(self, command: str, total_steps: int):
        """Send large commands in chunks"""
        parts = command.split(":")
        direction = parts[2] if len(parts) > 2 else "CW"
        
        chunk_size = 2000  # Reduced from 5000 for smoother progress updates
        chunks = (total_steps + chunk_size - 1) // chunk_size
        
        for i in range(chunks):
            if self.should_stop:
                break
                
            current_chunk = min(chunk_size, total_steps - (i * chunk_size))
            chunk_command = f"TURN:{current_chunk}:{direction}"
            
            # Send the chunk and wait for completion
            if not self.send_command(chunk_command):
                self.error_occurred.emit(f"Failed to send chunk {i+1}/{chunks}")
                break
                
            # Add a small delay between chunks to prevent overwhelming Arduino
            self.msleep(200)
            
    def stop_operation(self):
        """Stop current operation"""
        self.should_stop = True


class ProgressDialog(QDialog):
    """Modern progress dialog"""
    
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(400, 150)
        self.setModal(True)
        
        layout = QVBoxLayout()
        
        # Progress info
        self.status_label = QLabel("Preparing...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        layout.addWidget(self.progress_bar)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.pause_btn = QPushButton("Pause")
        self.stop_btn = QPushButton("Stop")
        self.emergency_btn = QPushButton("Emergency Stop")
        
        self.pause_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; }")
        self.stop_btn.setStyleSheet("QPushButton { background-color: #F48FB1; color: white; }")
        self.emergency_btn.setStyleSheet("QPushButton { background-color: #D32F2F; color: white; font-weight: bold; }")
        
        button_layout.addWidget(self.pause_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout.addWidget(self.emergency_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
    def update_progress(self, current: int, total: int):
        """Update progress display"""
        if total > 0:
            percentage = int((current / total) * 100)
            self.progress_bar.setValue(percentage)
            self.status_label.setText(f"Processing command {current} of {total}")


class KnittingMachineGUI(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.config_file = "knitting_config.json"
        self.config = self.load_config()
        
        # Initialize serial worker
        chunk_size = self.config.get("chunk_size", 32000)
        self.serial_worker = SerialWorker(chunk_size)
        self.setup_signals()
        
        # Initialize UI
        self.init_ui()
        self.apply_modern_styling()
        self.load_settings_ui()
        
        # Progress dialog
        self.progress_dialog: Optional[ProgressDialog] = None
        
        # Distance monitoring timer
        self.distance_timer = QTimer()
        self.distance_timer.timeout.connect(self.update_distance_reading)
        self.distance_monitoring_enabled = False
        self.distance_request_pending = False  # Prevent overlapping requests
        
        # Response checker timer for non-blocking serial reading
        self.response_checker = QTimer()
        self.response_checker.timeout.connect(self.check_for_responses)
        self.response_checker.start(50)  # Check every 50ms for responses
        
        # UI refresh timer for smoother updates
        self.ui_refresh_timer = QTimer()
        self.ui_refresh_timer.timeout.connect(self.refresh_ui_elements)
        self.ui_refresh_timer.start(200)  # Update UI every 200ms (5 times per second) - less frequent to prevent freezing
        
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        default_config = {
            "steps_per_needle": 1000,
            "arduino_port": "",
            "baudrate": 9600,
            "motor_speed": 1000,
            "microstepping": 1,
            "chunk_size": 32000
        }
        
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                # Merge with defaults
                default_config.update(config)
                return default_config
        except FileNotFoundError:
            return default_config
            
    def save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "Config Error", f"Failed to save config: {str(e)}")
            
    def setup_signals(self):
        """Setup signal connections"""
        self.serial_worker.response_received.connect(self.on_arduino_response)
        self.serial_worker.error_occurred.connect(self.on_arduino_error)
        self.serial_worker.progress_updated.connect(self.on_progress_update)
        self.serial_worker.operation_completed.connect(self.on_operation_complete)
        
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Sentro Knitting Machine Controller")
        self.setMinimumSize(1000, 700)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QHBoxLayout(central_widget)
        
        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left panel - Controls
        self.create_control_panel(splitter)
        
        # Right panel - Console and status
        self.create_console_panel(splitter)
        
        # Set splitter proportions
        splitter.setSizes([600, 400])
        
    def create_control_panel(self, parent):
        """Create the main control panel"""
        control_widget = QWidget()
        layout = QVBoxLayout(control_widget)
        
        # Connection section
        conn_group = QGroupBox("Arduino Connection")
        conn_layout = QGridLayout(conn_group)
        
        conn_layout.addWidget(QLabel("Port:"), 0, 0)
        self.port_combo = QComboBox()
        self.refresh_ports()
        conn_layout.addWidget(self.port_combo, 0, 1)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        conn_layout.addWidget(self.refresh_btn, 0, 2)
        
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.connect_btn, 1, 0, 1, 3)
        
        # Connection status indicator
        self.status_label = QLabel("❌ Disconnected")
        self.status_label.setStyleSheet("color: #F44336; font-weight: bold; padding: 5px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        conn_layout.addWidget(self.status_label, 2, 0, 1, 3)
        
        layout.addWidget(conn_group)
        
        # Settings section
        settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout(settings_group)
        
        settings_layout.addWidget(QLabel("Steps per Needle:"), 0, 0)
        self.steps_spinbox = QSpinBox()
        self.steps_spinbox.setRange(1, 10000)
        self.steps_spinbox.setValue(self.config["steps_per_needle"])
        self.steps_spinbox.valueChanged.connect(self.on_steps_changed)
        settings_layout.addWidget(self.steps_spinbox, 0, 1)
        
        layout.addWidget(settings_group)
        
        # Tab widget for different functions
        self.tab_widget = QTabWidget()
        
        # Create Script tab
        self.create_script_tab()
        
        # Upload Script tab
        self.create_upload_tab()
        
        # Manual Control tab
        self.create_manual_tab()
        
        # Settings tab
        self.create_settings_tab()
        
        layout.addWidget(self.tab_widget)
        
        parent.addWidget(control_widget)
        
    def create_script_tab(self):
        """Create the script creation tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Script parameters
        params_group = QGroupBox("Script Parameters")
        params_layout = QGridLayout(params_group)
        
        params_layout.addWidget(QLabel("Number of Rows:"), 0, 0)
        self.rows_spinbox = QSpinBox()
        self.rows_spinbox.setRange(1, 1000)
        self.rows_spinbox.setValue(10)
        params_layout.addWidget(self.rows_spinbox, 0, 1)
        
        params_layout.addWidget(QLabel("Needles per Row:"), 1, 0)
        self.needles_spinbox = QSpinBox()
        self.needles_spinbox.setRange(1, 200)
        self.needles_spinbox.setValue(48)
        params_layout.addWidget(self.needles_spinbox, 1, 1)
        
        layout.addWidget(params_group)
        
        # Direction settings
        direction_group = QGroupBox("Direction Pattern")
        direction_layout = QVBoxLayout(direction_group)
        
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["Alternating (CW/CCW)", "All Clockwise", "All Counter-Clockwise"])
        direction_layout.addWidget(self.direction_combo)
        
        layout.addWidget(direction_group)
        
        # Generate and save buttons
        button_layout = QHBoxLayout()
        
        self.generate_btn = QPushButton("Generate Script")
        self.generate_btn.clicked.connect(self.generate_script)
        button_layout.addWidget(self.generate_btn)
        
        self.save_script_btn = QPushButton("Save Script")
        self.save_script_btn.clicked.connect(self.save_script)
        button_layout.addWidget(self.save_script_btn)
        
        layout.addLayout(button_layout)
        
        # Script preview
        preview_group = QGroupBox("Script Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        self.script_preview = QTextEdit()
        self.script_preview.setMaximumHeight(200)
        self.script_preview.setReadOnly(True)
        preview_layout.addWidget(self.script_preview)
        
        layout.addWidget(preview_group)
        
        self.tab_widget.addTab(widget, "Create Script")
        
    def create_upload_tab(self):
        """Create the script upload tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # File selection
        file_group = QGroupBox("Script File")
        file_layout = QHBoxLayout(file_group)
        
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)
        file_layout.addWidget(self.file_path_edit)
        
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse_script_file)
        file_layout.addWidget(self.browse_btn)
        
        layout.addWidget(file_group)
        
        # Script info
        info_group = QGroupBox("Script Information")
        info_layout = QVBoxLayout(info_group)
        
        self.script_info = QLabel("No script loaded")
        info_layout.addWidget(self.script_info)
        
        layout.addWidget(info_group)
        
        # Upload button
        self.upload_btn = QPushButton("Upload and Execute Script")
        self.upload_btn.clicked.connect(self.upload_script)
        self.upload_btn.setEnabled(False)
        layout.addWidget(self.upload_btn)
        
        # Script content
        content_group = QGroupBox("Script Content")
        content_layout = QVBoxLayout(content_group)
        
        self.script_content = QTextEdit()
        self.script_content.setReadOnly(True)
        content_layout.addWidget(self.script_content)
        
        layout.addWidget(content_group)
        
        self.tab_widget.addTab(widget, "Upload Script")
        
    def create_manual_tab(self):
        """Create the manual control tab"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        
        # Create scroll area for manual controls
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Create scrollable content widget
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(20)  # Add spacing between sections
        
        # Manual turn controls
        manual_group = QGroupBox("Manual Turn Control")
        manual_layout = QGridLayout(manual_group)
        manual_layout.setSpacing(10)
        
        manual_layout.addWidget(QLabel("Steps:"), 0, 0)
        self.manual_steps = QSpinBox()
        self.manual_steps.setRange(1, 50000)
        self.manual_steps.setValue(1000)
        self.manual_steps.setMinimumWidth(120)
        self.manual_steps.setMinimumHeight(30)
        self.manual_steps.valueChanged.connect(self.check_manual_chunking)
        manual_layout.addWidget(self.manual_steps, 0, 1)
        
        manual_layout.addWidget(QLabel("Direction:"), 1, 0)
        self.manual_direction = QComboBox()
        self.manual_direction.addItems(["CW", "CCW"])
        self.manual_direction.setMinimumWidth(120)
        self.manual_direction.setMinimumHeight(30)
        manual_layout.addWidget(self.manual_direction, 1, 1)
        
        # Chunking info label
        self.chunking_info = QLabel("")
        self.chunking_info.setStyleSheet("QLabel { color: #888888; font-size: 11px; font-style: italic; margin: 5px; }")
        self.chunking_info.setWordWrap(True)
        self.chunking_info.setMinimumHeight(40)
        manual_layout.addWidget(self.chunking_info, 2, 0, 1, 2)
        
        self.manual_turn_btn = QPushButton("Execute Turn")
        self.manual_turn_btn.clicked.connect(self.manual_turn)
        self.manual_turn_btn.setMinimumHeight(40)
        self.manual_turn_btn.setStyleSheet("QPushButton { font-weight: bold; }")
        manual_layout.addWidget(self.manual_turn_btn, 3, 0, 1, 2)
        
        layout.addWidget(manual_group)
        
        # HC-SR04 Sensor Controls
        sensor_group = QGroupBox("HC-SR04 Ultrasonic Sensor")
        sensor_layout = QGridLayout(sensor_group)
        sensor_layout.setSpacing(10)
        
        self.distance_btn = QPushButton("Get Distance Reading")
        self.distance_btn.clicked.connect(lambda: self.send_command("DISTANCE"))
        self.distance_btn.setMinimumHeight(35)
        sensor_layout.addWidget(self.distance_btn, 0, 0)
        
        self.monitor_distance_btn = QPushButton("Start Distance Monitoring")
        self.monitor_distance_btn.clicked.connect(self.toggle_distance_monitoring)
        self.monitor_distance_btn.setMinimumHeight(35)
        sensor_layout.addWidget(self.monitor_distance_btn, 0, 1)
        
        # Add sensor test button
        self.test_sensor_btn = QPushButton("Test Sensor (5 readings)")
        self.test_sensor_btn.clicked.connect(self.test_sensor)
        self.test_sensor_btn.setMinimumHeight(35)
        sensor_layout.addWidget(self.test_sensor_btn, 1, 0, 1, 2)
        
        layout.addWidget(sensor_group)
        
        # Needle Detection Controls
        needle_group = QGroupBox("Needle Detection")
        needle_layout = QGridLayout(needle_group)
        needle_layout.setSpacing(10)
        
        self.needle_count_btn = QPushButton("Get Needle Count")
        self.needle_count_btn.clicked.connect(lambda: self.send_command("NEEDLE_COUNT"))
        self.needle_count_btn.setMinimumHeight(35)
        needle_layout.addWidget(self.needle_count_btn, 0, 0)
        
        self.reset_count_btn = QPushButton("Reset Needle Count")
        self.reset_count_btn.clicked.connect(lambda: self.send_command("RESET_COUNT"))
        self.reset_count_btn.setMinimumHeight(35)
        needle_layout.addWidget(self.reset_count_btn, 0, 1)
        
        layout.addWidget(needle_group)
        
        # System Commands
        system_group = QGroupBox("System Commands")
        system_layout = QGridLayout(system_group)
        system_layout.setSpacing(10)
        
        self.status_btn = QPushButton("Get Status")
        self.status_btn.clicked.connect(lambda: self.send_command("STATUS"))
        self.status_btn.setMinimumHeight(35)
        system_layout.addWidget(self.status_btn, 0, 0)
        
        self.home_btn = QPushButton("Home Position")
        self.home_btn.clicked.connect(lambda: self.send_command("HOME"))
        self.home_btn.setMinimumHeight(35)
        system_layout.addWidget(self.home_btn, 0, 1)
        
        self.stop_btn = QPushButton("Emergency Stop")
        self.stop_btn.clicked.connect(lambda: self.send_command("STOP"))
        self.stop_btn.setMinimumHeight(35)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #ffebee; color: #c62828; font-weight: bold; }")
        system_layout.addWidget(self.stop_btn, 1, 0, 1, 2)
        
        layout.addWidget(system_group)
        
        # Custom command
        custom_group = QGroupBox("Custom Command")
        custom_layout = QHBoxLayout(custom_group)
        custom_layout.setSpacing(10)
        
        self.custom_command = QLineEdit()
        self.custom_command.setPlaceholderText("Enter custom command (e.g., TURN:500:CW)...")
        self.custom_command.setMinimumHeight(35)
        custom_layout.addWidget(self.custom_command)
        
        self.send_custom_btn = QPushButton("Send Command")
        self.send_custom_btn.clicked.connect(self.send_custom_command)
        self.send_custom_btn.setMinimumHeight(35)
        self.send_custom_btn.setMinimumWidth(120)
        custom_layout.addWidget(self.send_custom_btn)
        
        layout.addWidget(custom_group)
        
        # Add some bottom padding
        layout.addSpacing(20)
        
        # Set the scroll content
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(widget, "Manual Control")
        
    def create_settings_tab(self):
        """Create the settings tab"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        
        # Create scroll area for settings
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Create scrollable content widget
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(15)  # Add spacing between sections
        
        # Motor Speed Settings
        speed_group = QGroupBox("Motor Speed Settings")
        speed_layout = QGridLayout(speed_group)
        speed_layout.setSpacing(10)
        
        speed_layout.addWidget(QLabel("Step Delay (microseconds):"), 0, 0)
        self.speed_spinbox = QSpinBox()
        self.speed_spinbox.setRange(500, 3000)
        self.speed_spinbox.setValue(1000)  # Default motor speed
        self.speed_spinbox.setSuffix(" μs")
        self.speed_spinbox.setMinimumWidth(120)
        self.speed_spinbox.valueChanged.connect(self.on_speed_changed)
        speed_layout.addWidget(self.speed_spinbox, 0, 1)
        
        speed_info = QLabel("Lower values = faster motor (500-1000 μs)\nHigher values = slower, more precise (1500-3000 μs)")
        speed_info.setWordWrap(True)
        speed_info.setStyleSheet("QLabel { color: #888888; font-size: 12px; margin: 5px; }")
        speed_layout.addWidget(speed_info, 1, 0, 1, 2)
        
        # Speed presets - in a grid for better space usage
        preset_label = QLabel("Speed Presets:")
        preset_label.setStyleSheet("QLabel { font-weight: bold; margin-top: 10px; }")
        speed_layout.addWidget(preset_label, 2, 0, 1, 2)
        
        self.speed_fast_btn = QPushButton("Fast\n(800μs)")
        self.speed_fast_btn.clicked.connect(lambda: self.set_speed_preset(800))
        self.speed_fast_btn.setMaximumHeight(50)
        speed_layout.addWidget(self.speed_fast_btn, 3, 0)
        
        self.speed_normal_btn = QPushButton("Normal\n(1000μs)")
        self.speed_normal_btn.clicked.connect(lambda: self.set_speed_preset(1000))
        self.speed_normal_btn.setMaximumHeight(50)
        speed_layout.addWidget(self.speed_normal_btn, 3, 1)
        
        self.speed_slow_btn = QPushButton("Slow\n(1500μs)")
        self.speed_slow_btn.clicked.connect(lambda: self.set_speed_preset(1500))
        self.speed_slow_btn.setMaximumHeight(50)
        speed_layout.addWidget(self.speed_slow_btn, 4, 0)
        
        self.speed_precise_btn = QPushButton("Precise\n(2000μs)")
        self.speed_precise_btn.clicked.connect(lambda: self.set_speed_preset(2000))
        self.speed_precise_btn.setMaximumHeight(50)
        speed_layout.addWidget(self.speed_precise_btn, 4, 1)
        
        # Apply speed button
        self.apply_speed_btn = QPushButton("Apply Speed to Arduino")
        self.apply_speed_btn.clicked.connect(self.apply_speed_setting)
        self.apply_speed_btn.setMinimumHeight(35)
        speed_layout.addWidget(self.apply_speed_btn, 5, 0, 1, 2)
        
        layout.addWidget(speed_group)
        
        # Microstepping Settings
        micro_group = QGroupBox("Microstepping Settings")
        micro_layout = QGridLayout(micro_group)
        micro_layout.setSpacing(10)
        
        micro_layout.addWidget(QLabel("Microstepping:"), 0, 0)
        self.micro_combo = QComboBox()
        self.micro_combo.addItems(["1", "2", "4", "8", "16", "32"])
        self.micro_combo.setCurrentText("1")  # Default microstepping
        self.micro_combo.setMinimumWidth(120)
        self.micro_combo.currentTextChanged.connect(self.on_micro_changed)
        micro_layout.addWidget(self.micro_combo, 0, 1)
        
        micro_info = QLabel("Higher values = smoother movement but slower\nMust match your driver's jumper settings")
        micro_info.setWordWrap(True)
        micro_info.setStyleSheet("QLabel { color: #888888; font-size: 12px; margin: 5px; }")
        micro_layout.addWidget(micro_info, 1, 0, 1, 2)
        
        # Apply microstepping button
        self.apply_micro_btn = QPushButton("Apply Microstepping to Arduino")
        self.apply_micro_btn.clicked.connect(self.apply_micro_setting)
        self.apply_micro_btn.setMinimumHeight(35)
        micro_layout.addWidget(self.apply_micro_btn, 2, 0, 1, 2)
        
        layout.addWidget(micro_group)
        
        # Advanced Settings
        advanced_group = QGroupBox("Advanced Settings")
        advanced_layout = QGridLayout(advanced_group)
        advanced_layout.setSpacing(10)
        
        advanced_layout.addWidget(QLabel("Chunk Size (max steps):"), 0, 0)
        self.chunk_size_spinbox = QSpinBox()
        self.chunk_size_spinbox.setRange(5000, 32700)
        self.chunk_size_spinbox.setValue(32000)
        self.chunk_size_spinbox.setMinimumWidth(120)
        self.chunk_size_spinbox.valueChanged.connect(self.on_chunk_size_changed)
        advanced_layout.addWidget(self.chunk_size_spinbox, 0, 1)
        
        chunk_info = QLabel("Maximum steps sent in one command to Arduino\nHigher values = fewer commands but near Arduino limit (32767)")
        chunk_info.setWordWrap(True)
        chunk_info.setStyleSheet("QLabel { color: #888888; font-size: 12px; margin: 5px; }")
        advanced_layout.addWidget(chunk_info, 1, 0, 1, 2)
        
        layout.addWidget(advanced_group)
        
        # Current Settings Display
        current_group = QGroupBox("Current Arduino Settings")
        current_layout = QVBoxLayout(current_group)
        current_layout.setSpacing(10)
        
        self.current_settings_label = QLabel("Connect to Arduino to view current settings")
        self.current_settings_label.setWordWrap(True)
        self.current_settings_label.setStyleSheet("QLabel { padding: 10px; background-color: #f9f9f9; border-radius: 4px; }")
        self.current_settings_label.setMinimumHeight(80)
        current_layout.addWidget(self.current_settings_label)
        
        self.refresh_settings_btn = QPushButton("Refresh Current Settings")
        self.refresh_settings_btn.clicked.connect(self.refresh_current_settings)
        self.refresh_settings_btn.setMinimumHeight(35)
        current_layout.addWidget(self.refresh_settings_btn)
        
        layout.addWidget(current_group)
        
        # Add some bottom padding
        layout.addSpacing(20)
        
        # Set the scroll content
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(widget, "Settings")
        
    def load_settings_ui(self):
        """Load saved settings into UI elements"""
        # Load motor speed
        if hasattr(self, 'speed_spinbox'):
            self.speed_spinbox.setValue(self.config.get("motor_speed", 1000))
            
        # Load microstepping
        if hasattr(self, 'micro_combo'):
            micro_value = str(self.config.get("microstepping", 1))
            self.micro_combo.setCurrentText(micro_value)
            
        # Load chunk size
        if hasattr(self, 'chunk_size_spinbox'):
            self.chunk_size_spinbox.setValue(self.config.get("chunk_size", 32000))
            
        # Update settings display
        if hasattr(self, 'current_settings_label'):
            self.update_settings_display()
            
        # Initialize manual chunking info
        if hasattr(self, 'chunking_info'):
            self.check_manual_chunking()
        
    def create_console_panel(self, parent):
        """Create the console and status panel"""
        console_widget = QWidget()
        layout = QVBoxLayout(console_widget)
        
        # Status section
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)
        
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("QLabel { color: #D32F2F; font-weight: bold; }")
        status_layout.addWidget(self.status_label)
        
        layout.addWidget(status_group)
        
        # Console section
        console_group = QGroupBox("Console Output")
        console_layout = QVBoxLayout(console_group)
        
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setFont(QFont("Consolas", 9))
        console_layout.addWidget(self.console_output)
        
        # Console controls
        console_controls = QHBoxLayout()
        
        self.clear_console_btn = QPushButton("Clear")
        self.clear_console_btn.clicked.connect(self.console_output.clear)
        console_controls.addWidget(self.clear_console_btn)
        
        console_controls.addStretch()
        console_layout.addLayout(console_controls)
        
        layout.addWidget(console_group)
        
        parent.addWidget(console_widget)
        
    def apply_modern_styling(self):
        """Apply modern styling to the application"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
                color: #F48FB1;
            }
            
            QWidget {
                color: #F48FB1;
            }
            
            QLabel {
                color: #F48FB1;
                font-weight: normal;
            }
            
            QGroupBox {
                color: #F48FB1;
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #EC407A;
                font-weight: bold;
            }
            
            QPushButton {
                background-color: #F48FB1;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                min-height: 20px;
            }
            
            QPushButton:hover {
                background-color: #EC407A;
            }
            
            QPushButton:pressed {
                background-color: #E91E63;
            }
            
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
            
            QLineEdit, QSpinBox, QComboBox {
                padding: 8px;
                border: 2px solid #ddd;
                border-radius: 4px;
                font-size: 14px;
                color: #F48FB1;
                background-color: white;
            }
            
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border-color: #F48FB1;
                background-color: white;
            }
            
            QTextEdit {
                border: 2px solid #ddd;
                border-radius: 4px;
                font-family: 'Consolas', monospace;
                color: #F48FB1;
                background-color: white;
            }
            
            QTabWidget::pane {
                border: 1px solid #cccccc;
                border-radius: 4px;
            }
            
            QTabBar::tab {
                background-color: #e0e0e0;
                color: #F48FB1;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            
            QTabBar::tab:selected {
                background-color: #F48FB1;
                color: white;
            }
            
            QProgressBar {
                border: 2px solid #ddd;
                border-radius: 4px;
                text-align: center;
                color: #F48FB1;
                background-color: white;
            }
            
            QProgressBar::chunk {
                background-color: #F48FB1;
                border-radius: 2px;
            }
            
            QComboBox QAbstractItemView {
                color: #F48FB1;
                background-color: white;
                selection-background-color: #FCE4EC;
            }
            
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #F48FB1;
            }
            
            QScrollBar:vertical {
                background-color: #f0f0f0;
                width: 12px;
                border-radius: 6px;
            }
            
            QScrollBar::handle:vertical {
                background-color: #F48FB1;
                border-radius: 6px;
                min-height: 20px;
            }
            
            QScrollBar::handle:vertical:hover {
                background-color: #EC407A;
            }
        """)
        
    # Event handlers
    def refresh_ports(self):
        """Refresh available serial ports"""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(f"{port.device} - {port.description}")
            
    def toggle_connection(self):
        """Toggle Arduino connection"""
        if self.connect_btn.text() == "Connect":
            port_text = self.port_combo.currentText()
            if not port_text:
                QMessageBox.warning(self, "Connection Error", "Please select a port")
                return
                
            port = port_text.split(" - ")[0]
            if self.serial_worker.connect_arduino(port):
                self.connect_btn.setText("Disconnect")
                self.status_label.setText("Connected")
                self.status_label.setStyleSheet("QLabel { color: #F48FB1; font-weight: bold; }")
                self.config["arduino_port"] = port
                self.save_config()
                self.log_message(f"Connected to {port}")
            else:
                QMessageBox.critical(self, "Connection Error", "Failed to connect to Arduino")
        else:
            self.serial_worker.disconnect_arduino()
            self.connect_btn.setText("Connect")
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("QLabel { color: #D32F2F; font-weight: bold; }")
            self.log_message("Disconnected from Arduino")
            
    def on_steps_changed(self, value):
        """Handle steps per needle change"""
        self.config["steps_per_needle"] = value
        self.save_config()
        
    def on_speed_changed(self, value):
        """Handle motor speed change"""
        self.config["motor_speed"] = value
        self.save_config()
        
    def on_micro_changed(self, text):
        """Handle microstepping change"""
        self.config["microstepping"] = int(text)
        self.save_config()
        
    def on_chunk_size_changed(self, value):
        """Handle chunk size change"""
        self.config["chunk_size"] = value
        self.serial_worker.update_chunk_size(value)
        self.save_config()
        
    def set_speed_preset(self, speed):
        """Set motor speed preset"""
        self.speed_spinbox.setValue(speed)
        self.config["motor_speed"] = speed
        self.save_config()
        
    def apply_speed_setting(self):
        """Apply current speed setting to Arduino"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Settings Error", "Please connect to Arduino first")
            return
            
        speed = self.speed_spinbox.value()
        command = f"SPEED:{speed}"
        self.send_command(command)
        self.log_message(f"Applied motor speed: {speed}μs")
        
    def apply_micro_setting(self):
        """Apply current microstepping setting to Arduino"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Settings Error", "Please connect to Arduino first")
            return
            
        micro = self.micro_combo.currentText()
        command = f"MICRO:{micro}"
        self.send_command(command)
        self.log_message(f"Applied microstepping: {micro}")
        
    def refresh_current_settings(self):
        """Get current settings from Arduino"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Settings Error", "Please connect to Arduino first")
            return
            
        self.send_command("STATUS")
        self.log_message("Requesting current Arduino settings...")
        
        # Update the display after a short delay to allow response
        QTimer.singleShot(1000, self.update_settings_display)
        
    def update_settings_display(self):
        """Update the current settings display"""
        # This would be called after getting STATUS response
        # For now, just show the config values
        settings_text = f"""Motor Speed: {self.config['motor_speed']}μs
Microstepping: {self.config['microstepping']}
Chunk Size: {self.config['chunk_size']} steps
Steps per Needle: {self.config['steps_per_needle']}"""
        self.current_settings_label.setText(settings_text)
        
    def generate_script(self):
        """Generate knitting script"""
        rows = self.rows_spinbox.value()
        needles = self.needles_spinbox.value()
        steps_per_needle = self.config["steps_per_needle"]
        direction_pattern = self.direction_combo.currentIndex()
        
        script_lines = []
        
        for row in range(1, rows + 1):
            if direction_pattern == 0:  # Alternating
                direction = "CW" if row % 2 == 1 else "CCW"
            elif direction_pattern == 1:  # All CW
                direction = "CW"
            else:  # All CCW
                direction = "CCW"
                
            total_steps = needles * steps_per_needle
            script_lines.append(f"TURN:{total_steps}:{direction}")
            
        script_content = "\n".join(script_lines)
        self.script_preview.setText(script_content)
        self.current_script = script_lines
        
        # Update info
        total_steps = sum(int(line.split(":")[1]) for line in script_lines)
        info = f"Script generated: {rows} rows, {needles} needles/row, {total_steps:,} total steps"
        self.log_message(info)
        
    def save_script(self):
        """Save script to file"""
        if not hasattr(self, 'current_script'):
            QMessageBox.warning(self, "Save Error", "Please generate a script first")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Script", "", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    f.write("\n".join(self.current_script))
                QMessageBox.information(self, "Success", "Script saved successfully")
                self.log_message(f"Script saved to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save script: {str(e)}")
                
    def browse_script_file(self):
        """Browse for script file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Script File", "", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    content = f.read().strip()
                    
                self.file_path_edit.setText(file_path)
                self.script_content.setText(content)
                
                # Parse script info
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                command_count = len(lines)
                total_steps = 0
                
                for line in lines:
                    if line.startswith("TURN:"):
                        parts = line.split(":")
                        if len(parts) >= 2:
                            try:
                                total_steps += int(parts[1])
                            except ValueError:
                                pass
                                
                info_text = f"Commands: {command_count}, Total Steps: {total_steps:,}"
                self.script_info.setText(info_text)
                self.upload_btn.setEnabled(True)
                
                self.loaded_script = lines
                self.log_message(f"Script loaded: {file_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"Failed to load script: {str(e)}")
                
    def upload_script(self):
        """Upload and execute script"""
        if not hasattr(self, 'loaded_script'):
            QMessageBox.warning(self, "Upload Error", "Please load a script first")
            return
            
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Upload Error", "Please connect to Arduino first")
            return
            
        # Show progress dialog
        self.progress_dialog = ProgressDialog("Executing Script", self)
        self.progress_dialog.stop_btn.clicked.connect(self.stop_script)
        self.progress_dialog.emergency_btn.clicked.connect(self.emergency_stop)
        self.progress_dialog.show()
        
        # Start script execution
        self.serial_worker.queue_commands(self.loaded_script)
        self.serial_worker.start()
        
    def manual_turn(self):
        """Execute manual turn"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Control Error", "Please connect to Arduino first")
            return
            
        steps = self.manual_steps.value()
        direction = self.manual_direction.currentText()
        command = f"TURN:{steps}:{direction}"
        
        # Check if chunking is needed
        chunk_size = self.config.get("chunk_size", 32000)
        if steps > chunk_size:
            self.send_chunked_command(command)
        else:
            self.send_command(command)
            
    def send_chunked_command(self, command: str):
        """Send a command that may need to be chunked"""
        chunks = self.serial_worker._chunk_large_command(command)
        if len(chunks) > 1:
            # Multiple chunks - show progress and send sequentially
            total_chunks = len(chunks)
            self.log_message(f"Large command detected - splitting into {total_chunks} chunks")
            
            # Create a simple progress tracking
            for i, chunk_command in enumerate(chunks, 1):
                self.log_message(f"Sending chunk {i}/{total_chunks}: {chunk_command}")
                self.serial_worker.send_command(chunk_command)
                # Small delay between chunks to ensure proper execution
                time.sleep(0.1)
            
            self.log_message(f"All {total_chunks} chunks sent successfully")
        else:
            # Single command
            self.send_command(command)
            
    def check_manual_chunking(self):
        """Check if manual command will need chunking and update info"""
        steps = self.manual_steps.value()
        chunk_size = self.config.get("chunk_size", 32000)
        
        if steps > chunk_size:
            num_chunks = (steps + chunk_size - 1) // chunk_size
            self.chunking_info.setText(f"⚠️ Large command will be split into {num_chunks} chunks")
            self.chunking_info.setStyleSheet("QLabel { color: #FF6B35; font-size: 11px; font-style: italic; }")
        else:
            self.chunking_info.setText("✅ Single command")
            self.chunking_info.setStyleSheet("QLabel { color: #4CAF50; font-size: 11px; font-style: italic; }")
        
    def send_command(self, command: str):
        """Send single command to Arduino"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Control Error", "Please connect to Arduino first")
            return
            
        self.serial_worker.send_command(command)
        self.log_message(f"Sent: {command}")
        
    def send_custom_command(self):
        """Send custom command"""
        command = self.custom_command.text().strip()
        if command:
            self.send_command(command)
            self.custom_command.clear()
            
    def stop_script(self):
        """Stop current script execution"""
        self.serial_worker.stop_operation()
        if self.progress_dialog:
            self.progress_dialog.accept()
            
    def emergency_stop(self):
        """Emergency stop - immediately stop motor"""
        self.send_command("STOP")
        self.serial_worker.stop_operation()
        if self.progress_dialog:
            self.progress_dialog.accept()
            
    # Signal handlers
    @pyqtSlot(str)
    def on_arduino_response(self, response: str):
        """Handle Arduino response"""
        # Clean up the response
        response = response.strip()
        
        # Special handling for distance readings
        if response.startswith("Distance:"):
            # Reset the pending flag
            self.distance_request_pending = False
            
            # Extract distance value and highlight it
            distance_parts = response.split(":", 1)  # Split only on first colon
            if len(distance_parts) >= 2:
                distance_value = distance_parts[1].strip()
                if "ERROR" in distance_value:
                    self.log_message(f"❌ HC-SR04 Error: {distance_value}")
                elif self.distance_monitoring_enabled:
                    self.log_message(f"📏 HC-SR04 Distance: {distance_value}")
                else:
                    self.log_message(f"📏 Arduino Distance Reading: {distance_value}")
            else:
                self.log_message(f"Arduino: {response}")
        # Special handling for needle count
        elif response.startswith("Needle count:"):
            needle_parts = response.split(":", 1)  # Split only on first colon
            if len(needle_parts) >= 2:
                count_value = needle_parts[1].strip()
                self.log_message(f"🧷 Needle Count: {count_value}")
            else:
                self.log_message(f"Arduino: {response}")
        # Handle debug messages
        elif response.startswith("DEBUG:"):
            if self.distance_monitoring_enabled:
                # Only show debug during active monitoring
                self.log_message(f"🔧 {response}")
        # Handle other important responses with icons
        elif "reset" in response.lower() and "needle" in response.lower():
            self.log_message(f"🔄 {response}")
        elif response == "OK" and self.distance_monitoring_enabled:
            # Don't log simple OK responses during monitoring to reduce clutter
            pass
        else:
            self.log_message(f"Arduino: {response}")
        
    @pyqtSlot(str)
    def on_arduino_error(self, error: str):
        """Handle Arduino error"""
        self.log_message(f"Error: {error}")
        QMessageBox.critical(self, "Arduino Error", error)
        
    @pyqtSlot(int, int)
    def on_progress_update(self, current: int, total: int):
        """Handle progress update"""
        if self.progress_dialog:
            self.progress_dialog.update_progress(current, total)
            
    @pyqtSlot()
    def on_operation_complete(self):
        """Handle operation completion"""
        self.log_message("Script execution completed")
        if self.progress_dialog:
            self.progress_dialog.accept()
            self.progress_dialog = None
            
    def log_message(self, message: str):
        """Log message to console with immediate UI update"""
        timestamp = time.strftime("%H:%M:%S")
        self.console_output.append(f"[{timestamp}] {message}")
        
        # Ensure the console scrolls to the bottom immediately
        cursor = self.console_output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.console_output.setTextCursor(cursor)
        
    def toggle_distance_monitoring(self):
        """Toggle real-time distance monitoring"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Monitoring Error", "Please connect to Arduino first")
            return
            
        if self.distance_monitoring_enabled:
            # Stop monitoring
            self.distance_timer.stop()
            self.distance_monitoring_enabled = False
            self.distance_request_pending = False  # Reset the flag
            self.monitor_distance_btn.setText("Start Distance Monitoring")
            self.log_message("Distance monitoring stopped")
        else:
            # Start monitoring
            self.distance_monitoring_enabled = True
            self.distance_timer.start(500)  # Update every 500ms (2 times per second) - safer interval
            self.monitor_distance_btn.setText("Stop Distance Monitoring")
            self.log_message("Distance monitoring started (updates 2x per second)")
            
    def check_for_responses(self):
        """Check for Arduino responses without blocking"""
        if self.connect_btn.text() == "Disconnect":
            response = self.serial_worker.check_distance_response()
            if response:
                self.on_arduino_response(response)
    
    def update_distance_reading(self):
        """Update distance reading from HC-SR04 sensor"""
        if (self.connect_btn.text() == "Disconnect" and 
            self.distance_monitoring_enabled and 
            not self.distance_request_pending):
            
            # Set flag to prevent overlapping requests
            self.distance_request_pending = True
            
            # Send distance command with minimal blocking
            success = self.serial_worker.send_distance_command_lightweight()
            if not success:
                self.distance_request_pending = False  # Reset on failure
            
    def test_sensor(self):
        """Test HC-SR04 sensor with multiple readings"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Test Error", "Please connect to Arduino first")
            return
            
        self.log_message("🧪 Starting HC-SR04 sensor test (5 readings)...")
        for i in range(5):
            self.log_message(f"Test reading {i+1}/5:")
            self.serial_worker.send_command("DISTANCE")
            # Small delay between readings
            QTimer.singleShot(500 * (i+1), lambda: None)  # Staggered timing
        
    def refresh_ui_elements(self):
        """Refresh UI elements for smoother operation"""
        try:
            # Update connection status indicator if needed (without processEvents to avoid recursion)
            if hasattr(self, 'status_label'):
                if self.connect_btn.text() == "Disconnect":
                    if not hasattr(self, '_last_connection_status') or self._last_connection_status != "connected":
                        self.status_label.setText("🔗 Connected")
                        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                        self._last_connection_status = "connected"
                else:
                    if not hasattr(self, '_last_connection_status') or self._last_connection_status != "disconnected":
                        self.status_label.setText("❌ Disconnected")
                        self.status_label.setStyleSheet("color: #F44336; font-weight: bold;")
                        self._last_connection_status = "disconnected"
                        
        except Exception as e:
            # Silently handle any refresh errors to prevent crashes
            pass
        
    def closeEvent(self, event):
        """Handle application close"""
        # Stop all timers and monitoring
        if self.distance_monitoring_enabled:
            self.distance_timer.stop()
            self.distance_monitoring_enabled = False
            self.distance_request_pending = False
            
        if hasattr(self, 'ui_refresh_timer'):
            self.ui_refresh_timer.stop()
            
        if hasattr(self, 'response_checker'):
            self.response_checker.stop()
            
        if self.serial_worker.is_running:
            self.serial_worker.stop_operation()
            self.serial_worker.wait(3000)  # Wait up to 3 seconds
            
        self.serial_worker.disconnect_arduino()
        event.accept()


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("Sentro Knitting Machine Controller")
    app.setOrganizationName("Knitting Solutions")
    
    # Set application style
    app.setStyle('Fusion')
    
    # Create and show main window
    window = KnittingMachineGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
