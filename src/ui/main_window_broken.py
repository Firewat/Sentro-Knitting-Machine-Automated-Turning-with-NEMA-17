#!/usr/bin/env python3
"""
Main GUI Application with Full Functionality
Professional knitting machine controller with all original features
"""

import sys
import json
import serial.tools.list_ports
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QGroupBox, QLabel, QPushButton, QMessageBox,
    QListWidget, QListWidgetItem, QLineEdit, QTextEdit, QSpinBox,
    QComboBox, QFileDialog, QDialog, QDialogButtonBox, QGridLayout,
    QSplitter, QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal, QThread
from PyQt6.QtGui import QIcon, QFont, QColor

# Import our modules
from ..core.controller import KnittingController, MachineState, ExecutionStatus
from ..patterns.models import KnittingPattern, PatternStep
from ..hardware.serial_manager import SerialManager
from ..ui.components import (
    NoWheelSpinBox, NoWheelComboBox, ProgressDialog, ThemeManager
)
from ..ui.pattern_visualizer import PatternVisualizer
from ..utils.logger import get_logger, setup_logging
from config.settings import AppConfig, ThemeConfig, SerialConfig


class MainWindow(QMainWindow):
    """Main application window with full functionality"""
    
    def __init__(self):
        super().__init__()
        self.logger = get_logger(__name__)
        
        # Configuration and data files
        self.config_file = Path("knitting_config.json")
        self.patterns_file = Path("knitting_patterns.json")
        self.config = self._load_config()
        
        # Initialize serial manager
        self.serial_manager = SerialManager()
        self._setup_serial_connections()
        
        # Initialize controller
        self.controller = KnittingController(str(AppConfig.PATTERNS_DIR))
        self.controller.set_callbacks(
            state_callback=self._on_state_change,
            progress_callback=self._on_progress_update,
            error_callback=self._on_error
        )
        
        # Pattern management
        self.current_pattern = KnittingPattern.empty("New Pattern")
        self.saved_patterns: List[KnittingPattern] = self._load_patterns()
        self.pattern_execution_index = 0
        self.pattern_repetition_index = 0
        self.pattern_execution_stopped = False
        
        # Machine state
        self.current_needle_position = 0
        self.total_needles_on_machine = self.config.get("total_needles", 48)
        self.needle_monitoring_enabled = False
        
        # UI state
        self.current_theme = self.config.get("theme", ThemeConfig.DEFAULT_THEME)
        self.progress_dialog: Optional[ProgressDialog] = None
        
        # Setup UI
        self._setup_window()
        self._setup_ui()
        self._setup_timers()
        self._load_settings_ui()
        
        # Apply initial theme
        self._apply_theme()
        
        self.logger.info("Main window initialized with full functionality")
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        default_config = {
            "steps_per_needle": 1000,
            "arduino_port": "",
            "baudrate": 9600,
            "motor_speed": 1000,
            "microstepping": 1,
            "chunk_size": 32000,
            "theme": "Pink/Rose",
            "total_needles": 48
        }
        
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    default_config.update(config)
            return default_config
        except Exception as e:
            self.logger.warning(f"Failed to load config: {e}")
            return default_config
    
    def _save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")
            QMessageBox.warning(self, "Config Error", f"Failed to save config: {str(e)}")
    
    def _load_patterns(self) -> List[KnittingPattern]:
        """Load saved patterns from file"""
        try:
            if self.patterns_file.exists():
                with open(self.patterns_file, 'r') as f:
                    patterns_data = json.load(f)
                    patterns = []
                    for pattern_data in patterns_data:
                        # Convert dict to KnittingPattern
                        pattern = KnittingPattern.empty(pattern_data.get("name", "Unnamed"))
                        pattern = pattern.with_repetitions(pattern_data.get("repetitions", 1))
                        # Add steps
                        for step_data in pattern_data.get("steps", []):
                            step = PatternStep(
                                needles=step_data.get("needles", 1),
                                direction=step_data.get("direction", "CW"),
                                rows=step_data.get("rows", 1),
                                description=step_data.get("description", "")
                            )
                            pattern = pattern.add_step(step)
                        patterns.append(pattern)
                    return patterns
            return []
        except Exception as e:
            self.logger.error(f"Error loading patterns: {e}")
            return []
    
    def _save_patterns(self):
        """Save patterns to file"""
        try:
            patterns_data = []
            for pattern in self.saved_patterns:
                pattern_data = {
                    "name": pattern.name,
                    "description": pattern.description,
                    "repetitions": pattern.repetitions,
                    "steps": []
                }
                for step in pattern.steps:
                    step_data = {
                        "needles": step.needles,
                        "direction": step.direction,
                        "rows": step.rows,
                        "description": step.description
                    }
                    pattern_data["steps"].append(step_data)
                patterns_data.append(pattern_data)
            
            with open(self.patterns_file, 'w') as f:
                json.dump(patterns_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save patterns: {e}")
            QMessageBox.warning(self, "Patterns Error", f"Failed to save patterns: {str(e)}")
    
    def _setup_serial_connections(self):
        """Setup serial manager connections"""
        self.serial_manager.response_received.connect(self._on_arduino_response)
        self.serial_manager.error_occurred.connect(self._on_arduino_error)
        self.serial_manager.progress_updated.connect(self._on_arduino_progress)
        self.serial_manager.operation_completed.connect(self._on_arduino_operation_complete)
    
    def _setup_window(self):
        """Setup main window properties"""
        self.setWindowTitle(f"{AppConfig.APP_NAME} v{AppConfig.APP_VERSION}")
        self.setMinimumSize(AppConfig.WINDOW_MIN_WIDTH, AppConfig.WINDOW_MIN_HEIGHT)
        self.showMaximized()
    
    def _setup_ui(self):
        """Setup main user interface with console and full functionality"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout with splitter for resizable panels
        main_layout = QHBoxLayout(central_widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left panel - Controls (75%)
        self._create_control_panel(splitter)
        
        # Right panel - Console and status (25%)
        self._create_console_panel(splitter)
        
        # Set splitter proportions
        splitter.setSizes([900, 300])  # 75% control, 25% console
        
        # Status bar
        self.statusBar().showMessage("Ready - Connect to Arduino to begin")
    
    def _create_control_panel(self, parent):
        """Create the main control panel with all tabs"""
        control_widget = QWidget()
        layout = QVBoxLayout(control_widget)
        
        # Connection section at top
        conn_group = QGroupBox("Arduino Connection")
        conn_layout = QGridLayout(conn_group)
        
        conn_layout.addWidget(QLabel("Port:"), 0, 0)
        self.port_combo = NoWheelComboBox()
        self._refresh_ports()
        conn_layout.addWidget(self.port_combo, 0, 1)
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_ports)
        conn_layout.addWidget(refresh_btn, 0, 2)
        
        conn_layout.addWidget(QLabel("Baudrate:"), 0, 3)
        self.baudrate_combo = NoWheelComboBox()
        for rate in SerialConfig.BAUDRATES:
            self.baudrate_combo.addItem(str(rate))
        self.baudrate_combo.setCurrentText(str(self.config.get("baudrate", 9600)))
        conn_layout.addWidget(self.baudrate_combo, 0, 4)
        
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._toggle_connection)
        self.connect_btn.setMinimumHeight(40)
        conn_layout.addWidget(self.connect_btn, 1, 0, 1, 5)
        
        layout.addWidget(conn_group)
        
        # Create tab widget for different functions
        self.tab_widget = QTabWidget()
        
        # Create all tabs
        self._create_pattern_builder_tab()
        self._create_manual_control_tab()
        self._create_script_execution_tab()
        self._create_settings_tab()
        
        layout.addWidget(self.tab_widget)
        parent.addWidget(control_widget)
    
    def _create_console_panel(self, parent):
        """Create console and status panel"""
        console_widget = QWidget()
        layout = QVBoxLayout(console_widget)
        
        # Status section
        status_group = QGroupBox("Machine Status")
        status_layout = QVBoxLayout(status_group)
        
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("QLabel { color: #D32F2F; font-weight: bold; font-size: 14px; }")
        status_layout.addWidget(self.status_label)
        
        # Current position display
        self.position_label = QLabel("Position: Unknown")
        self.position_label.setStyleSheet("QLabel { font-size: 12px; }")
        status_layout.addWidget(self.position_label)
        
        # Needle monitoring status
        self.monitoring_label = QLabel("Monitoring: Off")
        self.monitoring_label.setStyleSheet("QLabel { font-size: 12px; }")
        status_layout.addWidget(self.monitoring_label)
        
        layout.addWidget(status_group)
        
        # Console section
        console_group = QGroupBox("Console Output")
        console_layout = QVBoxLayout(console_group)
        
        # Console output
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setFont(QFont("Courier", 9))
        self.console_output.setMaximumHeight(300)
        console_layout.addWidget(self.console_output)
        
        # Console controls
        console_controls = QHBoxLayout()
        
        clear_console_btn = QPushButton("Clear Console")
        clear_console_btn.clicked.connect(self._clear_console)
        console_controls.addWidget(clear_console_btn)
        
        console_controls.addStretch()
        
        # Auto-scroll checkbox
        from PyQt6.QtWidgets import QCheckBox
        self.auto_scroll_check = QCheckBox("Auto-scroll")
        self.auto_scroll_check.setChecked(True)
        console_controls.addWidget(self.auto_scroll_check)
        
        console_layout.addLayout(console_controls)
        layout.addWidget(console_group)
        
        parent.addWidget(console_widget)
    
    def _create_connection_tab(self):
        """Create Arduino connection tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Connection group
        conn_group = QGroupBox("Arduino Connection")
        conn_layout = QHBoxLayout(conn_group)
        
        # Port selection
        conn_layout.addWidget(QLabel("Port:"))
        self.port_combo = NoWheelComboBox()
        self.port_combo.setMinimumWidth(100)
        conn_layout.addWidget(self.port_combo)
        
        # Refresh ports button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_ports)
        conn_layout.addWidget(refresh_btn)
        
        # Baudrate selection  
        conn_layout.addWidget(QLabel("Baudrate:"))
        self.baudrate_combo = NoWheelComboBox()
        for rate in SerialConfig.BAUDRATES:
            self.baudrate_combo.addItem(str(rate))
        self.baudrate_combo.setCurrentText(str(AppConfig.DEFAULT_BAUDRATE))
        conn_layout.addWidget(self.baudrate_combo)
        
        # Connect/Disconnect button
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._toggle_connection)
        conn_layout.addWidget(self.connect_btn)
        
        conn_layout.addStretch()
        layout.addWidget(conn_group)
        
        # Status group
        status_group = QGroupBox("Machine Status")
        status_layout = QVBoxLayout(status_group)
        
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        status_layout.addWidget(self.status_label)
        
        self.needle_position_label = QLabel("Current Position: Unknown")
        status_layout.addWidget(self.needle_position_label)
        
        layout.addWidget(status_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Connection")
        
        # Initialize ports
        self._refresh_ports()
    
    def _create_pattern_builder_tab(self):
        """Create comprehensive pattern builder tab"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        
        # Make scrollable
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        
        # Pattern Information Section
        info_group = QGroupBox("Pattern Information")
        info_layout = QGridLayout(info_group)
        
        info_layout.addWidget(QLabel("Pattern Name:"), 0, 0)
        self.pattern_name_edit = QLineEdit(self.current_pattern.name)
        self.pattern_name_edit.textChanged.connect(self._on_pattern_name_changed)
        info_layout.addWidget(self.pattern_name_edit, 0, 1)
        
        info_layout.addWidget(QLabel("Description:"), 1, 0)
        self.pattern_description = QTextEdit()
        self.pattern_description.setMaximumHeight(60)
        self.pattern_description.setPlainText(self.current_pattern.description)
        self.pattern_description.textChanged.connect(self._on_pattern_description_changed)
        info_layout.addWidget(self.pattern_description, 1, 1)
        
        info_layout.addWidget(QLabel("Repetitions:"), 2, 0)
        self.repetitions_spin = NoWheelSpinBox()
        self.repetitions_spin.setMinimum(1)
        self.repetitions_spin.setMaximum(1000)
        self.repetitions_spin.setValue(self.current_pattern.repetitions)
        self.repetitions_spin.valueChanged.connect(self._on_pattern_repetitions_changed)
        info_layout.addWidget(self.repetitions_spin, 2, 1)
        
        layout.addWidget(info_group)
        
        # Step Builder Section
        step_group = QGroupBox("Add Pattern Step")
        step_layout = QGridLayout(step_group)
        
        step_layout.addWidget(QLabel("Needles:"), 0, 0)
        self.needles_spin = NoWheelSpinBox()
        self.needles_spin.setMinimum(1)
        self.needles_spin.setMaximum(10000)
        self.needles_spin.setValue(48)
        step_layout.addWidget(self.needles_spin, 0, 1)
        
        step_layout.addWidget(QLabel("Direction:"), 0, 2)
        self.direction_combo = NoWheelComboBox()
        self.direction_combo.addItems(["CW", "CCW"])
        step_layout.addWidget(self.direction_combo, 0, 3)
        
        step_layout.addWidget(QLabel("Rows:"), 1, 0)
        self.rows_spin = NoWheelSpinBox()
        self.rows_spin.setMinimum(1)
        self.rows_spin.setMaximum(1000)
        self.rows_spin.setValue(1)
        step_layout.addWidget(self.rows_spin, 1, 1)
        
        step_layout.addWidget(QLabel("Description:"), 1, 2)
        self.step_description_edit = QLineEdit()
        self.step_description_edit.setPlaceholderText("Optional description...")
        step_layout.addWidget(self.step_description_edit, 1, 3)
        
        add_step_btn = QPushButton("Add Step to Pattern")
        add_step_btn.clicked.connect(self._add_pattern_step)
        add_step_btn.setMinimumHeight(40)
        add_step_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #C8E6C9; }")
        step_layout.addWidget(add_step_btn, 2, 0, 1, 4)
        
        layout.addWidget(step_group)
        
        # Current Pattern Steps
        steps_group = QGroupBox("Current Pattern Steps")
        steps_layout = QVBoxLayout(steps_group)
        
        self.steps_list = QListWidget()
        self.steps_list.setMinimumHeight(150)
        steps_layout.addWidget(self.steps_list)
        
        # Step controls
        step_controls = QHBoxLayout()
        
        edit_step_btn = QPushButton("Edit Selected")
        edit_step_btn.clicked.connect(self._edit_selected_step)
        step_controls.addWidget(edit_step_btn)
        
        delete_step_btn = QPushButton("Delete Selected")
        delete_step_btn.clicked.connect(self._remove_pattern_step)
        step_controls.addWidget(delete_step_btn)
        
        move_up_btn = QPushButton("Move Up")
        move_up_btn.clicked.connect(self._move_step_up)
        step_controls.addWidget(move_up_btn)
        
        move_down_btn = QPushButton("Move Down")
        move_down_btn.clicked.connect(self._move_step_down)
        step_controls.addWidget(move_down_btn)
        
        step_controls.addStretch()
        steps_layout.addLayout(step_controls)
        layout.addWidget(steps_group)
        
        # Pattern Visual Preview (Excel-like table)
        preview_group = QGroupBox("Pattern Visual Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        self.pattern_table = QTableWidget()
        self.pattern_table.setMinimumHeight(200)
        self.pattern_table.setMaximumHeight(400)
        self.pattern_table.setAlternatingRowColors(True)
        self.pattern_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        
        # Excel-like styling
        self.pattern_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #d0d0d0;
                background-color: white;
                alternate-background-color: #f5f5f5;
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
        
        preview_layout.addWidget(self.pattern_table)
        
        # Pattern info label
        self.pattern_info_label = QLabel()
        self.pattern_info_label.setStyleSheet("font-size: 12px; color: #666; padding: 5px;")
        self.pattern_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pattern_info_label.setWordWrap(True)
        preview_layout.addWidget(self.pattern_info_label)
        
        layout.addWidget(preview_group)
        
        # Pattern Management
        mgmt_group = QGroupBox("Pattern Management")
        mgmt_layout = QGridLayout(mgmt_group)
        
        save_btn = QPushButton("Save Pattern")
        save_btn.clicked.connect(self._save_current_pattern)
        save_btn.setMinimumHeight(40)
        save_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #BBDEFB; }")
        mgmt_layout.addWidget(save_btn, 0, 0)
        
        load_btn = QPushButton("Load Pattern")
        load_btn.clicked.connect(self._show_load_pattern_dialog)
        load_btn.setMinimumHeight(40)
        mgmt_layout.addWidget(load_btn, 0, 1)
        
        new_btn = QPushButton("New Pattern")
        new_btn.clicked.connect(self._new_pattern)
        new_btn.setMinimumHeight(40)
        mgmt_layout.addWidget(new_btn, 0, 2)
        
        execute_btn = QPushButton("Execute Pattern")
        execute_btn.clicked.connect(self._execute_current_pattern)
        execute_btn.setMinimumHeight(50)
        execute_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                font-weight: bold;
                font-size: 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #e0e0e0;
                color: #9e9e9e;
            }
        """)
        mgmt_layout.addWidget(execute_btn, 1, 0, 1, 2)
        
        stop_btn = QPushButton("STOP MACHINE")
        stop_btn.clicked.connect(self._emergency_stop)
        stop_btn.setMinimumHeight(50)
        stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-weight: bold;
                font-size: 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        mgmt_layout.addWidget(stop_btn, 1, 2)
        
        layout.addWidget(mgmt_group)
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(widget, "Pattern Builder")
        
        # Initialize display
        self._update_pattern_display()
        
        # Step controls
        step_controls = QHBoxLayout()
        remove_step_btn = QPushButton("Remove Selected")
        # Initialize display
        self._update_pattern_display()
    
    def _create_script_execution_tab(self):
        """Create script execution tab for loading and running script files"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Script file selection
        file_group = QGroupBox("Script File")
        file_layout = QVBoxLayout(file_group)
        
        file_select_layout = QHBoxLayout()
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setPlaceholderText("Select a script file...")
        file_select_layout.addWidget(self.file_path_edit)
        
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_script_file)
        file_select_layout.addWidget(browse_btn)
        
        file_layout.addLayout(file_select_layout)
        
        # Script info
        self.script_info_label = QLabel("No script loaded")
        self.script_info_label.setStyleSheet("font-size: 12px; color: #666;")
        file_layout.addWidget(self.script_info_label)
        
        layout.addWidget(file_group)
        
        # Script content preview
        content_group = QGroupBox("Script Content Preview")
        content_layout = QVBoxLayout(content_group)
        
        self.script_content = QTextEdit()
        self.script_content.setMaximumHeight(200)
        self.script_content.setReadOnly(True)
        self.script_content.setFont(QFont("Courier", 9))
        content_layout.addWidget(self.script_content)
        
        layout.addWidget(content_group)
        
        # Script execution
        exec_group = QGroupBox("Script Execution")
        exec_layout = QHBoxLayout(exec_group)
        
        self.upload_btn = QPushButton("Execute Script")
        self.upload_btn.setEnabled(False)
        self.upload_btn.clicked.connect(self._execute_script)
        self.upload_btn.setMinimumHeight(40)
        self.upload_btn.setStyleSheet("""
            QPushButton:enabled {
                background-color: #4caf50;
                color: white;
                font-weight: bold;
            }
        """)
        exec_layout.addWidget(self.upload_btn)
        
        exec_layout.addStretch()
        layout.addWidget(exec_group)
        
        layout.addStretch()
        
        self.tab_widget.addTab(widget, "Script Execution")
    
    def _create_manual_control_tab(self):
        """Create comprehensive manual control tab"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        
        # Make scrollable
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        
        # Current Position & Home Control
        position_group = QGroupBox("Current Position & Home")
        position_layout = QGridLayout(position_group)
        
        # Current needle position display
        position_layout.addWidget(QLabel("Current Needle Position:"), 0, 0)
        self.current_needle_display = QLabel("0")
        self.current_needle_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_needle_display.setStyleSheet("""
            QLabel {
                font-size: 36px;
                font-weight: bold;
                color: #FF6B9D;
                padding: 15px;
                background-color: #F9F9F9;
                border: 2px solid #DDD;
                border-radius: 8px;
            }
        """)
        position_layout.addWidget(self.current_needle_display, 0, 1)
        
        # Home button
        home_btn = QPushButton("🏠 Return to Home (Needle 0)")
        home_btn.clicked.connect(self._home_machine)
        home_btn.setMinimumHeight(45)
        home_btn.setStyleSheet("""
            QPushButton {
                font-weight: bold;
                font-size: 14px;
                background-color: #4CAF50;
                color: white;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        position_layout.addWidget(home_btn, 1, 0, 1, 2)
        
        layout.addWidget(position_group)
        
        # Needle Control Mode
        needle_group = QGroupBox("Needle-Based Control")
        needle_layout = QGridLayout(needle_group)
        
        needle_layout.addWidget(QLabel("Target Needles:"), 0, 0)
        self.needle_target_spin = NoWheelSpinBox()
        self.needle_target_spin.setMinimum(1)
        self.needle_target_spin.setMaximum(10000)
        self.needle_target_spin.setValue(48)
        self.needle_target_spin.setMinimumHeight(35)
        needle_layout.addWidget(self.needle_target_spin, 0, 1)
        
        needle_layout.addWidget(QLabel("Direction:"), 0, 2)
        self.needle_direction_combo = NoWheelComboBox()
        self.needle_direction_combo.addItems(["CW", "CCW"])
        self.needle_direction_combo.setMinimumHeight(35)
        needle_layout.addWidget(self.needle_direction_combo, 0, 3)
        
        start_needle_btn = QPushButton("▶️ Turn to Target Needles")
        start_needle_btn.clicked.connect(self._start_needle_target_mode)
        start_needle_btn.setMinimumHeight(45)
        start_needle_btn.setStyleSheet("""
            QPushButton {
                font-weight: bold;
                font-size: 16px;
                background-color: #2196F3;
                color: white;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        needle_layout.addWidget(start_needle_btn, 1, 0, 1, 4)
        
        layout.addWidget(needle_group)
        
        # Needle Sensor Controls
        sensor_group = QGroupBox("Needle Sensor Controls")
        sensor_layout = QGridLayout(sensor_group)
        
        self.monitor_needle_btn = QPushButton("Start Needle Monitoring")
        self.monitor_needle_btn.clicked.connect(self._toggle_needle_monitoring)
        self.monitor_needle_btn.setMinimumHeight(35)
        sensor_layout.addWidget(self.monitor_needle_btn, 0, 0)
        
        reset_count_btn = QPushButton("Reset Needle Count")
        reset_count_btn.clicked.connect(self._reset_needle_position)
        reset_count_btn.setMinimumHeight(35)
        sensor_layout.addWidget(reset_count_btn, 0, 1)
        
        show_needle_window_btn = QPushButton("Show Needle Window")
        show_needle_window_btn.clicked.connect(self._show_needle_count_window)
        show_needle_window_btn.setMinimumHeight(35)
        sensor_layout.addWidget(show_needle_window_btn, 1, 0, 1, 2)
        
        # Sensor status
        self.sensor_status_label = QLabel("Monitoring: Stopped")
        self.sensor_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sensor_status_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #666;
                padding: 8px;
                background-color: #F0F0F0;
                border-radius: 4px;
            }
        """)
        sensor_layout.addWidget(self.sensor_status_label, 2, 0, 1, 2)
        
        layout.addWidget(sensor_group)
        
        # Emergency Stop
        emergency_group = QGroupBox("Emergency Control")
        emergency_layout = QVBoxLayout(emergency_group)
        
        stop_btn = QPushButton("🛑 EMERGENCY STOP")
        stop_btn.clicked.connect(self._emergency_stop)
        stop_btn.setMinimumHeight(50)
        stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-weight: bold;
                font-size: 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        emergency_layout.addWidget(stop_btn)
        
        layout.addWidget(emergency_group)
        
        # Manual Step Control (Advanced)
        manual_group = QGroupBox("Manual Step Control (Advanced)")
        manual_layout = QGridLayout(manual_group)
        
        manual_layout.addWidget(QLabel("Steps:"), 0, 0)
        self.manual_steps_spin = NoWheelSpinBox()
        self.manual_steps_spin.setRange(1, 50000)
        self.manual_steps_spin.setValue(1000)
        self.manual_steps_spin.setMinimumHeight(30)
        manual_layout.addWidget(self.manual_steps_spin, 0, 1)
        
        manual_layout.addWidget(QLabel("Direction:"), 1, 0)
        self.manual_direction_combo = NoWheelComboBox()
        self.manual_direction_combo.addItems(["CW", "CCW"])
        self.manual_direction_combo.setMinimumHeight(30)
        manual_layout.addWidget(self.manual_direction_combo, 1, 1)
        
        manual_turn_btn = QPushButton("Execute Manual Steps")
        manual_turn_btn.clicked.connect(self._manual_turn)
        manual_turn_btn.setMinimumHeight(35)
        manual_layout.addWidget(manual_turn_btn, 2, 0, 1, 2)
        
        layout.addWidget(manual_group)
        
        # Custom Command
        custom_group = QGroupBox("Custom Command")
        custom_layout = QHBoxLayout(custom_group)
        
        self.custom_command_edit = QLineEdit()
        self.custom_command_edit.setPlaceholderText("Enter custom Arduino command...")
        self.custom_command_edit.returnPressed.connect(self._send_custom_command)
        self.custom_command_edit.setMinimumHeight(35)
        custom_layout.addWidget(self.custom_command_edit)
        
        send_custom_btn = QPushButton("Send Command")
        send_custom_btn.clicked.connect(self._send_custom_command)
        send_custom_btn.setMinimumHeight(35)
        custom_layout.addWidget(send_custom_btn)
        
        layout.addWidget(custom_group)
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(widget, "Manual Control")
        
    def _create_settings_tab(self):
        """Create comprehensive settings tab"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        
        # Make scrollable
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        
        # Theme Selection
        theme_group = QGroupBox("Application Theme")
        theme_layout = QGridLayout(theme_group)
        
        theme_layout.addWidget(QLabel("Theme:"), 0, 0)
        self.theme_combo = NoWheelComboBox()
        self.theme_combo.addItems(["Pink/Rose", "Dark", "Light/Grey"])
        self.theme_combo.setCurrentText(self.config.get("theme", "Pink/Rose"))
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        theme_layout.addWidget(self.theme_combo, 0, 1)
        
        theme_info = QLabel("Choose the color theme for the application interface.")
        theme_info.setWordWrap(True)
        theme_info.setStyleSheet("color: #666; font-size: 12px;")
        theme_layout.addWidget(theme_info, 1, 0, 1, 2)
        
        layout.addWidget(theme_group)
        
        # Motor Speed Settings
        speed_group = QGroupBox("Motor Speed Settings")
        speed_layout = QGridLayout(speed_group)
        
        speed_layout.addWidget(QLabel("Step Delay (microseconds):"), 0, 0)
        self.speed_spin = NoWheelSpinBox()
        self.speed_spin.setRange(500, 3000)
        self.speed_spin.setValue(self.config.get("motor_speed", 1000))
        self.speed_spin.setSuffix(" μs")
        self.speed_spin.valueChanged.connect(self._on_speed_changed)
        speed_layout.addWidget(self.speed_spin, 0, 1)
        
        # Speed presets
        speed_layout.addWidget(QLabel("Speed Presets:"), 1, 0, 1, 2)
        
        presets_layout = QHBoxLayout()
        for name, speed in [("Fast", 800), ("Normal", 1000), ("Slow", 1500), ("Precise", 2000)]:
            btn = QPushButton(f"{name}\n({speed}μs)")
            btn.clicked.connect(lambda checked, s=speed: self._set_speed_preset(s))
            btn.setMaximumHeight(50)
            presets_layout.addWidget(btn)
        
        speed_layout.addLayout(presets_layout, 2, 0, 1, 2)
        
        apply_speed_btn = QPushButton("Apply Speed to Arduino")
        apply_speed_btn.clicked.connect(self._apply_speed_setting)
        apply_speed_btn.setMinimumHeight(35)
        speed_layout.addWidget(apply_speed_btn, 3, 0, 1, 2)
        
        layout.addWidget(speed_group)
        
        # Advanced Settings
        advanced_group = QGroupBox("Advanced Settings")
        advanced_layout = QGridLayout(advanced_group)
        
        advanced_layout.addWidget(QLabel("Steps per Needle:"), 0, 0)
        self.steps_per_needle_spin = NoWheelSpinBox()
        self.steps_per_needle_spin.setRange(1, 10000)
        self.steps_per_needle_spin.setValue(self.config.get("steps_per_needle", 1000))
        self.steps_per_needle_spin.valueChanged.connect(self._on_steps_per_needle_changed)
        advanced_layout.addWidget(self.steps_per_needle_spin, 0, 1)
        
        advanced_layout.addWidget(QLabel("Chunk Size (max steps):"), 1, 0)
        self.chunk_size_spin = NoWheelSpinBox()
        self.chunk_size_spin.setRange(5000, 32700)
        self.chunk_size_spin.setValue(self.config.get("chunk_size", 32000))
        self.chunk_size_spin.valueChanged.connect(self._on_chunk_size_changed)
        advanced_layout.addWidget(self.chunk_size_spin, 1, 1)
        
        advanced_layout.addWidget(QLabel("Total Needles on Machine:"), 2, 0)
        self.total_needles_spin = NoWheelSpinBox()
        self.total_needles_spin.setRange(20, 200)
        self.total_needles_spin.setValue(self.config.get("total_needles", 48))
        self.total_needles_spin.valueChanged.connect(self._on_total_needles_changed)
        advanced_layout.addWidget(self.total_needles_spin, 2, 1)
        
        layout.addWidget(advanced_group)
        
        # Current Settings Display
        current_group = QGroupBox("Current Arduino Settings")
        current_layout = QVBoxLayout(current_group)
        
        self.current_settings_label = QLabel("Connect to Arduino to view current settings")
        self.current_settings_label.setWordWrap(True)
        self.current_settings_label.setStyleSheet("""
            QLabel {
                padding: 10px;
                background-color: #f9f9f9;
                border-radius: 4px;
            }
        """)
        self.current_settings_label.setMinimumHeight(80)
        current_layout.addWidget(self.current_settings_label)
        
        refresh_settings_btn = QPushButton("Refresh Current Settings")
        refresh_settings_btn.clicked.connect(self._refresh_current_settings)
        refresh_settings_btn.setMinimumHeight(35)
        current_layout.addWidget(refresh_settings_btn)
        
        layout.addWidget(current_group)
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(widget, "Settings")
        
    def _setup_timers(self):
        """Setup periodic update timers"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)  # Update every second
        
        # Needle monitoring timer
        self.needle_timer = QTimer()
        self.needle_timer.timeout.connect(self._update_needle_reading)
        
        # Response checker timer
        self.response_checker = QTimer()
        self.response_checker.timeout.connect(self._check_for_responses)
        self.response_checker.start(30)  # Check every 30ms for responses
    
    def _load_settings_ui(self):
        """Load saved settings into UI elements"""
        # This method loads saved config values into UI controls
        # Will be called after UI setup
        pass
    
    def _apply_theme(self):
        """Apply current theme to application"""
        if self.current_theme == "Pink/Rose":
            self._apply_pink_theme()
        elif self.current_theme == "Dark":
            self._apply_dark_theme()
        elif self.current_theme == "Light/Grey":
            self._apply_light_theme()
    
    # Console logging methods
    def _log_message(self, message: str):
        """Log message to console"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.console_output.append(formatted_message)
        
        # Auto-scroll to bottom if enabled
        if self.auto_scroll_check.isChecked():
            scrollbar = self.console_output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        
        # Log to file as well
        self.logger.info(message)
    
    def _clear_console(self):
        """Clear console output"""
        self.console_output.clear()
        self._log_message("Console cleared")
    
    # Arduino communication event handlers
    def _on_arduino_response(self, response: str):
        """Handle Arduino response"""
        self._log_message(f"Arduino: {response}")
        
        # Handle specific responses
        if "NEEDLE_COUNT:" in response:
            try:
                count = int(response.split(":")[1])
                self.current_needle_position = count % self.total_needles_on_machine
                self.current_needle_display.setText(str(self.current_needle_position))
                self.position_label.setText(f"Position: Needle {self.current_needle_position}")
            except (ValueError, IndexError):
                pass
        elif "DONE" in response:
            self._log_message("✓ Operation completed")
        elif "ERROR:" in response:
            self._log_message(f"❌ Arduino Error: {response}")
    
    def _on_arduino_error(self, error: str):
        """Handle Arduino error"""
        self._log_message(f"❌ Communication Error: {error}")
        QMessageBox.critical(self, "Communication Error", error)
    
    def _on_arduino_progress(self, current: int, total: int):
        """Handle Arduino progress update"""
        if self.progress_dialog:
            percentage = int((current / total) * 100) if total > 0 else 0
            self.progress_dialog.update_progress(current, total, f"Processing command {current} of {total}")
    
    def _on_arduino_operation_complete(self):
        """Handle Arduino operation completion"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        self._log_message("✓ Script execution completed")
    
    # Connection methods
    @pyqtSlot()
    def _refresh_ports(self):
        """Refresh available COM ports"""
        self.port_combo.clear()
        try:
            ports = serial.tools.list_ports.comports()
            if ports:
                for port in ports:
                    self.port_combo.addItem(f"{port.device} - {port.description}")
            else:
                self.port_combo.addItem("No ports found")
        except Exception as e:
            self._log_message(f"Error refreshing ports: {e}")
    
    @pyqtSlot()
    def _toggle_connection(self):
        """Toggle Arduino connection"""
        if self.connect_btn.text() == "Connect":
            port_text = self.port_combo.currentText()
            if not port_text or port_text == "No ports found":
                QMessageBox.warning(self, "Connection Error", "Please select a valid port")
                return
            
            port = port_text.split(" - ")[0]
            baudrate = int(self.baudrate_combo.currentText())
            
            if self.serial_manager.connect(port, baudrate):
                self.connect_btn.setText("Disconnect")
                self.status_label.setText("Connected")
                self.status_label.setStyleSheet("QLabel { color: #4CAF50; font-weight: bold; font-size: 14px; }")
                self.config["arduino_port"] = port
                self.config["baudrate"] = baudrate
                self._save_config()
                self._log_message(f"Connected to {port} at {baudrate} baud")
                self.statusBar().showMessage(f"Connected to {port}")
            else:
                QMessageBox.critical(self, "Connection Error", "Failed to connect to Arduino")
        else:
            self.serial_manager.disconnect()
            self.connect_btn.setText("Connect")
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("QLabel { color: #D32F2F; font-weight: bold; font-size: 14px; }")
            self._log_message("Disconnected from Arduino")
            self.statusBar().showMessage("Disconnected")
        else:
            self.controller.disconnect_machine()
    
    # Include all methods from the MainWindowMethods mixin
    from .main_window_methods import MainWindowMethods
    
    # Add all methods from MainWindowMethods to this class
    for method_name in dir(MainWindowMethods):
        if not method_name.startswith('__'):
            method = getattr(MainWindowMethods, method_name)
            if callable(method):
                locals()[method_name] = method

def main():
    """Main application entry point"""
    # Setup logging
    setup_logging("INFO", AppConfig.LOGS_DIR / "knitting_machine.log")
    logger = get_logger(__name__)
    
    try:
        # Create application
        app = QApplication(sys.argv)
        app.setApplicationName(AppConfig.APP_NAME)
        app.setApplicationVersion(AppConfig.APP_VERSION)
        app.setStyle('Fusion')
        
        # Create main window
        window = MainWindow()
        window.show()
        
        logger.info(f"Started {AppConfig.APP_NAME} v{AppConfig.APP_VERSION}")
        
        # Run application
        sys.exit(app.exec())
        
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
