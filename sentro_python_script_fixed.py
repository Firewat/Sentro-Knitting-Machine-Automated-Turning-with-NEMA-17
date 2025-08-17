#!/usr/bin/env python3
"""
Sentro Knitting Machine Controller - PyQt6 Version
Modern, Professional GUI for Arduino-based knitting machine control
Focus: Needle-based pattern creation and execution
"""

import sys
import json
import os
import serial
import serial.tools.list_ports
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List

class PatternStep:
    """Represents a single step in a knitting pattern"""
    def __init__(self, needles: int, direction: str, rows: int = 1, description: str = ""):
        self.needles = needles  # Needles per row
        self.direction = direction  # "CW" or "CCW"  
        self.rows = rows  # Number of rows
        self.description = description or f"{needles} needles × {rows} rows {direction}"
        
    def get_total_needles(self) -> int:
        """Calculate total needles for this step (needles per row × number of rows)"""
        return self.needles * self.rows
        
    def to_dict(self) -> Dict:
        return {
            "needles": self.needles,
            "direction": self.direction,
            "rows": self.rows,
            "description": self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict):
        # Handle backward compatibility with old repeat_count field
        rows = data.get("rows", data.get("repeat_count", 1))
        step = cls(data["needles"], data["direction"], rows, data.get("description", ""))
        return step

class KnittingPattern:
    """Represents a complete knitting pattern"""
    def __init__(self, name: str = "New Pattern"):
        self.name = name
        self.steps: List[PatternStep] = []
        self.description = ""
        self.repetitions = 1  # Number of times to repeat the entire pattern
    
    def add_step(self, step: PatternStep):
        self.steps.append(step)
    
    def remove_step(self, index: int):
        if 0 <= index < len(self.steps):
            del self.steps[index]
    
    def get_total_needles(self) -> int:
        return sum(step.get_total_needles() for step in self.steps) * self.repetitions
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "repetitions": self.repetitions,
            "steps": [step.to_dict() for step in self.steps]
        }
    
    @classmethod
    def from_dict(cls, data: Dict):
        pattern = cls(data.get("name", "Unnamed Pattern"))
        pattern.description = data.get("description", "")
        pattern.repetitions = data.get("repetitions", 1)
        pattern.steps = [PatternStep.from_dict(step_data) for step_data in data.get("steps", [])]
        return pattern

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QGridLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox, 
    QSpinBox, QProgressBar, QFileDialog, QMessageBox, QTabWidget,
    QScrollArea, QFrame, QSplitter, QGroupBox, QDialog, QDialogButtonBox,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, pyqtSlot
)
from PyQt6.QtGui import QFont, QPalette, QColor, QIcon


class NoWheelSpinBox(QSpinBox):
    """Custom QSpinBox that ignores mouse wheel events"""
    def wheelEvent(self, event):
        # Ignore wheel events to prevent accidental value changes
        event.ignore()


class NoWheelComboBox(QComboBox):
    """Custom QComboBox that ignores mouse wheel events"""
    def wheelEvent(self, event):
        # Ignore wheel events to prevent accidental value changes
        event.ignore()


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
            
    def send_motor_command_with_monitoring(self, command: str):
        """Send motor command while allowing needle monitoring to continue"""
        if not self.serial_port or not self.serial_port.is_open:
            self.error_occurred.emit("Arduino not connected")
            return False
            
        try:
            print(f"DEBUG: Sending motor command with monitoring: {command}")
            
            # Send command without clearing buffers (to preserve needle responses)
            self.serial_port.write(f"{command}\n".encode('ascii'))
            self.serial_port.flush()
            
            # Signal that we should start reading responses in background
            self.response_received.emit("MOTOR_COMMAND_SENT")
            
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"Motor command failed: {str(e)}")
            return False
    
    def send_needle_command_lightweight(self):
        """Send needle count command with minimal blocking"""
        if not self.serial_port or not self.serial_port.is_open:
            return False
            
        try:
            # Clear any pending input first
            if self.serial_port.in_waiting > 0:
                self.serial_port.reset_input_buffer()
            
            # Send command quickly
            self.serial_port.write(b"NEEDLE_COUNT\n")
            self.serial_port.flush()
            return True
        except Exception as e:
            self.error_occurred.emit(f"Needle command failed: {str(e)}")
            return False
    
    def check_needle_response(self):
        """Check for any Arduino response without blocking"""
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
        self.patterns_file = "knitting_patterns.json"
        self.config = self.load_config()
        
        # Initialize serial worker
        chunk_size = self.config.get("chunk_size", 32000)
        self.serial_worker = SerialWorker(chunk_size)
        self.setup_signals()
        
        # Initialize needle count window reference
        self.needle_window = None
        
        # Initialize pattern management
        self.current_pattern = KnittingPattern()
        self.saved_patterns: List[KnittingPattern] = self.load_patterns()
        self.pattern_execution_index = 0  # Track current step in pattern execution
        self.pattern_repetition_index = 0  # Track current pattern repetition
        self.pattern_execution_stopped = False  # Flag to immediately stop pattern execution
        
        # Initialize UI
        self.init_ui()
        self.apply_modern_styling()
        self.load_settings_ui()
        
        # Progress dialog
        self.progress_dialog: Optional[ProgressDialog] = None
        
        # Needle counting timer
        self.needle_timer = QTimer()
        self.needle_timer.timeout.connect(self.update_needle_reading)
        self.needle_monitoring_enabled = False
        self.needle_request_pending = False  # Prevent overlapping requests
        self.concurrent_monitoring = False  # Flag for concurrent operations
        
        # Needle position tracking
        self.current_needle_position = 0  # Track current needle position
        self.total_needles_on_machine = 48  # Default, can be configured
        
        # Response checker timer for non-blocking serial reading
        self.response_checker = QTimer()
        self.response_checker.timeout.connect(self.check_for_responses)
        self.response_checker.start(30)  # Check every 30ms for responses (faster during concurrent ops)
        
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
            "chunk_size": 32000,
            "theme": "Pink/Rose"
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
    
    def load_patterns(self) -> List[KnittingPattern]:
        """Load saved patterns from file"""
        try:
            with open(self.patterns_file, 'r') as f:
                patterns_data = json.load(f)
                return [KnittingPattern.from_dict(pattern_data) for pattern_data in patterns_data]
        except FileNotFoundError:
            return []
        except Exception as e:
            print(f"Error loading patterns: {e}")
            return []
    
    def save_patterns(self):
        """Save patterns to file"""
        try:
            patterns_data = [pattern.to_dict() for pattern in self.saved_patterns]
            with open(self.patterns_file, 'w') as f:
                json.dump(patterns_data, f, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "Patterns Error", f"Failed to save patterns: {str(e)}")
            
    def setup_signals(self):
        """Setup signal connections"""
        self.serial_worker.response_received.connect(self.on_arduino_response)
        self.serial_worker.error_occurred.connect(self.on_arduino_error)
        self.serial_worker.progress_updated.connect(self.on_progress_update)
        self.serial_worker.operation_completed.connect(self.on_operation_complete)
        
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Sentro Knitting Machine - Pattern Builder & Controller")
        self.setMinimumSize(1200, 800)
        
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
        
        # Set splitter proportions (75% control panel, 25% console)
        splitter.setSizes([750, 250])
        
    def create_control_panel(self, parent):
        """Create the main control panel"""
        control_widget = QWidget()
        layout = QVBoxLayout(control_widget)
        
        # Connection section
        conn_group = QGroupBox("Arduino Connection")
        conn_layout = QGridLayout(conn_group)
        
        conn_layout.addWidget(QLabel("Port:"), 0, 0)
        self.port_combo = NoWheelComboBox()
        self.refresh_ports()
        conn_layout.addWidget(self.port_combo, 0, 1)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        conn_layout.addWidget(self.refresh_btn, 0, 2)
        
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.connect_btn, 1, 0, 1, 3)
        
        layout.addWidget(conn_group)
        
        # Tab widget for different functions - Reordered for needle-focused workflow
        self.tab_widget = QTabWidget()
        
        # Pattern Builder tab (MAIN FOCUS)
        self.create_pattern_builder_tab()
        
        # Manual Control tab (with both needles and steps)
        self.create_manual_tab()
        
        # Settings tab
        self.create_settings_tab()
        
        layout.addWidget(self.tab_widget)
        
        parent.addWidget(control_widget)
    
    def create_pattern_builder_tab(self):
        """Create the main Pattern Builder tab - needle-focused workflow"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        
        # Make the entire tab scrollable
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        
        # Pattern Information Section
        info_group = QGroupBox("Pattern Information")
        info_layout = QGridLayout(info_group)
        
        info_layout.addWidget(QLabel("Pattern Name:"), 0, 0)
        self.pattern_name_input = QLineEdit(self.current_pattern.name)
        self.pattern_name_input.setPlaceholderText("Enter a descriptive name for your knitting pattern...")
        self.pattern_name_input.textChanged.connect(self.on_pattern_name_changed)
        info_layout.addWidget(self.pattern_name_input, 0, 1)
        
        info_layout.addWidget(QLabel("Description (optional):"), 1, 0)
        self.pattern_description = QTextEdit()
        self.pattern_description.setMaximumHeight(60)
        self.pattern_description.setPlaceholderText("Add notes about yarn, stitch patterns, or special instructions...")
        self.pattern_description.setPlainText(self.current_pattern.description)
        self.pattern_description.textChanged.connect(self.on_pattern_description_changed)
        info_layout.addWidget(self.pattern_description, 1, 1)
        
        info_layout.addWidget(QLabel("Pattern Repetitions:"), 2, 0)
        self.pattern_repetitions_input = NoWheelSpinBox()
        self.pattern_repetitions_input.setMinimum(1)
        self.pattern_repetitions_input.setMaximum(1000)
        self.pattern_repetitions_input.setValue(self.current_pattern.repetitions)
        self.pattern_repetitions_input.setToolTip("Number of times to repeat the entire pattern")
        self.pattern_repetitions_input.valueChanged.connect(self.on_pattern_repetitions_changed)
        info_layout.addWidget(self.pattern_repetitions_input, 2, 1)
        
        layout.addWidget(info_group)
        
        # Step Builder Section
        step_group = QGroupBox("Add Pattern Step")
        step_layout = QGridLayout(step_group)
        
        step_layout.addWidget(QLabel("Needles:"), 0, 0)
        self.step_needles_input = NoWheelSpinBox()
        self.step_needles_input.setMinimum(1)
        self.step_needles_input.setMaximum(10000) 
        self.step_needles_input.setValue(48)
        self.step_needles_input.setStyleSheet("font-size: 16px; font-weight: bold;")
        step_layout.addWidget(self.step_needles_input, 0, 1)
        
        step_layout.addWidget(QLabel("Direction:"), 0, 2)
        self.step_direction_combo = NoWheelComboBox()
        self.step_direction_combo.addItems(["CW", "CCW"])
        self.step_direction_combo.setStyleSheet("font-size: 16px;")
        step_layout.addWidget(self.step_direction_combo, 0, 3)
        
        step_layout.addWidget(QLabel("Rows:"), 1, 0)
        self.step_rows_input = NoWheelSpinBox()
        self.step_rows_input.setMinimum(1)
        self.step_rows_input.setMaximum(1000)
        self.step_rows_input.setValue(1)
        self.step_rows_input.setToolTip("Number of rows (each row = one full rotation)")
        step_layout.addWidget(self.step_rows_input, 1, 1)
        
        step_layout.addWidget(QLabel("Description:"), 1, 2)
        self.step_description_input = QLineEdit()
        self.step_description_input.setPlaceholderText("Optional description...")
        step_layout.addWidget(self.step_description_input, 1, 3)
        
        # Add step button
        self.add_step_btn = QPushButton("Add Step to Pattern")
        self.add_step_btn.clicked.connect(self.add_pattern_step)
        self.add_step_btn.setMinimumHeight(40)
        self.add_step_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #C8E6C9; font-size: 14px; }")
        step_layout.addWidget(self.add_step_btn, 2, 0, 1, 4)
        
        layout.addWidget(step_group)
        
        # Current Pattern Steps List
        steps_group = QGroupBox("Current Pattern Steps")
        steps_layout = QVBoxLayout(steps_group)
        
        # Pattern steps list widget
        self.pattern_steps_list = QListWidget()
        self.pattern_steps_list.setMinimumHeight(200)
        self.pattern_steps_list.setStyleSheet("font-size: 14px;")
        steps_layout.addWidget(self.pattern_steps_list)
        
        # Pattern steps control buttons
        steps_controls_layout = QHBoxLayout()
        
        self.edit_step_btn = QPushButton("Edit Selected")
        self.edit_step_btn.clicked.connect(self.edit_selected_step)
        steps_controls_layout.addWidget(self.edit_step_btn)
        
        self.delete_step_btn = QPushButton("Delete Selected")
        self.delete_step_btn.clicked.connect(self.delete_selected_step)
        steps_controls_layout.addWidget(self.delete_step_btn)
        
        self.move_up_btn = QPushButton("Move Up")
        self.move_up_btn.clicked.connect(self.move_step_up)
        steps_controls_layout.addWidget(self.move_up_btn)
        
        self.move_down_btn = QPushButton("Move Down")
        self.move_down_btn.clicked.connect(self.move_step_down)
        steps_controls_layout.addWidget(self.move_down_btn)
        
        steps_layout.addLayout(steps_controls_layout)
        
        layout.addWidget(steps_group)
        
        # Pattern Summary - Visual Representation
        summary_group = QGroupBox("Pattern Visual Preview")
        summary_layout = QVBoxLayout(summary_group)
        
        # Create a table widget for the pattern visualization (Excel-like grid)
        self.pattern_table = QTableWidget()
        self.pattern_table.setMinimumHeight(120)
        self.pattern_table.setMaximumHeight(300)
        self.pattern_table.setAlternatingRowColors(True)
        self.pattern_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.pattern_table.verticalHeader().setVisible(True)
        self.pattern_table.horizontalHeader().setVisible(True)
        self.pattern_table.setShowGrid(True)
        
        # Make the table look more like Excel
        self.pattern_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #d0d0d0;
                background-color: white;
                alternate-background-color: #f5f5f5;
                selection-background-color: transparent;
            }
            QTableWidget::item {
                padding: 4px;
                text-align: center;
                border: 1px solid #d0d0d0;
            }
            QHeaderView::section {
                background-color: #e0e0e0;
                font-weight: bold;
                padding: 4px;
                border: 1px solid #b0b0b0;
            }
        """)
        
        summary_layout.addWidget(self.pattern_table)
        
        # Add pattern info label below the visual
        self.pattern_info_label = QLabel()
        self.pattern_info_label.setStyleSheet("font-size: 12px; color: #666; padding: 5px;")
        self.pattern_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pattern_info_label.setWordWrap(True)
        summary_layout.addWidget(self.pattern_info_label)
        
        layout.addWidget(summary_group)
        
        # Pattern Management Buttons
        management_group = QGroupBox("Pattern Management")
        management_layout = QGridLayout(management_group)
        
        self.save_pattern_btn = QPushButton("Save Pattern")
        self.save_pattern_btn.clicked.connect(self.save_current_pattern)
        self.save_pattern_btn.setMinimumHeight(40)
        self.save_pattern_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #BBDEFB; }")
        management_layout.addWidget(self.save_pattern_btn, 0, 0)
        
        self.load_pattern_btn = QPushButton("Load Pattern")
        self.load_pattern_btn.clicked.connect(self.load_pattern_dialog)
        self.load_pattern_btn.setMinimumHeight(40)
        management_layout.addWidget(self.load_pattern_btn, 0, 1)
        
        self.new_pattern_btn = QPushButton("New Pattern")
        self.new_pattern_btn.clicked.connect(self.new_pattern)
        self.new_pattern_btn.setMinimumHeight(40)
        management_layout.addWidget(self.new_pattern_btn, 0, 2)
        
        self.execute_pattern_btn = QPushButton("Execute Pattern")
        self.execute_pattern_btn.clicked.connect(self.execute_current_pattern)
        self.execute_pattern_btn.setMinimumHeight(50)
        self.execute_pattern_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                font-weight: bold;
                font-size: 16px;
                border: none;
                border-radius: 6px;
                padding: 12px 20px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #e0e0e0;
                color: #9e9e9e;
            }
        """)
        management_layout.addWidget(self.execute_pattern_btn, 1, 0, 1, 2)  # Span 2 columns instead of 3
        
        # Add Stop Machine button
        self.stop_machine_btn = QPushButton("STOP MACHINE")
        self.stop_machine_btn.clicked.connect(self.stop_machine_immediately)
        self.stop_machine_btn.setMinimumHeight(50)
        self.stop_machine_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-weight: bold;
                font-size: 16px;
                border: none;
                border-radius: 6px;
                padding: 12px 20px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
            QPushButton:pressed {
                background-color: #b71c1c;
            }
            QPushButton:disabled {
                background-color: #e0e0e0;
                color: #9e9e9e;
            }
        """)
        management_layout.addWidget(self.stop_machine_btn, 1, 2)  # Place in column 2
        
        layout.addWidget(management_group)
        
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(widget, "Pattern Builder")
        
        # Initialize the pattern display
        self.update_pattern_display()
        
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
        
        # Current Position & Home Control
        position_group = QGroupBox("Current Position & Home")
        position_layout = QGridLayout(position_group)
        position_layout.setSpacing(15)
        
        # Current needle position display
        self.current_needle_display = QLabel("0")
        self.current_needle_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_needle_display.setStyleSheet("font-size: 48px; font-weight: bold; color: #FF6B9D; padding: 20px; background-color: #F9F9F9; border: 2px solid #DDD; border-radius: 8px;")
        position_layout.addWidget(QLabel("Current Needle Position:"), 0, 0)
        position_layout.addWidget(self.current_needle_display, 0, 1)
        
        # Home button with proper logic
        self.home_btn = QPushButton("🏠 Return to Home (Needle 0)")
        self.home_btn.clicked.connect(self.return_to_home)
        self.home_btn.setMinimumHeight(45)
        self.home_btn.setStyleSheet("QPushButton { font-weight: bold; font-size: 14px; background-color: #4CAF50; color: white; border-radius: 6px; } QPushButton:hover { background-color: #45a049; }")
        position_layout.addWidget(self.home_btn, 1, 0, 1, 2)
        
        layout.addWidget(position_group)
        
        # Needle Control Mode (Main control)
        needle_group = QGroupBox("Needle-Based Control")
        needle_layout = QGridLayout(needle_group)
        needle_layout.setSpacing(15)
        
        # Target needle input
        needle_layout.addWidget(QLabel("Target Needles:"), 0, 0)
        self.needle_target_input = NoWheelSpinBox()
        self.needle_target_input.setMinimum(1)
        self.needle_target_input.setMaximum(10000)
        self.needle_target_input.setValue(48)
        self.needle_target_input.setMinimumHeight(35)
        self.needle_target_input.setStyleSheet("font-size: 16px; padding: 5px;")
        needle_layout.addWidget(self.needle_target_input, 0, 1)
        
        # Direction selection
        needle_layout.addWidget(QLabel("Direction:"), 0, 2)
        self.needle_target_direction = NoWheelComboBox()
        self.needle_target_direction.addItems(["CW", "CCW"])
        self.needle_target_direction.setMinimumHeight(35)
        self.needle_target_direction.setStyleSheet("font-size: 16px; padding: 5px;")
        needle_layout.addWidget(self.needle_target_direction, 0, 3)
        
        # Execute needle control button
        self.start_needle_target_btn = QPushButton("▶️ Turn to Target Needles")
        self.start_needle_target_btn.clicked.connect(self.start_needle_target_mode)
        self.start_needle_target_btn.setMinimumHeight(45)
        self.start_needle_target_btn.setStyleSheet("QPushButton { font-weight: bold; font-size: 16px; background-color: #2196F3; color: white; border-radius: 6px; } QPushButton:hover { background-color: #1976D2; }")
        needle_layout.addWidget(self.start_needle_target_btn, 1, 0, 1, 4)
        
        layout.addWidget(needle_group)
        
        # Needle Sensor Controls
        sensor_group = QGroupBox("Needle Sensor Controls")
        sensor_layout = QGridLayout(sensor_group)
        sensor_layout.setSpacing(10)
        
        self.monitor_needle_btn = QPushButton("Start/Stop Needle Monitoring")
        self.monitor_needle_btn.clicked.connect(self.toggle_needle_monitoring)
        self.monitor_needle_btn.setMinimumHeight(35)
        sensor_layout.addWidget(self.monitor_needle_btn, 0, 0)
        
        self.reset_count_btn = QPushButton("Reset Needle Count")
        self.reset_count_btn.clicked.connect(self.reset_needle_position)
        self.reset_count_btn.setMinimumHeight(35)
        sensor_layout.addWidget(self.reset_count_btn, 0, 1)
        
        self.show_needle_window_btn = QPushButton("Show Needle Window")
        self.show_needle_window_btn.clicked.connect(self.show_needle_count_window)
        self.show_needle_window_btn.setMinimumHeight(35)
        sensor_layout.addWidget(self.show_needle_window_btn, 1, 0, 1, 2)
        
        # Sensor status indicator
        self.sensor_status_label = QLabel("Monitoring: Stopped")
        self.sensor_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sensor_status_label.setStyleSheet("font-size: 14px; color: #666; padding: 8px; background-color: #F0F0F0; border-radius: 4px;")
        sensor_layout.addWidget(self.sensor_status_label, 2, 0, 1, 2)
        
        layout.addWidget(sensor_group)
        
        # Emergency Stop
        emergency_group = QGroupBox("Emergency Control")
        emergency_layout = QVBoxLayout(emergency_group)
        
        self.stop_btn = QPushButton("🛑 EMERGENCY STOP")
        self.stop_btn.clicked.connect(self.stop_machine_immediately)
        self.stop_btn.setMinimumHeight(50)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; font-size: 16px; border-radius: 6px; } QPushButton:hover { background-color: #d32f2f; }")
        emergency_layout.addWidget(self.stop_btn)
        
        layout.addWidget(emergency_group)
        
        # Manual Step Control (moved to bottom, less prominent)
        manual_group = QGroupBox("Manual Step Control (Advanced)")
        manual_layout = QGridLayout(manual_group)
        manual_layout.setSpacing(10)
        
        manual_layout.addWidget(QLabel("Steps:"), 0, 0)
        self.manual_steps = NoWheelSpinBox()
        self.manual_steps.setRange(1, 50000)
        self.manual_steps.setValue(1000)
        self.manual_steps.setMinimumWidth(120)
        self.manual_steps.setMinimumHeight(30)
        self.manual_steps.valueChanged.connect(self.check_manual_chunking)
        manual_layout.addWidget(self.manual_steps, 0, 1)
        
        manual_layout.addWidget(QLabel("Direction:"), 1, 0)
        self.manual_direction = NoWheelComboBox()
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
        
        self.manual_turn_btn = QPushButton("Execute Manual Steps")
        self.manual_turn_btn.clicked.connect(self.manual_turn_with_tracking)
        self.manual_turn_btn.setMinimumHeight(35)
        self.manual_turn_btn.setStyleSheet("QPushButton { font-size: 12px; }")
        manual_layout.addWidget(self.manual_turn_btn, 3, 0, 1, 2)
        
        layout.addWidget(manual_group)
        
        # Custom command (keep at bottom)
        custom_group = QGroupBox("Custom Command")
        custom_layout = QHBoxLayout(custom_group)
        custom_layout.setSpacing(10)
        
        self.custom_command = QLineEdit()
        self.custom_command.setPlaceholderText("Enter custom Arduino command...")
        self.custom_command.returnPressed.connect(self.send_custom_command)
        custom_layout.addWidget(self.custom_command)
        
        self.send_custom_btn = QPushButton("Send")
        self.send_custom_btn.clicked.connect(self.send_custom_command)
        self.send_custom_btn.setMinimumHeight(35)
        custom_layout.addWidget(self.send_custom_btn)
        
        layout.addWidget(custom_group)
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
        
        # Theme Selection
        theme_group = QGroupBox("Application Theme")
        theme_layout = QGridLayout(theme_group)
        theme_layout.setSpacing(10)
        
        theme_layout.addWidget(QLabel("Theme:"), 0, 0)
        self.theme_combo = NoWheelComboBox()
        self.theme_combo.addItems(["Pink/Rose", "Dark", "Light/Grey"])
        self.theme_combo.setCurrentText(self.config.get("theme", "Pink/Rose"))
        self.theme_combo.currentTextChanged.connect(self.on_theme_changed)
        theme_layout.addWidget(self.theme_combo, 0, 1)
        
        theme_info = QLabel("Choose the color theme for the application interface.")
        theme_info.setWordWrap(True)
        theme_info.setStyleSheet("color: #666; font-size: 12px;")
        theme_layout.addWidget(theme_info, 1, 0, 1, 2)
        
        layout.addWidget(theme_group)
        
        # Motor Speed Settings
        speed_group = QGroupBox("Motor Speed Settings")
        speed_layout = QGridLayout(speed_group)
        speed_layout.setSpacing(10)
        
        speed_layout.addWidget(QLabel("Step Delay (microseconds):"), 0, 0)
        self.speed_spinbox = NoWheelSpinBox()
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
        self.micro_combo = NoWheelComboBox()
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
        
        # Steps per Needle setting
        advanced_layout.addWidget(QLabel("Steps per Needle:"), 0, 0)
        self.steps_spinbox = NoWheelSpinBox()
        self.steps_spinbox.setRange(1, 10000)
        self.steps_spinbox.setValue(self.config["steps_per_needle"])
        self.steps_spinbox.setMinimumWidth(120)
        self.steps_spinbox.valueChanged.connect(self.on_steps_changed)
        advanced_layout.addWidget(self.steps_spinbox, 0, 1)
        
        steps_info = QLabel("Number of stepper motor steps per needle position\nTypical values: 800-1200 for most setups")
        steps_info.setWordWrap(True)
        steps_info.setStyleSheet("QLabel { color: #888888; font-size: 12px; margin: 5px; }")
        advanced_layout.addWidget(steps_info, 1, 0, 1, 2)
        
        advanced_layout.addWidget(QLabel("Chunk Size (max steps):"), 2, 0)
        self.chunk_size_spinbox = NoWheelSpinBox()
        self.chunk_size_spinbox.setRange(5000, 32700)
        self.chunk_size_spinbox.setValue(32000)
        self.chunk_size_spinbox.setMinimumWidth(120)
        self.chunk_size_spinbox.valueChanged.connect(self.on_chunk_size_changed)
        advanced_layout.addWidget(self.chunk_size_spinbox, 2, 1)
        
        chunk_info = QLabel("Maximum steps sent in one command to Arduino\nHigher values = fewer commands but near Arduino limit (32767)")
        chunk_info.setWordWrap(True)
        chunk_info.setStyleSheet("QLabel { color: #888888; font-size: 12px; margin: 5px; }")
        advanced_layout.addWidget(chunk_info, 3, 0, 1, 2)
        
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
    
    # ========== PATTERN BUILDER METHODS ==========
    
    def on_pattern_name_changed(self):
        """Handle pattern name change"""
        self.current_pattern.name = self.pattern_name_input.text()
        self.update_pattern_display()
    
    def on_pattern_description_changed(self):
        """Handle pattern description change"""
        self.current_pattern.description = self.pattern_description.toPlainText()
    
    def on_pattern_repetitions_changed(self, value):
        """Handle pattern repetitions change"""
        self.current_pattern.repetitions = value
        self.update_pattern_display()
    
    def add_pattern_step(self):
        """Add a new step to the current pattern"""
        needles = self.step_needles_input.value()
        direction = self.step_direction_combo.currentText()
        rows = self.step_rows_input.value()
        description = self.step_description_input.text().strip()
        
        # Create the step
        step = PatternStep(needles, direction, rows, description)
        
        # Add to current pattern
        self.current_pattern.add_step(step)
        
        # Update display
        self.update_pattern_display()
        
        # Clear input fields
        self.step_description_input.clear()
        
        # Log the addition
        total_needles = needles * rows
        self.log_message(f"Added step: {needles} needles × {rows} rows = {total_needles} total needles {direction}")
    
    def edit_selected_step(self):
        """Edit the selected pattern step"""
        current_row = self.pattern_steps_list.currentRow()
        if current_row >= 0 and current_row < len(self.current_pattern.steps):
            step = self.current_pattern.steps[current_row]
            
            # Create edit dialog
            dialog = QDialog(self)
            dialog.setWindowTitle("Edit Pattern Step")
            dialog.setModal(True)
            layout = QVBoxLayout(dialog)
            
            # Form fields
            form_layout = QGridLayout()
            
            needles_input = NoWheelSpinBox()
            needles_input.setMinimum(1)
            needles_input.setMaximum(10000)
            needles_input.setValue(step.needles)
            form_layout.addWidget(QLabel("Needles:"), 0, 0)
            form_layout.addWidget(needles_input, 0, 1)
            
            direction_combo = NoWheelComboBox()
            direction_combo.addItems(["CW", "CCW"])
            direction_combo.setCurrentText(step.direction)
            form_layout.addWidget(QLabel("Direction:"), 1, 0)
            form_layout.addWidget(direction_combo, 1, 1)
            
            rows_input = NoWheelSpinBox()
            rows_input.setMinimum(1)
            rows_input.setMaximum(1000)
            rows_input.setValue(step.rows)
            rows_input.setToolTip("Number of rows (each row = one full rotation)")
            form_layout.addWidget(QLabel("Rows:"), 2, 0)
            form_layout.addWidget(rows_input, 2, 1)
            
            desc_input = QLineEdit(step.description)
            form_layout.addWidget(QLabel("Description:"), 3, 0)
            form_layout.addWidget(desc_input, 3, 1)
            
            layout.addLayout(form_layout)
            
            # Buttons
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                step.needles = needles_input.value()
                step.direction = direction_combo.currentText()
                step.rows = rows_input.value()
                step.description = desc_input.text().strip()
                
                self.update_pattern_display()
                self.log_message(f"Edited step {current_row + 1}: {step.needles} needles × {step.rows} rows = {step.get_total_needles()} total needles")
    
    def delete_selected_step(self):
        """Delete the selected pattern step"""
        current_row = self.pattern_steps_list.currentRow()
        if current_row >= 0 and current_row < len(self.current_pattern.steps):
            step = self.current_pattern.steps[current_row]
            reply = QMessageBox.question(
                self, "Delete Step", 
                f"Delete step: {step.description}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.current_pattern.remove_step(current_row)
                self.update_pattern_display()
                self.log_message(f"Deleted step {current_row + 1}")
    
    def move_step_up(self):
        """Move selected step up"""
        current_row = self.pattern_steps_list.currentRow()
        if current_row > 0:
            # Swap steps
            steps = self.current_pattern.steps
            steps[current_row], steps[current_row - 1] = steps[current_row - 1], steps[current_row]
            
            self.update_pattern_display()
            self.pattern_steps_list.setCurrentRow(current_row - 1)
            self.log_message(f"Moved step {current_row + 1} up")
    
    def move_step_down(self):
        """Move selected step down"""
        current_row = self.pattern_steps_list.currentRow()
        if current_row >= 0 and current_row < len(self.current_pattern.steps) - 1:
            # Swap steps  
            steps = self.current_pattern.steps
            steps[current_row], steps[current_row + 1] = steps[current_row + 1], steps[current_row]
            
            self.update_pattern_display()
            self.pattern_steps_list.setCurrentRow(current_row + 1)
            self.log_message(f"Moved step {current_row + 1} down")
    
    def update_pattern_display(self):
        """Update the pattern steps display"""
        self.pattern_steps_list.clear()
        
        total_needles = 0
        for i, step in enumerate(self.current_pattern.steps):
            step_needles = step.get_total_needles()  # needles per row × rows
            total_needles += step_needles
            
            # Create display text
            rows_text = f" × {step.rows} rows" if step.rows > 1 else ""
            display_text = f"{i+1}. {step.needles} needles{rows_text} {step.direction} = {step_needles} total"
            if step.description:
                display_text += f" - {step.description}"
            
            item = QListWidgetItem(display_text)
            # Color code by direction
            if step.direction == "CW":
                item.setBackground(QColor("#E8F5E8"))  # Light green
            else:
                item.setBackground(QColor("#FFF0F0"))  # Light red
            
            self.pattern_steps_list.addItem(item)
        
        # Update visual pattern representation
        self.update_pattern_visual()
    
    def update_pattern_visual(self):
        """Create an Excel-like table visualization of the knitting pattern"""
        # Clear the table
        self.pattern_table.clear()
        
        step_count = len(self.current_pattern.steps)
        if step_count == 0:
            # Show empty state
            self.pattern_table.setRowCount(1)
            self.pattern_table.setColumnCount(1)
            self.pattern_table.setHorizontalHeaderLabels(["Pattern"])
            self.pattern_table.setVerticalHeaderLabels(["Info"])
            
            item = QTableWidgetItem("Add steps to see pattern preview")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.pattern_table.setItem(0, 0, item)
            self.pattern_table.resizeColumnsToContents()
            self.pattern_info_label.setText("No pattern created yet")
            return
        
        # Calculate grid dimensions
        max_needles = 0
        total_rows = 0
        
        # First pass: determine grid size
        for step in self.current_pattern.steps:
            max_needles = max(max_needles, step.needles)
            total_rows += step.rows
        
        # Account for repetitions
        total_rows_with_reps = total_rows * self.current_pattern.repetitions
        
        # Set up the table
        self.pattern_table.setRowCount(total_rows_with_reps)
        self.pattern_table.setColumnCount(max_needles)
        
        # Create column headers (needle numbers)
        column_headers = [f"N{i+1}" for i in range(max_needles)]
        self.pattern_table.setHorizontalHeaderLabels(column_headers)
        
        # Fill the table with pattern data
        current_row = 0
        
        for rep in range(self.current_pattern.repetitions):
            for step_idx, step in enumerate(self.current_pattern.steps):
                # Determine colors for this step
                if step.direction == "CW":
                    bg_color = QColor("#E3F2FD")  # Light blue
                    symbol = "↻"
                else:
                    bg_color = QColor("#FFEBEE")  # Light red
                    symbol = "↺"
                
                # Fill rows for this step
                for row in range(step.rows):
                    # Set row header
                    row_label = f"R{current_row + 1}"
                    if self.current_pattern.repetitions > 1:
                        row_label += f" (Rep {rep + 1}, Step {step_idx + 1})"
                    else:
                        row_label += f" (Step {step_idx + 1})"
                    
                    self.pattern_table.setVerticalHeaderItem(current_row, QTableWidgetItem(row_label))
                    
                    # Fill needle columns for this row
                    for needle in range(max_needles):
                        item = QTableWidgetItem()
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                        
                        if needle < step.needles:
                            # This needle is used in this step
                            item.setText(f"{step.direction}\n{symbol}")
                            item.setBackground(bg_color)
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        else:
                            # This needle is not used
                            item.setText("-")
                            item.setBackground(QColor("#F5F5F5"))
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        
                        self.pattern_table.setItem(current_row, needle, item)
                    
                    current_row += 1
        
        # Resize table appropriately
        self.pattern_table.resizeColumnsToContents()
        self.pattern_table.resizeRowsToContents()
        
        # Set uniform column widths for better Excel-like appearance
        header = self.pattern_table.horizontalHeader()
        header.setDefaultSectionSize(60)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        
        # Update info label
        total_needles = self.current_pattern.get_total_needles()
        total_needles_with_reps = total_needles * self.current_pattern.repetitions
        rep_text = f" (×{self.current_pattern.repetitions} = {total_needles_with_reps} total)" if self.current_pattern.repetitions > 1 else ""
        avg_needles = total_needles / step_count if step_count > 0 else 0
        
        self.pattern_info_label.setText(
            f"Grid: {total_rows_with_reps} rows × {max_needles} needles | "
            f"Pattern: {step_count} steps, {total_needles} needles per cycle{rep_text} | "
            f"Blue=CW ↻, Red=CCW ↺ | Average: {avg_needles:.1f} needles/step"
        )
    
    def save_current_pattern(self):
        """Save the current pattern to the saved patterns list"""
        if not self.current_pattern.steps:
            QMessageBox.warning(self, "Save Pattern", "Cannot save empty pattern!")
            return
        
        # Check if pattern with this name already exists
        existing_pattern = None
        for pattern in self.saved_patterns:
            if pattern.name == self.current_pattern.name:
                existing_pattern = pattern
                break
        
        if existing_pattern:
            reply = QMessageBox.question(
                self, "Pattern Exists", 
                f"Pattern '{self.current_pattern.name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
            
            # Replace existing pattern
            index = self.saved_patterns.index(existing_pattern)
            self.saved_patterns[index] = KnittingPattern.from_dict(self.current_pattern.to_dict())
        else:
            # Add new pattern
            self.saved_patterns.append(KnittingPattern.from_dict(self.current_pattern.to_dict()))
        
        # Save to file
        self.save_patterns()
        self.log_message(f"Pattern '{self.current_pattern.name}' saved successfully")
    
    def load_pattern_dialog(self):
        """Show dialog to load a saved pattern"""
        if not self.saved_patterns:
            QMessageBox.information(self, "Load Pattern", "No saved patterns available!")
            return
        
        # Create selection dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Load Pattern")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("Select pattern to load:"))
        
        pattern_list = QListWidget()
        for pattern in self.saved_patterns:
            total_needles = pattern.get_total_needles()
            item_text = f"{pattern.name} ({len(pattern.steps)} steps, {total_needles} needles)"
            pattern_list.addItem(item_text)
        
        layout.addWidget(pattern_list)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_row = pattern_list.currentRow()
            if selected_row >= 0:
                self.load_pattern(self.saved_patterns[selected_row])
    
    def load_pattern(self, pattern: KnittingPattern):
        """Load a pattern into the current editor"""
        self.current_pattern = KnittingPattern.from_dict(pattern.to_dict())
        
        # Update UI
        self.pattern_name_input.setText(self.current_pattern.name)
        self.pattern_description.setPlainText(self.current_pattern.description)
        if hasattr(self, 'pattern_repetitions_input'):
            self.pattern_repetitions_input.setValue(self.current_pattern.repetitions)
        self.update_pattern_display()
        
        self.log_message(f"Loaded pattern '{pattern.name}'")
    
    def new_pattern(self):
        """Create a new empty pattern"""
        if self.current_pattern.steps:
            reply = QMessageBox.question(
                self, "New Pattern",
                "Current pattern will be lost. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        self.current_pattern = KnittingPattern("New Pattern")
        self.pattern_name_input.setText(self.current_pattern.name)
        self.pattern_description.setPlainText("")
        if hasattr(self, 'pattern_repetitions_input'):
            self.pattern_repetitions_input.setValue(self.current_pattern.repetitions)
        self.update_pattern_display()
        
        self.log_message("Created new pattern")
    
    def execute_current_pattern(self):
        """Execute the current pattern"""
        if not self.current_pattern.steps:
            QMessageBox.warning(self, "Execute Pattern", "No steps in current pattern!")
            return
        
        # Start execution directly
        self.start_pattern_execution()
    
    def start_pattern_execution(self):
        """Start executing the pattern"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Execution Error", "Please connect to Arduino first!")
            return
        
        if not self.current_pattern.steps:
            QMessageBox.warning(self, "Execution Error", "No pattern to execute!")
            return
        
        self.pattern_execution_index = 0
        self.pattern_repetition_index = 0
        self.pattern_execution_stopped = False  # Reset stop flag
        
        # Show progress dialog
        total_steps = len(self.current_pattern.steps) * self.current_pattern.repetitions
        self.log_message(f"Starting pattern execution: '{self.current_pattern.name}' with {len(self.current_pattern.steps)} steps × {self.current_pattern.repetitions} repetitions = {total_steps} total steps")
        
        self.execute_next_pattern_step()
    
    def execute_next_pattern_step(self):
        """Execute the next step in the pattern"""
        # Check if execution has been stopped
        if self.pattern_execution_stopped:
            self.log_message("Pattern execution stopped by user")
            return
            
        if self.pattern_execution_index >= len(self.current_pattern.steps):
            # Finished current repetition of pattern, check if more repetitions needed
            self.pattern_repetition_index += 1
            if self.pattern_repetition_index >= self.current_pattern.repetitions:
                # All repetitions complete
                self.log_message(f"Pattern execution completed! Executed {self.current_pattern.repetitions} repetitions of {len(self.current_pattern.steps)} steps each.")
                return
            else:
                # Start next repetition
                self.pattern_execution_index = 0
                self.log_message(f"Starting repetition {self.pattern_repetition_index + 1}/{self.current_pattern.repetitions}")
        
        step = self.current_pattern.steps[self.pattern_execution_index]
        
        # Log step execution with repetition info
        step_num = self.pattern_execution_index + 1
        rep_num = self.pattern_repetition_index + 1
        total_steps = len(self.current_pattern.steps)
        total_reps = self.current_pattern.repetitions
        
        total_needles_for_step = step.get_total_needles()  # needles per row × rows
        
        self.log_message(f"Executing step {step_num}/{total_steps} (repetition {rep_num}/{total_reps}): {step.needles} needles × {step.rows} rows = {total_needles_for_step} total needles {step.direction}")
        
        # Check stop flag again right before sending command
        if self.pattern_execution_stopped:
            self.log_message("Pattern execution stopped before sending motor command")
            return
        
        # Send needle target command for the total needles (needles × rows)
        command = f"NEEDLE_TARGET:{total_needles_for_step}:{step.direction}"
        success = self.serial_worker.send_motor_command_with_monitoring(command)
        
        if not success:
            self.log_message("Failed to send command")
            return
        
        # Move to next step
        self.pattern_execution_index += 1
        
        # Continue with next step after a shorter delay (more responsive to stop commands)
        QTimer.singleShot(100, self.execute_next_pattern_step)
    
    def pause_pattern_execution(self):
        """Pause pattern execution"""
        self.serial_worker.send_command("STOP")
        self.log_message("Pattern execution paused")
    
    def stop_pattern_execution(self):
        """Stop pattern execution"""
        self.pattern_execution_stopped = True  # Set stop flag
        self.serial_worker.send_command("STOP")
        self.pattern_execution_index = 0
        self.pattern_repetition_index = 0
        self.log_message("Pattern execution stopped")
    
    def stop_machine_immediately(self):
        """Emergency stop - immediately halt the machine"""
        # Set stop flag immediately to prevent further execution
        self.pattern_execution_stopped = True
        
        # Update UI to show stopping state
        if hasattr(self, 'stop_machine_btn'):
            self.stop_machine_btn.setText("STOPPING...")
            self.stop_machine_btn.setEnabled(False)
        
        if hasattr(self, 'execute_pattern_btn'):
            self.execute_pattern_btn.setEnabled(False)
        
        if hasattr(self, 'serial_worker') and self.serial_worker:
            try:
                # Send stop commands directly through serial port for immediate effect
                if hasattr(self.serial_worker, 'serial_port') and self.serial_worker.serial_port:
                    serial_port = self.serial_worker.serial_port
                    if serial_port.is_open:
                        # Send multiple immediate stop commands
                        for _ in range(3):  # Send 3 times to ensure it gets through
                            serial_port.write(b"STOP\n")
                            serial_port.write(b"EMERGENCY_STOP\n")
                            serial_port.write(b"HALT\n")
                        serial_port.flush()  # Force immediate send
                
                # Also use the worker methods as backup
                self.serial_worker.send_command("STOP")
                self.serial_worker.send_command("EMERGENCY_STOP") 
                self.serial_worker.send_command("HALT")
                
            except Exception as e:
                self.log_message(f"Error during emergency stop: {e}")
            
            # Reset all execution indices
            self.pattern_execution_index = 0
            self.pattern_repetition_index = 0
            
            self.log_message("EMERGENCY STOP - Machine halted immediately!")
            
            # Re-enable UI after a short delay
            QTimer.singleShot(2000, self._reset_stop_button_ui)
            
            # Show message box to confirm the stop
            QMessageBox.information(self, "Machine Stopped", 
                                  "Machine has been stopped immediately!\n\n"
                                  "All pattern execution has been halted.",
                                  QMessageBox.StandardButton.Ok)
        else:
            self._reset_stop_button_ui()  # Reset UI immediately if not connected
            QMessageBox.warning(self, "Not Connected", 
                              "No connection to machine. Please connect first.",
                              QMessageBox.StandardButton.Ok)
    
    def _reset_stop_button_ui(self):
        """Reset the stop button UI after emergency stop"""
        if hasattr(self, 'stop_machine_btn'):
            self.stop_machine_btn.setText("STOP MACHINE")
            self.stop_machine_btn.setEnabled(True)
        
        if hasattr(self, 'execute_pattern_btn'):
            self.execute_pattern_btn.setEnabled(True)
        
    # ========== END PATTERN BUILDER METHODS ==========
        
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
        
    def on_theme_changed(self, theme):
        """Handle theme change"""
        self.config["theme"] = theme
        self.save_config()
        self.apply_theme(theme)
        self.log_message(f"Theme changed to: {theme}")

    def apply_theme(self, theme_name):
        """Apply the selected theme"""
        if theme_name == "Pink/Rose":
            self.apply_pink_theme()
        elif theme_name == "Dark":
            self.apply_dark_theme()
        elif theme_name == "Light/Grey":
            self.apply_light_theme()

    def apply_pink_theme(self):
        """Apply pink/rose theme (current default)"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: white;
                color: #333333;
            }
            
            QWidget {
                background-color: white;
                color: #333333;
            }
            
            QLabel {
                color: #333333;
                font-weight: normal;
                font-size: 14px;
            }
            
            QGroupBox {
                color: #333333;
                font-weight: bold;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 15px;
                background-color: #fafafa;
                font-size: 14px;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #e91e63;
                font-weight: bold;
                font-size: 15px;
            }
            
            QPushButton {
                background-color: #e91e63;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 500;
                font-size: 14px;
                min-height: 25px;
                min-width: 100px;
            }
            
            QPushButton:hover {
                background-color: #c2185b;
            }
            
            QPushButton:pressed {
                background-color: #ad1457;
            }
            
            QPushButton:disabled {
                background-color: #e0e0e0;
                color: #9e9e9e;
            }
            
            QLineEdit, QSpinBox, QComboBox {
                padding: 10px;
                border: 2px solid #e0e0e0;
                border-radius: 6px;
                font-size: 14px;
                color: #333333;
                background-color: white;
                min-height: 20px;
            }
            
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border-color: #e91e63;
                background-color: white;
            }
            
            QTextEdit {
                border: 2px solid #e0e0e0;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
                color: #333333;
                background-color: white;
                font-family: 'Consolas', 'Monaco', monospace;
            }
            
            QTextEdit:focus {
                border-color: #e91e63;
            }
            
            QTabWidget::pane {
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                background-color: white;
            }
            
            QTabWidget::tab-bar {
                alignment: center;
            }
            
            QTabBar::tab {
                background-color: #f5f5f5;
                color: #666666;
                padding: 12px 20px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 14px;
                font-weight: 500;
                min-width: 120px;
            }
            
            QTabBar::tab:selected {
                background-color: #e91e63;
                color: white;
            }
            
            QTabBar::tab:hover:!selected {
                background-color: #fce4ec;
                color: #e91e63;
            }
            
            QListWidget {
                border: 2px solid #e0e0e0;
                border-radius: 6px;
                background-color: white;
                color: #333333;
                font-size: 14px;
                padding: 4px;
            }
            
            QListWidget::item {
                padding: 8px;
                margin: 2px;
                border-radius: 4px;
            }
            
            QListWidget::item:selected {
                background-color: #e91e63;
                color: white;
            }
            
            QListWidget::item:hover:!selected {
                background-color: #fce4ec;
                color: #333333;
            }
            
            QProgressBar {
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                background-color: white;
                color: #333333;
                text-align: center;
                font-weight: bold;
                font-size: 14px;
                min-height: 25px;
            }
            
            QProgressBar::chunk {
                background-color: #e91e63;
                border-radius: 6px;
            }
            
            QScrollArea {
                border: none;
                background-color: white;
            }
            
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #f5f5f5;
                border: 1px solid #e0e0e0;
                width: 20px;
            }
            
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #e91e63;
            }
            
            QComboBox::drop-down {
                border: none;
                background-color: #f5f5f5;
                width: 30px;
            }
            
            QComboBox::down-arrow {
                width: 12px;
                height: 12px;
            }
            
            QComboBox QAbstractItemView {
                border: 2px solid #e0e0e0;
                background-color: white;
                color: #333333;
                selection-background-color: #e91e63;
            }
        """)

    def apply_dark_theme(self):
        """Apply dark theme"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            
            QLabel {
                color: #ffffff;
                font-weight: normal;
                font-size: 14px;
            }
            
            QGroupBox {
                color: #ffffff;
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 15px;
                background-color: #3a3a3a;
                font-size: 14px;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #64b5f6;
                font-weight: bold;
                font-size: 15px;
            }
            
            QPushButton {
                background-color: #64b5f6;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 500;
                font-size: 14px;
                min-height: 25px;
                min-width: 100px;
            }
            
            QPushButton:hover {
                background-color: #42a5f5;
            }
            
            QPushButton:pressed {
                background-color: #1e88e5;
            }
            
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
            
            QLineEdit, QSpinBox, QComboBox {
                padding: 10px;
                border: 2px solid #555555;
                border-radius: 6px;
                font-size: 14px;
                color: #ffffff;
                background-color: #3a3a3a;
                min-height: 20px;
            }
            
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border-color: #64b5f6;
                background-color: #3a3a3a;
            }
            
            QTextEdit {
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
                color: #ffffff;
                background-color: #3a3a3a;
                font-family: 'Consolas', 'Monaco', monospace;
            }
            
            QTextEdit:focus {
                border-color: #64b5f6;
            }
            
            QTabWidget::pane {
                border: 2px solid #555555;
                border-radius: 8px;
                background-color: #2b2b2b;
            }
            
            QTabBar::tab {
                background-color: #3a3a3a;
                color: #ffffff;
                padding: 12px 20px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 14px;
                font-weight: 500;
                min-width: 120px;
            }
            
            QTabBar::tab:selected {
                background-color: #64b5f6;
                color: white;
            }
            
            QTabBar::tab:hover:!selected {
                background-color: #4a4a4a;
                color: #64b5f6;
            }
            
            QListWidget {
                border: 2px solid #555555;
                border-radius: 6px;
                background-color: #3a3a3a;
                color: #ffffff;
                font-size: 14px;
                padding: 4px;
            }
            
            QListWidget::item {
                padding: 8px;
                margin: 2px;
                border-radius: 4px;
            }
            
            QListWidget::item:selected {
                background-color: #64b5f6;
                color: white;
            }
            
            QListWidget::item:hover:!selected {
                background-color: #4a4a4a;
                color: #ffffff;
            }
            
            QProgressBar {
                border: 2px solid #555555;
                border-radius: 8px;
                background-color: #3a3a3a;
                color: #ffffff;
                text-align: center;
                font-weight: bold;
                font-size: 14px;
                min-height: 25px;
            }
            
            QProgressBar::chunk {
                background-color: #64b5f6;
                border-radius: 6px;
            }
            
            QScrollArea {
                border: none;
                background-color: #2b2b2b;
            }
            
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #4a4a4a;
                border: 1px solid #555555;
                width: 20px;
            }
            
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #64b5f6;
            }
            
            QComboBox::drop-down {
                border: none;
                background-color: #4a4a4a;
                width: 30px;
            }
            
            QComboBox QAbstractItemView {
                border: 2px solid #555555;
                background-color: #3a3a3a;
                color: #ffffff;
                selection-background-color: #64b5f6;
            }
        """)

    def apply_light_theme(self):
        """Apply light/grey theme"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
                color: #2e2e2e;
            }
            
            QWidget {
                background-color: #f5f5f5;
                color: #2e2e2e;
            }
            
            QLabel {
                color: #2e2e2e;
                font-weight: normal;
                font-size: 14px;
            }
            
            QGroupBox {
                color: #2e2e2e;
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 15px;
                background-color: #ffffff;
                font-size: 14px;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #607d8b;
                font-weight: bold;
                font-size: 15px;
            }
            
            QPushButton {
                background-color: #607d8b;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 500;
                font-size: 14px;
                min-height: 25px;
                min-width: 100px;
            }
            
            QPushButton:hover {
                background-color: #546e7a;
            }
            
            QPushButton:pressed {
                background-color: #455a64;
            }
            
            QPushButton:disabled {
                background-color: #e0e0e0;
                color: #9e9e9e;
            }
            
            QLineEdit, QSpinBox, QComboBox {
                padding: 10px;
                border: 2px solid #cccccc;
                border-radius: 6px;
                font-size: 14px;
                color: #2e2e2e;
                background-color: white;
                min-height: 20px;
            }
            
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border-color: #607d8b;
                background-color: white;
            }
            
            QTextEdit {
                border: 2px solid #cccccc;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
                color: #2e2e2e;
                background-color: white;
                font-family: 'Consolas', 'Monaco', monospace;
            }
            
            QTextEdit:focus {
                border-color: #607d8b;
            }
            
            QTabWidget::pane {
                border: 2px solid #cccccc;
                border-radius: 8px;
                background-color: white;
            }
            
            QTabBar::tab {
                background-color: #e0e0e0;
                color: #2e2e2e;
                padding: 12px 20px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 14px;
                font-weight: 500;
                min-width: 120px;
            }
            
            QTabBar::tab:selected {
                background-color: #607d8b;
                color: white;
            }
            
            QTabBar::tab:hover:!selected {
                background-color: #f0f0f0;
                color: #607d8b;
            }
            
            QListWidget {
                border: 2px solid #cccccc;
                border-radius: 6px;
                background-color: white;
                color: #2e2e2e;
                font-size: 14px;
                padding: 4px;
            }
            
            QListWidget::item {
                padding: 8px;
                margin: 2px;
                border-radius: 4px;
            }
            
            QListWidget::item:selected {
                background-color: #607d8b;
                color: white;
            }
            
            QListWidget::item:hover:!selected {
                background-color: #f0f0f0;
                color: #2e2e2e;
            }
            
            QProgressBar {
                border: 2px solid #cccccc;
                border-radius: 8px;
                background-color: white;
                color: #2e2e2e;
                text-align: center;
                font-weight: bold;
                font-size: 14px;
                min-height: 25px;
            }
            
            QProgressBar::chunk {
                background-color: #607d8b;
                border-radius: 6px;
            }
            
            QScrollArea {
                border: none;
                background-color: #f5f5f5;
            }
            
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #e0e0e0;
                border: 1px solid #cccccc;
                width: 20px;
            }
            
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #607d8b;
            }
            
            QComboBox::drop-down {
                border: none;
                background-color: #e0e0e0;
                width: 30px;
            }
            
            QComboBox QAbstractItemView {
                border: 2px solid #cccccc;
                background-color: white;
                color: #2e2e2e;
                selection-background-color: #607d8b;
            }
        """)

    def apply_modern_styling(self):
        """Apply the selected theme"""
        theme = self.config.get("theme", "Pink/Rose")
        self.apply_theme(theme)
        
        # Always apply matte green styling to execute button regardless of theme
        if hasattr(self, 'execute_pattern_btn'):
            self.execute_pattern_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4caf50;
                    color: white;
                    border: none;
                    padding: 12px 24px;
                    border-radius: 6px;
                    font-weight: 600;
                    font-size: 14px;
                    min-height: 25px;
                    min-width: 120px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
                QPushButton:pressed {
                    background-color: #3d8b40;
                }
                QPushButton:disabled {
                    background-color: #a5d6a7;
                    color: #ffffff;
                }
            """)
        
        # Always apply red styling to stop button regardless of theme
        if hasattr(self, 'stop_machine_btn'):
            self.stop_machine_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    border: none;
                    padding: 12px 24px;
                    border-radius: 6px;
                    font-weight: 600;
                    font-size: 14px;
                    min-height: 25px;
                    min-width: 120px;
                }
                QPushButton:hover {
                    background-color: #d32f2f;
                }
                QPushButton:pressed {
                    background-color: #b71c1c;
                }
                QPushButton:disabled {
                    background-color: #ffcdd2;
                    color: #ffffff;
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
        
    def manual_turn_with_monitoring(self):
        """Execute manual turn while keeping needle monitoring active"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Control Error", "Please connect to Arduino first")
            return
            
        steps = self.manual_steps.value()
        direction = self.manual_direction.currentText()
        command = f"TURN:{steps}:{direction}"
        
        # Enable concurrent monitoring mode
        self.concurrent_monitoring = True
        
        # Increase needle monitoring frequency during motor operations
        if self.needle_monitoring_enabled:
            self.needle_timer.stop()
            self.needle_timer.start(300)  # Check every 300ms during motor operations
        else:
            # Start needle monitoring automatically for concurrent mode
            self.needle_monitoring_enabled = True
            self.needle_timer.start(300)  # Check every 300ms
            self.monitor_needle_btn.setText("Stop Needle Monitoring")
        
        # Send command without blocking needle monitoring
        success = self.serial_worker.send_motor_command_with_monitoring(command)
        if success:
            self.log_message(f"🔄 Motor turning {steps} steps {direction} (with needle monitoring)")
        else:
            self.concurrent_monitoring = False
            
    def start_needle_target_mode(self):
        """Start needle target mode - run motor until target needles are counted"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Control Error", "Please connect to Arduino first")
            return
            
        target_needles = self.needle_target_input.value()
        direction = self.needle_target_direction.currentText()
        
        # Show confirmation dialog
        reply = QMessageBox.question(
            self, 
            "Needle Target Mode", 
            f"Motor will run {direction} until {target_needles} needles are counted.\n\n"
            f"Current needle count will be the starting point.\n"
            f"You can stop anytime with the STOP button.\n\n"
            f"Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Enable needle monitoring automatically
        if not self.needle_monitoring_enabled:
            self.needle_monitoring_enabled = True
            self.needle_timer.start(300)  # Fast monitoring during target mode
            self.monitor_needle_btn.setText("Stop Needle Monitoring")
        else:
            # Increase frequency for target mode
            self.needle_timer.stop()
            self.needle_timer.start(300)
        
        # Enable concurrent monitoring
        self.concurrent_monitoring = True
        
        # Send needle target command
        command = f"NEEDLE_TARGET:{target_needles}:{direction}"
        success = self.serial_worker.send_motor_command_with_monitoring(command)
        
        if success:
            self.log_message(f"🎯 Needle target mode started: {target_needles} needles {direction}")
            # Disable the button to prevent multiple starts
            self.start_needle_target_btn.setEnabled(False)
            self.start_needle_target_btn.setText("🎯 Target Mode Running...")
            self.start_needle_target_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #FFB74D; }")
        else:
            self.concurrent_monitoring = False
            self.log_message("❌ Failed to start needle target mode")
            
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
            
    def manual_turn_with_tracking(self):
        """Execute manual turn with needle position tracking"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Control Error", "Please connect to Arduino first")
            return
            
        steps = self.manual_steps.value()
        direction = self.manual_direction.currentText()
        
        # Update needle position based on steps
        steps_per_needle = self.config.get("steps_per_needle", 1000)
        needles_moved = steps / steps_per_needle
        
        if direction == "CW":
            self.current_needle_position += needles_moved
        else:
            self.current_needle_position -= needles_moved
            
        # Keep position within bounds (0 to total_needles_on_machine-1)
        self.current_needle_position = self.current_needle_position % self.total_needles_on_machine
        if self.current_needle_position < 0:
            self.current_needle_position += self.total_needles_on_machine
            
        # Update display
        self.current_needle_display.setText(f"{int(self.current_needle_position)}")
        
        # Execute the turn
        command = f"TURN:{steps}:{direction}"
        chunk_size = self.config.get("chunk_size", 32000)
        if steps > chunk_size:
            self.send_chunked_command(command)
        else:
            self.send_command(command)
            
        self.log_message(f"Manual turn: {steps} steps {direction} (Position: {int(self.current_needle_position)})")
        
    def return_to_home(self):
        """Return to needle position 0 (home/white needle)"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Control Error", "Please connect to Arduino first")
            return
        
        if self.current_needle_position == 0:
            self.log_message("✅ Already at home position (needle 0)")
            return
            
        # Calculate the shortest path to home (needle 0)
        current_pos = self.current_needle_position
        total_needles = self.total_needles_on_machine
        
        # Calculate distance going clockwise and counter-clockwise
        cw_distance = -current_pos if current_pos > 0 else 0
        ccw_distance = total_needles - current_pos if current_pos > 0 else 0
        
        # Choose the shorter path
        if abs(cw_distance) <= ccw_distance:
            needles_to_move = abs(cw_distance)
            direction = "CCW"  # Move counter-clockwise to reduce position
        else:
            needles_to_move = ccw_distance
            direction = "CW"  # Move clockwise to wrap around
            
        # Convert needles to steps
        steps_per_needle = self.config.get("steps_per_needle", 1000)
        steps_to_move = int(needles_to_move * steps_per_needle)
        
        if steps_to_move > 0:
            # Execute the movement
            command = f"TURN:{steps_to_move}:{direction}"
            chunk_size = self.config.get("chunk_size", 32000)
            if steps_to_move > chunk_size:
                self.send_chunked_command(command)
            else:
                self.send_command(command)
                
            # Update position to home
            self.current_needle_position = 0
            self.current_needle_display.setText("0")
            
            self.log_message(f"🏠 Returning to home: {needles_to_move:.1f} needles {direction} ({steps_to_move} steps)")
        
    def reset_needle_position(self):
        """Reset the current needle position to 0 and send reset command"""
        self.current_needle_position = 0
        self.current_needle_display.setText("0")
        self.send_command("RESET_COUNT")
        self.log_message("🔄 Needle position reset to 0")
        
    def send_custom_command(self):
        """Send custom command from the text input"""
        command = self.custom_command.text().strip()
        if command:
            self.send_command(command)
            self.custom_command.clear()
            self.log_message(f"📤 Custom command sent: {command}")
            
    def start_continuous_knitting(self):
        """Start continuous knitting with distance monitoring"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Control Error", "Please connect to Arduino first")
            return
            
        # Enable both concurrent monitoring and needle monitoring
        if not self.needle_monitoring_enabled:
            self.toggle_needle_monitoring()
            
        self.concurrent_monitoring = True
        self.log_message("🧶 Continuous knitting mode started (needle monitoring active)")
        
    def stop_continuous_knitting(self):
        """Stop continuous knitting mode"""
        self.concurrent_monitoring = False
        self.serial_worker.send_command("STOP")
        self.log_message("⏹️ Continuous knitting mode stopped")
            
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
            
        # Reset needle target button if it was running
        if hasattr(self, 'start_needle_target_btn') and not self.start_needle_target_btn.isEnabled():
            self.start_needle_target_btn.setEnabled(True)
            self.start_needle_target_btn.setText("🎯 Run Until Target Needles")
            self.start_needle_target_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #FFE0B2; }")
            
    def emergency_stop(self):
        """Emergency stop - immediately stop motor using improved stop mechanism"""
        # Use the same immediate stop functionality as the pattern builder
        self.pattern_execution_stopped = True  # Set stop flag immediately
        
        try:
            # Send stop commands directly through serial port for immediate effect
            if hasattr(self, 'serial_worker') and self.serial_worker and hasattr(self.serial_worker, 'serial_port'):
                serial_port = self.serial_worker.serial_port
                if serial_port and serial_port.is_open:
                    # Send multiple immediate stop commands
                    for _ in range(3):  # Send 3 times to ensure it gets through
                        serial_port.write(b"STOP\n")
                        serial_port.write(b"EMERGENCY_STOP\n")
                        serial_port.write(b"HALT\n")
                    serial_port.flush()  # Force immediate send
            
            # Also use the existing methods as backup
            self.send_command("STOP")
            if hasattr(self.serial_worker, 'stop_operation'):
                self.serial_worker.stop_operation()
                
        except Exception as e:
            self.log_message(f"Error during emergency stop: {e}")
        
        # Reset all execution indices
        self.pattern_execution_index = 0
        self.pattern_repetition_index = 0
        
        # Reset needle target button if it was running
        if hasattr(self, 'start_needle_target_btn') and not self.start_needle_target_btn.isEnabled():
            self.start_needle_target_btn.setEnabled(True)
            self.start_needle_target_btn.setText("🎯 Run Until Target Needles")
            self.start_needle_target_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #FFE0B2; }")
        
        # Close progress dialog if open
        if self.progress_dialog:
            self.progress_dialog.accept()
        
        self.log_message("EMERGENCY STOP - Machine halted immediately from manual control!")
            
    # Signal handlers
    @pyqtSlot(str)
    def on_arduino_response(self, response: str):
        """Handle Arduino response"""
        # Clean up the response
        response = response.strip()
        
        # Special handling for needle detection notifications
        if response.startswith("NEEDLE_DETECTED:"):
            # Extract needle count from notification
            needle_parts = response.split(":", 1)
            if len(needle_parts) >= 2:
                count_value = needle_parts[1].strip()
                self.log_message(f"🧷 Needle detected! Total count: {count_value}")
                # Update real-time display immediately
                self.current_needle_display.setText(count_value)
                self.current_needle_display.setStyleSheet("font-size: 48px; font-weight: bold; color: #FF6B9D; padding: 20px; background-color: #FFF3F8; border: 2px solid #DDD; border-radius: 8px;")
                # Flash effect
                QTimer.singleShot(500, lambda: self.current_needle_display.setStyleSheet("font-size: 48px; font-weight: bold; color: #FF6B9D; padding: 20px; background-color: #F9F9F9; border: 2px solid #DDD; border-radius: 8px;"))
                
                # Sync internal position tracking with sensor reading
                try:
                    self.current_needle_position = float(count_value) % self.total_needles_on_machine
                except (ValueError, TypeError):
                    pass  # Keep existing position if conversion fails
                
                # Update needle count window if it exists
                if hasattr(self, 'needle_window') and self.needle_window:
                    self.needle_window.update_needle_count()
                    self.needle_window.flash_effect()
            return
        
        # Special handling for needle count readings
        elif response.startswith("Needle count:"):
            # Reset the pending flag
            self.needle_request_pending = False
            
            # Extract needle count value
            needle_parts = response.split(":", 1)
            if len(needle_parts) >= 2:
                count_value = needle_parts[1].strip()
                if self.needle_monitoring_enabled or self.concurrent_monitoring:
                    # Enhanced logging for concurrent mode
                    if self.concurrent_monitoring:
                        self.log_message(f"🧷 Needle count (while turning): {count_value}")
                    else:
                        self.log_message(f"🧷 LM393 Needle Count: {count_value}")
                    
                    # Update real-time display
                    self.current_needle_display.setText(count_value)
                    self.current_needle_display.setStyleSheet("font-size: 36px; font-weight: bold; color: #4CAF50; padding: 15px;")
                else:
                    self.log_message(f"🧷 Arduino Needle Count: {count_value}")
                    self.current_needle_display.setText(count_value)
                    self.current_needle_display.setStyleSheet("font-size: 36px; font-weight: bold; color: #FF6B9D; padding: 15px;")
                
                # Update needle count window if it exists
                if hasattr(self, 'needle_window') and self.needle_window:
                    self.needle_window.update_needle_count()
            else:
                self.log_message(f"Arduino: {response}")
        
        # Special handling for sensor status in STATUS response
        elif "Sensor:" in response:
            status_parts = response.split(":", 1)
            if len(status_parts) >= 2:
                status_value = status_parts[1].strip()
                if status_value == "CLEAR":
                    self.sensor_status_label.setText("Status: ✅ Clear")
                    self.sensor_status_label.setStyleSheet("font-size: 12px; color: #4CAF50; padding: 5px;")
                elif status_value == "BLOCKED":
                    self.sensor_status_label.setText("Status: 🚫 Blocked")
                    self.sensor_status_label.setStyleSheet("font-size: 12px; color: #F44336; padding: 5px;")
                else:
                    self.sensor_status_label.setText(f"Status: {status_value}")
                    self.sensor_status_label.setStyleSheet("font-size: 12px; color: #666; padding: 5px;")
            return
        
        # Special handling for motor completion
        elif response == "DONE":
            if self.concurrent_monitoring:
                self.log_message("✅ Motor operation completed (needle monitoring continues)")
                self.concurrent_monitoring = False
                # Reset needle monitoring to normal frequency
                if self.needle_monitoring_enabled:
                    self.needle_timer.stop()
                    self.needle_timer.start(1000)  # Back to 1 second intervals
                
                # Reset needle target button if it was running
                if hasattr(self, 'start_needle_target_btn') and not self.start_needle_target_btn.isEnabled():
                    self.start_needle_target_btn.setEnabled(True)
                    self.start_needle_target_btn.setText("🎯 Run Until Target Needles")
                    self.start_needle_target_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #FFE0B2; }")
            else:
                self.log_message("✅ Operation completed")
        
        # Handle other important responses with icons
        elif "reset" in response.lower() and ("needle" in response.lower() or "count" in response.lower()):
            self.log_message(f"🔄 {response}")
            # Reset display when count is reset
            self.current_needle_display.setText("0")
            self.current_needle_display.setStyleSheet("font-size: 36px; font-weight: bold; color: #FF6B9D; padding: 15px;")
            # Update needle count window if it exists
            if hasattr(self, 'needle_window') and self.needle_window:
                self.needle_window.update_needle_count()
        
        # Special handling for needle target mode messages
        elif "Needle target mode:" in response:
            self.log_message(f"🎯 {response}")
        elif "Target reached!" in response:
            self.log_message(f"🏆 {response}")
        elif "Needle progress:" in response:
            self.log_message(f"📊 {response}")
        elif "Safety timeout" in response or "STOP command received" in response:
            self.log_message(f"⚠️ {response}")
            # Reset button state if target mode was stopped
            if hasattr(self, 'start_needle_target_btn') and not self.start_needle_target_btn.isEnabled():
                self.start_needle_target_btn.setEnabled(True)
                self.start_needle_target_btn.setText("🎯 Run Until Target Needles")
                self.start_needle_target_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #FFE0B2; }")
        
        elif response == "OK" and self.needle_monitoring_enabled:
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
        
    def toggle_needle_monitoring(self):
        """Toggle real-time needle monitoring"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Monitoring Error", "Please connect to Arduino first")
            return
            
        if self.needle_monitoring_enabled:
            # Stop monitoring
            self.needle_timer.stop()
            self.needle_monitoring_enabled = False
            self.needle_request_pending = False  # Reset the flag
            self.monitor_needle_btn.setText("Start Needle Monitoring")
            self.sensor_status_label.setText("Monitoring: Stopped")
            self.sensor_status_label.setStyleSheet("font-size: 14px; color: #666; padding: 8px; background-color: #F0F0F0; border-radius: 4px;")
            self.log_message("Needle monitoring stopped")
        else:
            # Start monitoring
            self.needle_monitoring_enabled = True
            self.needle_timer.start(1000)  # Update every 1000ms (1 time per second) - very safe interval
            self.monitor_needle_btn.setText("Stop Needle Monitoring")
            self.sensor_status_label.setText("Monitoring: Active")
            self.sensor_status_label.setStyleSheet("font-size: 14px; color: white; padding: 8px; background-color: #4CAF50; border-radius: 4px;")
            self.log_message("Needle monitoring started (updates 1x per second)")
            
    def check_for_responses(self):
        """Check for Arduino responses without blocking"""
        if self.connect_btn.text() == "Disconnect":
            response = self.serial_worker.check_needle_response()
            if response:
                # Log all responses for concurrent monitoring
                if self.concurrent_monitoring or self.needle_monitoring_enabled:
                    self.on_arduino_response(response)
                elif not self.needle_monitoring_enabled:
                    # Only log non-needle responses when not monitoring
                    if not response.startswith("Needle count:"):
                        self.on_arduino_response(response)
    
    def update_needle_reading(self):
        """Update needle count reading from LM393 sensor"""
        if (self.connect_btn.text() == "Disconnect" and 
            self.needle_monitoring_enabled and 
            not self.needle_request_pending):
            
            # Set flag to prevent overlapping requests
            self.needle_request_pending = True
            
            # Send needle count command with minimal blocking
            success = self.serial_worker.send_needle_command_lightweight()
            if not success:
                self.needle_request_pending = False  # Reset on failure
            
            # If in concurrent mode, also check for any responses immediately
            if self.concurrent_monitoring:
                response = self.serial_worker.check_needle_response()
                if response:
                    self.on_arduino_response(response)
            
    def test_sensor(self):
        """Test LM393 sensor status"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Test Error", "Please connect to Arduino first")
            return
            
        self.log_message("🧪 Checking LM393 sensor status...")
        self.serial_worker.send_command("STATUS")
        
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
        if self.needle_monitoring_enabled:
            self.needle_timer.stop()
            self.needle_monitoring_enabled = False
            self.needle_request_pending = False
            
        if hasattr(self, 'ui_refresh_timer'):
            self.ui_refresh_timer.stop()
            
        if hasattr(self, 'response_checker'):
            self.response_checker.stop()
            
        if self.serial_worker.is_running:
            self.serial_worker.stop_operation()
            self.serial_worker.wait(3000)  # Wait up to 3 seconds
            
        self.serial_worker.disconnect_arduino()
        event.accept()

    def show_needle_count_window(self):
        """Show a separate window for needle count display"""
        if hasattr(self, 'needle_window') and self.needle_window:
            # If window already exists, just show it
            self.needle_window.show()
            self.needle_window.raise_()
            return
            
        # Create new needle count window
        self.needle_window = NeedleCountWindow(self)
        self.needle_window.show()


class NeedleCountWindow(QWidget):
    """Standalone window to display needle count in large format"""
    
    def __init__(self, parent_controller):
        super().__init__()
        self.parent_controller = parent_controller
        self.init_ui()
        
    def init_ui(self):
        """Initialize the needle count window UI"""
        self.setWindowTitle("Needle Counter")
        self.setFixedSize(300, 200)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        
        # Apply pink theme
        self.setStyleSheet("""
            QWidget {
                background-color: #FFF0F5;
                font-family: Arial, sans-serif;
            }
            QLabel {
                color: #333;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title_label = QLabel("Needles Passed")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #FF6B9D;")
        layout.addWidget(title_label)
        
        # Large needle count display
        self.needle_count_label = QLabel("0")
        self.needle_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.needle_count_label.setStyleSheet("""
            font-size: 64px; 
            font-weight: bold; 
            color: #FF6B9D; 
            background-color: white;
            border: 3px solid #FF6B9D;
            border-radius: 10px;
            padding: 20px;
        """)
        layout.addWidget(self.needle_count_label)
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14px; color: #666;")
        layout.addWidget(self.status_label)
        
        # Connect to parent's needle count updates
        if hasattr(self.parent_controller, 'current_needle_display'):
            # Update this window when main window updates
            self.update_needle_count()
    
    def update_needle_count(self):
        """Update the needle count display"""
        if hasattr(self.parent_controller, 'current_needle_display'):
            current_text = self.parent_controller.current_needle_display.text()
            self.needle_count_label.setText(current_text)
            
            # Update status based on monitoring state
            if hasattr(self.parent_controller, 'needle_monitoring_enabled'):
                if self.parent_controller.needle_monitoring_enabled:
                    self.status_label.setText("Monitoring Active")
                    self.status_label.setStyleSheet("font-size: 14px; color: #4CAF50;")
                else:
                    self.status_label.setText("Monitoring Stopped")
                    self.status_label.setStyleSheet("font-size: 14px; color: #F44336;")
    
    def flash_effect(self):
        """Flash the display when a new needle is detected"""
        original_style = self.needle_count_label.styleSheet()
        flash_style = original_style.replace("background-color: white;", "background-color: #FFE4E1;")
        
        self.needle_count_label.setStyleSheet(flash_style)
        QTimer.singleShot(300, lambda: self.needle_count_label.setStyleSheet(original_style))
    
    def closeEvent(self, event):
        """Handle window close event"""
        self.parent_controller.needle_window = None
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
    window.showMaximized()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
