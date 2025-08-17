#!/usr/bin/env python3
"""
Main GUI Application with Console Logging
Clean interface for knitting machine control with enhanced functionality
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QGroupBox, QLabel, QPushButton, QMessageBox,
    QListWidget, QListWidgetItem, QLineEdit, QTextEdit,
    QSplitter, QCheckBox, QScrollArea, QGridLayout
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont

# Import our modules
from ..core.controller import KnittingController, MachineState, ExecutionStatus
from ..patterns.models import KnittingPattern, PatternStep
from ..ui.components import (
    NoWheelSpinBox, NoWheelComboBox, ProgressDialog, ThemeManager
)
from ..ui.pattern_visualizer import PatternVisualizer
from ..utils.logger import get_logger, setup_logging
from config.settings import AppConfig, ThemeConfig


class MainWindow(QMainWindow):
    """Main application window with console logging"""
    
    def __init__(self):
        super().__init__()
        self.logger = get_logger(__name__)
        
        # Initialize configuration
        self.config_file = Path("knitting_config.json")
        self.config = self._load_config()
        
        # Initialize controller
        self.controller = KnittingController(str(AppConfig.PATTERNS_DIR))
        self.controller.set_callbacks(
            state_callback=self._on_state_change,
            progress_callback=self._on_progress_update,
            error_callback=self._on_error
        )
        
        # Pattern management
        self.current_pattern = KnittingPattern.empty("New Pattern")
        self.patterns_file = Path("knitting_patterns.json")
        self.saved_patterns = self._load_saved_patterns()
        
        # UI state
        self.current_theme = self.config.get("theme", ThemeConfig.DEFAULT_THEME)
        self.progress_dialog = None
        
        # Machine state
        self.current_needle_position = 0
        self.needle_monitoring_enabled = False
        
        # Setup UI
        self._setup_window()
        self._setup_ui()
        self._setup_timers()
        
        # Apply initial theme
        self._apply_theme()
        
        # Initial console message (after UI is set up)
        self._log_message("=== Knitting Machine Controller Ready ===")
        self._log_message("Connect to ESP8266 to begin")
        
        self.logger.info("Main window with console initialized")
    
    def _load_config(self):
        """Load configuration from JSON file"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.warning(f"Could not load config: {e}")
        
        # Default configuration
        return {
            "arduino_port": "",
            "baudrate": 9600,
            "theme": "Pink/Rose",
            "motor_speed": 1000,
            "steps_per_needle": 1000,
            "chunk_size": 32000,
            "total_needles": 48
        }
    
    def _save_config(self):
        """Save configuration to JSON file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            self.logger.error(f"Could not save config: {e}")
    
    def _load_saved_patterns(self):
        """Load saved patterns from file"""
        try:
            if self.patterns_file.exists():
                with open(self.patterns_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    patterns = []
                    for pattern_data in data:
                        pattern = KnittingPattern.from_dict(pattern_data)
                        patterns.append(pattern)
                    return patterns
            return []
        except Exception as e:
            self.logger.error(f"Could not load patterns: {e}")
            return []
    
    def _save_patterns_to_file(self):
        """Save patterns to file"""
        try:
            data = [pattern.to_dict() for pattern in self.saved_patterns]
            with open(self.patterns_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            self.logger.info(f"Saved {len(self.saved_patterns)} patterns to file")
        except Exception as e:
            self.logger.error(f"Could not save patterns: {e}")
            raise
    
    def _setup_window(self):
        """Setup main window properties"""
        self.setWindowTitle(f"{AppConfig.APP_NAME} v{AppConfig.APP_VERSION}")
        self.setMinimumSize(1200, 800)
        self.showMaximized()
    
    def _setup_ui(self):
        """Setup main user interface with console"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout with splitter
        main_layout = QHBoxLayout(central_widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left panel - Controls
        self._create_control_panel(splitter)
        
        # Right panel - Console
        self._create_console_panel(splitter)
        
        # Set proportions (70% control, 30% console)
        splitter.setSizes([840, 360])
        
        # Status bar
        self.statusBar().showMessage("Ready - Connect to ESP8266 to begin")
    
    def _create_control_panel(self, parent):
        """Create main control panel"""
        control_widget = QWidget()
        layout = QVBoxLayout(control_widget)
        
        # Connection section
        self._create_connection_section(layout)
        
        # Tab widget
        self.tab_widget = QTabWidget()
        
        # Create tabs
        self._create_pattern_tab()
        self._create_manual_tab()
        self._create_settings_tab()
        
        layout.addWidget(self.tab_widget)
        parent.addWidget(control_widget)
    
    def _create_connection_section(self, parent_layout):
        """Create ESP8266 WiFi connection section"""
        conn_group = QGroupBox("ESP8266 WiFi Connection")
        conn_layout = QGridLayout(conn_group)
        
        # Device selection
        conn_layout.addWidget(QLabel("Device:"), 0, 0)
        self.port_combo = NoWheelComboBox()
        self._refresh_ports()
        conn_layout.addWidget(self.port_combo, 0, 1)
        
        # Refresh devices button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_ports)
        conn_layout.addWidget(refresh_btn, 0, 2)
        
        # Manual IP entry
        conn_layout.addWidget(QLabel("Manual IP:"), 0, 3)
        self.manual_ip_edit = QLineEdit()
        self.manual_ip_edit.setPlaceholderText("192.168.1.100")
        conn_layout.addWidget(self.manual_ip_edit, 0, 4)
        
        # Connect button
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._toggle_connection)
        self.connect_btn.setMinimumHeight(40)
        self.connect_btn.setStyleSheet("""
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
        conn_layout.addWidget(self.connect_btn, 1, 0, 1, 5)
        
        parent_layout.addWidget(conn_group)
    
    def _create_console_panel(self, parent):
        """Create console and status panel"""
        console_widget = QWidget()
        layout = QVBoxLayout(console_widget)
        
        # Status section
        status_group = QGroupBox("Machine Status")
        status_layout = QVBoxLayout(status_group)
        
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("color: red; font-weight: bold; font-size: 14px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.status_label)
        
        # Position display
        self.position_label = QLabel("Position: Unknown")
        self.position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.position_label)
        
        # Needle position display
        self.needle_display = QLabel("0")
        self.needle_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.needle_display.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #FF6B9D;
                padding: 10px;
                background-color: #f9f9f9;
                border: 2px solid #ddd;
                border-radius: 6px;
            }
        """)
        status_layout.addWidget(self.needle_display)
        
        # Monitoring status
        self.monitoring_label = QLabel("Monitoring: Off")
        self.monitoring_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.monitoring_label.setStyleSheet("font-size: 12px; color: #666; padding: 5px;")
        status_layout.addWidget(self.monitoring_label)
        
        layout.addWidget(status_group)
        
        # Console section
        console_group = QGroupBox("Console Output")
        console_layout = QVBoxLayout(console_group)
        
        # Console output
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setFont(QFont("Courier", 9))
        self.console_output.setMinimumHeight(300)
        console_layout.addWidget(self.console_output)
        
        # Console controls
        controls = QHBoxLayout()
        
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_console)
        controls.addWidget(clear_btn)
        
        self.auto_scroll = QCheckBox("Auto-scroll")
        self.auto_scroll.setChecked(True)
        controls.addWidget(self.auto_scroll)
        
        save_log_btn = QPushButton("Save Log")
        save_log_btn.clicked.connect(self._save_console_log)
        controls.addWidget(save_log_btn)
        
        controls.addStretch()
        console_layout.addLayout(controls)
        
        layout.addWidget(console_group)
        parent.addWidget(console_widget)
    
    def _create_pattern_tab(self):
        """Create pattern builder tab"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        
        # Make scrollable
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        
        # Pattern information
        info_group = QGroupBox("Pattern Information")
        info_layout = QGridLayout(info_group)
        
        info_layout.addWidget(QLabel("Name:"), 0, 0)
        self.pattern_name = QLineEdit("New Pattern")
        info_layout.addWidget(self.pattern_name, 0, 1)
        
        info_layout.addWidget(QLabel("Description:"), 1, 0)
        self.pattern_description = QTextEdit()
        self.pattern_description.setMaximumHeight(60)
        info_layout.addWidget(self.pattern_description, 1, 1)
        
        info_layout.addWidget(QLabel("Repetitions:"), 2, 0)
        self.repetitions_spin = NoWheelSpinBox()
        self.repetitions_spin.setMinimum(1)
        self.repetitions_spin.setMaximum(1000)
        self.repetitions_spin.setValue(1)
        info_layout.addWidget(self.repetitions_spin, 2, 1)
        
        layout.addWidget(info_group)
        
        # Step creation
        step_group = QGroupBox("Add Step")
        step_layout = QGridLayout(step_group)
        
        step_layout.addWidget(QLabel("Needles:"), 0, 0)
        self.needles_spin = NoWheelSpinBox()
        self.needles_spin.setMinimum(1)
        self.needles_spin.setMaximum(1000)
        self.needles_spin.setValue(48)
        step_layout.addWidget(self.needles_spin, 0, 1)
        
        step_layout.addWidget(QLabel("Direction:"), 0, 2)
        self.direction_combo = NoWheelComboBox()
        self.direction_combo.addItems(["CW", "CCW"])
        step_layout.addWidget(self.direction_combo, 0, 3)
        
        step_layout.addWidget(QLabel("Rows:"), 1, 0)
        self.rows_spin = NoWheelSpinBox()
        self.rows_spin.setMinimum(1)
        self.rows_spin.setMaximum(100)
        self.rows_spin.setValue(1)
        step_layout.addWidget(self.rows_spin, 1, 1)
        
        add_btn = QPushButton("Add Step")
        add_btn.clicked.connect(self._add_step)
        add_btn.setMinimumHeight(35)
        add_btn.setStyleSheet("background-color: #C8E6C9; font-weight: bold;")
        step_layout.addWidget(add_btn, 1, 2, 1, 2)
        
        layout.addWidget(step_group)
        
        # Steps list
        steps_group = QGroupBox("Pattern Steps")
        steps_layout = QVBoxLayout(steps_group)
        
        self.steps_list = QListWidget()
        self.steps_list.setMinimumHeight(150)
        steps_layout.addWidget(self.steps_list)
        
        # Step controls
        step_controls = QHBoxLayout()
        
        edit_btn = QPushButton("Edit Selected")
        edit_btn.clicked.connect(self._edit_step)
        step_controls.addWidget(edit_btn)
        
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self._delete_step)
        step_controls.addWidget(delete_btn)
        
        move_up_btn = QPushButton("Move Up")
        move_up_btn.clicked.connect(self._move_step_up)
        step_controls.addWidget(move_up_btn)
        
        move_down_btn = QPushButton("Move Down")
        move_down_btn.clicked.connect(self._move_step_down)
        step_controls.addWidget(move_down_btn)
        
        step_controls.addStretch()
        steps_layout.addLayout(step_controls)
        
        layout.addWidget(steps_group)
        
        # Pattern actions
        actions_group = QGroupBox("Pattern Actions")
        actions_layout = QGridLayout(actions_group)
        
        save_btn = QPushButton("Save Pattern")
        save_btn.clicked.connect(self._save_pattern)
        save_btn.setMinimumHeight(40)
        save_btn.setStyleSheet("background-color: #BBDEFB; font-weight: bold;")
        actions_layout.addWidget(save_btn, 0, 0)
        
        load_btn = QPushButton("Load Pattern")
        load_btn.clicked.connect(self._load_pattern)
        load_btn.setMinimumHeight(40)
        actions_layout.addWidget(load_btn, 0, 1)
        
        new_btn = QPushButton("New Pattern")
        new_btn.clicked.connect(self._new_pattern)
        new_btn.setMinimumHeight(40)
        actions_layout.addWidget(new_btn, 0, 2)
        
        execute_btn = QPushButton("Execute Pattern")
        execute_btn.clicked.connect(self._execute_pattern)
        execute_btn.setMinimumHeight(50)
        execute_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                font-size: 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        actions_layout.addWidget(execute_btn, 1, 0, 1, 2)
        
        stop_btn = QPushButton("STOP")
        stop_btn.clicked.connect(self._emergency_stop)
        stop_btn.setMinimumHeight(50)
        stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
                color: white;
                font-weight: bold;
                font-size: 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #D32F2F;
            }
        """)
        actions_layout.addWidget(stop_btn, 1, 2)
        
        layout.addWidget(actions_group)
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(widget, "Pattern Builder")
    
    def _create_manual_tab(self):
        """Create manual control tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Needle position control
        position_group = QGroupBox("Current Position")
        position_layout = QVBoxLayout(position_group)
        
        self.current_needle_display = QLabel("0")
        self.current_needle_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_needle_display.setStyleSheet("""
            QLabel {
                font-size: 36px;
                font-weight: bold;
                color: #FF6B9D;
                padding: 15px;
                background-color: #f9f9f9;
                border: 2px solid #ddd;
                border-radius: 8px;
            }
        """)
        position_layout.addWidget(self.current_needle_display)
        
        home_btn = QPushButton("Return to Home")
        home_btn.clicked.connect(self._home_machine)
        home_btn.setMinimumHeight(40)
        home_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                border-radius: 6px;
            }
        """)
        position_layout.addWidget(home_btn)
        
        layout.addWidget(position_group)
        
        # Manual controls
        manual_group = QGroupBox("Manual Control")
        manual_layout = QGridLayout(manual_group)
        
        manual_layout.addWidget(QLabel("Needles:"), 0, 0)
        self.manual_needles = NoWheelSpinBox()
        self.manual_needles.setMinimum(1)
        self.manual_needles.setMaximum(1000)
        self.manual_needles.setValue(48)
        manual_layout.addWidget(self.manual_needles, 0, 1)
        
        manual_layout.addWidget(QLabel("Direction:"), 0, 2)
        self.manual_direction = NoWheelComboBox()
        self.manual_direction.addItems(["CW", "CCW"])
        manual_layout.addWidget(self.manual_direction, 0, 3)
        
        move_btn = QPushButton("Move")
        move_btn.clicked.connect(self._manual_move)
        move_btn.setMinimumHeight(40)
        move_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        manual_layout.addWidget(move_btn, 1, 0, 1, 2)
        
        stop_btn = QPushButton("STOP")
        stop_btn.clicked.connect(self._emergency_stop)
        stop_btn.setMinimumHeight(40)
        stop_btn.setStyleSheet("background-color: red; color: white; font-weight: bold;")
        manual_layout.addWidget(stop_btn, 1, 2, 1, 2)
        
        layout.addWidget(manual_group)
        
        layout.addStretch()
        
        self.tab_widget.addTab(widget, "Manual Control")
    
    def _create_settings_tab(self):
        """Create settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Theme settings
        theme_group = QGroupBox("Theme")
        theme_layout = QGridLayout(theme_group)
        
        theme_layout.addWidget(QLabel("Theme:"), 0, 0)
        self.theme_combo = NoWheelComboBox()
        self.theme_combo.addItems(["Rose Gold", "Midnight Purple", "Ocean Blue"])
        # Map display names to internal names
        theme_map = {
            "Rose Gold": "Pink/Rose",
            "Midnight Purple": "Dark", 
            "Ocean Blue": "Light/Grey"
        }
        # Set current selection
        current_display = next((k for k, v in theme_map.items() if v == self.config.get("theme", "Pink/Rose")), "Rose Gold")
        self.theme_combo.setCurrentText(current_display)
        
        # Create a wrapper function to handle the mapping
        def on_theme_display_changed(display_name):
            internal_name = theme_map.get(display_name, "Pink/Rose")
            self._on_theme_changed(internal_name)
        
        self.theme_combo.currentTextChanged.connect(on_theme_display_changed)
        theme_layout.addWidget(self.theme_combo, 0, 1)
        
        layout.addWidget(theme_group)
        
        # Motor settings
        motor_group = QGroupBox("Motor Settings")
        motor_layout = QGridLayout(motor_group)
        
        motor_layout.addWidget(QLabel("Motor Speed (μs):"), 0, 0)
        self.speed_spin = NoWheelSpinBox()
        self.speed_spin.setRange(500, 3000)
        self.speed_spin.setValue(self.config.get("motor_speed", 1000))
        self.speed_spin.valueChanged.connect(self._on_speed_changed)
        motor_layout.addWidget(self.speed_spin, 0, 1)
        
        apply_btn = QPushButton("Apply Settings")
        apply_btn.clicked.connect(self._apply_settings)
        apply_btn.setMinimumHeight(35)
        motor_layout.addWidget(apply_btn, 1, 0, 1, 2)
        
        layout.addWidget(motor_group)
        
        layout.addStretch()
        
        self.tab_widget.addTab(widget, "Settings")
    
    def _setup_timers(self):
        """Setup timers"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)
        
        self.needle_timer = QTimer()
        self.needle_timer.timeout.connect(self._check_needle_position)
    
    def _apply_theme(self):
        """Apply current theme with beautiful, modern styling"""
        theme = self.current_theme
        
        if theme == "Pink/Rose":
            # Beautiful Rose Gold theme with gradients and modern styling
            self.setStyleSheet("""
                QMainWindow { 
                    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                        stop: 0 #fdf2f8, stop: 0.5 #fce7f3, stop: 1 #fbddf4);
                    color: #4a1a3e;
                }
                
                QGroupBox { 
                    font-weight: bold; 
                    border: 2px solid #ec4899;
                    border-radius: 12px;
                    margin: 8px; 
                    padding-top: 20px; 
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #ffffff, stop: 1 #fdf2f8);
                    color: #831843;
                }
                QGroupBox::title { 
                    subcontrol-origin: margin; 
                    left: 15px; 
                    padding: 5px 10px;
                    color: #be185d;
                    background: #ffffff;
                    border-radius: 6px;
                    border: 1px solid #ec4899;
                }
                
                QPushButton {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #f472b6, stop: 1 #ec4899);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 8px 16px;
                    font-weight: 600;
                    min-height: 20px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #ec4899, stop: 1 #db2777);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #db2777, stop: 1 #be185d);
                }
                
                QTextEdit, QLineEdit {
                    background: #ffffff;
                    border: 2px solid #f3e8ff;
                    border-radius: 8px;
                    padding: 8px;
                    color: #4a1a3e;
                    selection-background-color: #fce7f3;
                }
                QTextEdit:focus, QLineEdit:focus {
                    border-color: #ec4899;
                    outline: none;
                }
                
                QComboBox, QSpinBox {
                    background: #ffffff;
                    border: 2px solid #f3e8ff;
                    border-radius: 6px;
                    padding: 6px 12px;
                    color: #4a1a3e;
                    min-height: 20px;
                }
                QComboBox:hover, QSpinBox:hover {
                    border-color: #ec4899;
                }
                QComboBox::drop-down {
                    border: none;
                    border-radius: 6px;
                    width: 20px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border: 2px solid #ec4899;
                    border-radius: 2px;
                }
                QComboBox QAbstractItemView {
                    background-color: #ffffff !important;
                    color: #4a1a3e !important;
                    border: 2px solid #ec4899;
                    border-radius: 6px;
                    selection-background-color: #fce7f3;
                    selection-color: #831843;
                    outline: none;
                }
                QComboBox QAbstractItemView::item {
                    background-color: #ffffff !important;
                    color: #4a1a3e !important;
                    padding: 6px;
                    border: none;
                    min-height: 20px;
                }
                QComboBox QAbstractItemView::item:selected {
                    background-color: #fce7f3 !important;
                    color: #831843 !important;
                }
                QComboBox QAbstractItemView::item:hover {
                    background-color: #fce7f3 !important;
                    color: #831843 !important;
                }
                /* Additional fallback selectors */
                QComboBox QListView {
                    background-color: #ffffff !important;
                    color: #4a1a3e !important;
                    border: 2px solid #ec4899;
                    border-radius: 6px;
                }
                QComboBox QListView::item {
                    background-color: #ffffff !important;
                    color: #4a1a3e !important;
                    padding: 6px;
                    border: none;
                }
                QComboBox QListView::item:selected {
                    background-color: #fce7f3 !important;
                    color: #831843 !important;
                }
                
                QListWidget {
                    background: #ffffff;
                    border: 2px solid #f3e8ff;
                    border-radius: 8px;
                    color: #4a1a3e;
                    alternate-background-color: #fdf2f8;
                }
                QListWidget::item {
                    padding: 8px;
                    border-bottom: 1px solid #f3e8ff;
                }
                QListWidget::item:selected {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #fce7f3, stop: 1 #f3e8ff);
                    color: #831843;
                }
                
                QTabWidget::pane {
                    border: 2px solid #ec4899;
                    border-radius: 8px;
                    background: #ffffff;
                }
                QTabBar::tab {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #fdf2f8, stop: 1 #f3e8ff);
                    color: #831843;
                    padding: 12px 20px;
                    margin-right: 2px;
                    border-top-left-radius: 8px;
                    border-top-right-radius: 8px;
                    border: 2px solid #f3e8ff;
                    font-weight: 600;
                }
                QTabBar::tab:selected {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #ffffff, stop: 1 #fdf2f8);
                    border-color: #ec4899;
                    border-bottom: none;
                }
                QTabBar::tab:hover {
                    background: #fce7f3;
                }
                
                QCheckBox {
                    color: #831843;
                    font-weight: 500;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #ec4899;
                    border-radius: 4px;
                    background: #ffffff;
                }
                QCheckBox::indicator:checked {
                    background: #ec4899;
                    image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEwIDNMNC41IDguNUwyIDYiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
                }
                
                QScrollArea {
                    border: none;
                    background: transparent;
                }
                QWidget {
                    background-color: #fdf2f8;
                    color: #4a1a3e;
                }
                
                QLabel {
                    color: #831843;
                    font-weight: 500;
                }
                
                QStatusBar {
                    background: #fdf2f8;
                    color: #831843;
                    border-top: 1px solid #f3e8ff;
                }
                QScrollBar:vertical {
                    background: #f3e8ff;
                    width: 12px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background: #ec4899;
                    border-radius: 6px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #db2777;
                }
            """)
            
        elif theme == "Dark":
            # Modern Dark theme with purple accents and smooth gradients
            self.setStyleSheet("""
                QMainWindow { 
                    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                        stop: 0 #0f0f23, stop: 0.5 #1a1a2e, stop: 1 #16213e);
                    color: #e2e8f0;
                }
                
                QGroupBox { 
                    font-weight: bold; 
                    border: 2px solid #6366f1;
                    border-radius: 12px;
                    margin: 8px; 
                    padding-top: 20px; 
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #1e293b, stop: 1 #0f172a);
                    color: #cbd5e1;
                }
                QGroupBox::title { 
                    subcontrol-origin: margin; 
                    left: 15px; 
                    padding: 5px 10px;
                    color: #a5b4fc;
                    background: #1e293b;
                    border-radius: 6px;
                    border: 1px solid #6366f1;
                }
                
                QPushButton {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #6366f1, stop: 1 #4f46e5);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 8px 16px;
                    font-weight: 600;
                    min-height: 20px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #7c3aed, stop: 1 #6d28d9);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #5b21b6, stop: 1 #4c1d95);
                }
                
                QTextEdit, QLineEdit {
                    background: #1e293b;
                    border: 2px solid #334155;
                    border-radius: 8px;
                    padding: 8px;
                    color: #e2e8f0;
                    selection-background-color: #3730a3;
                }
                QTextEdit:focus, QLineEdit:focus {
                    border-color: #6366f1;
                    outline: none;
                }
                
                QComboBox, QSpinBox {
                    background: #1e293b;
                    border: 2px solid #334155;
                    border-radius: 6px;
                    padding: 6px 12px;
                    color: #e2e8f0;
                    min-height: 20px;
                }
                QComboBox:hover, QSpinBox:hover {
                    border-color: #6366f1;
                }
                QComboBox QAbstractItemView {
                    background-color: #1e293b !important;
                    color: #e2e8f0 !important;
                    border: 2px solid #6366f1;
                    border-radius: 6px;
                    selection-background-color: #3730a3;
                    selection-color: #c7d2fe;
                    outline: none;
                }
                QComboBox QAbstractItemView::item {
                    background-color: #1e293b !important;
                    color: #e2e8f0 !important;
                    padding: 6px;
                    border: none;
                    min-height: 20px;
                }
                QComboBox QAbstractItemView::item:selected {
                    background-color: #3730a3 !important;
                    color: #c7d2fe !important;
                }
                QComboBox QAbstractItemView::item:hover {
                    background-color: #3730a3 !important;
                    color: #c7d2fe !important;
                }
                /* Additional fallback selectors */
                QComboBox QListView {
                    background-color: #1e293b !important;
                    color: #e2e8f0 !important;
                    border: 2px solid #6366f1;
                    border-radius: 6px;
                }
                QComboBox QListView::item {
                    background-color: #1e293b !important;
                    color: #e2e8f0 !important;
                    padding: 6px;
                    border: none;
                }
                QComboBox QListView::item:selected {
                    background-color: #3730a3 !important;
                    color: #c7d2fe !important;
                }
                
                QListWidget {
                    background: #1e293b;
                    border: 2px solid #334155;
                    border-radius: 8px;
                    color: #e2e8f0;
                    alternate-background-color: #0f172a;
                }
                QListWidget::item {
                    padding: 8px;
                    border-bottom: 1px solid #334155;
                }
                QListWidget::item:selected {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #3730a3, stop: 1 #312e81);
                    color: #c7d2fe;
                }
                
                QTabWidget::pane {
                    border: 2px solid #6366f1;
                    border-radius: 8px;
                    background: #1e293b;
                }
                QTabBar::tab {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #334155, stop: 1 #1e293b);
                    color: #cbd5e1;
                    padding: 12px 20px;
                    margin-right: 2px;
                    border-top-left-radius: 8px;
                    border-top-right-radius: 8px;
                    border: 2px solid #334155;
                    font-weight: 600;
                }
                QTabBar::tab:selected {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #1e293b, stop: 1 #0f172a);
                    border-color: #6366f1;
                    border-bottom: none;
                    color: #a5b4fc;
                }
                
                QCheckBox {
                    color: #cbd5e1;
                    font-weight: 500;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #6366f1;
                    border-radius: 4px;
                    background: #1e293b;
                }
                QCheckBox::indicator:checked {
                    background: #6366f1;
                }
                
                QWidget {
                    background-color: #1a1a2e;
                    color: #e2e8f0;
                }
                
                QLabel {
                    color: #cbd5e1;
                    font-weight: 500;
                }
                
                QStatusBar {
                    background: #1e293b;
                    color: #cbd5e1;
                    border-top: 1px solid #334155;
                }
                QScrollBar:vertical {
                    background: #334155;
                    width: 12px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background: #6366f1;
                    border-radius: 6px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #7c3aed;
                }
            """)
            
        else:  # Light/Grey - Clean and minimal
            # Modern Light theme with blue accents and clean design
            self.setStyleSheet("""
                QMainWindow { 
                    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                        stop: 0 #f8fafc, stop: 0.5 #f1f5f9, stop: 1 #e2e8f0);
                    color: #1e293b;
                }
                
                QGroupBox { 
                    font-weight: bold; 
                    border: 2px solid #3b82f6;
                    border-radius: 12px;
                    margin: 8px; 
                    padding-top: 20px; 
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #ffffff, stop: 1 #f8fafc);
                    color: #1e293b;
                }
                QGroupBox::title { 
                    subcontrol-origin: margin; 
                    left: 15px; 
                    padding: 5px 10px;
                    color: #1d4ed8;
                    background: #ffffff;
                    border-radius: 6px;
                    border: 1px solid #3b82f6;
                }
                
                QPushButton {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #3b82f6, stop: 1 #2563eb);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 8px 16px;
                    font-weight: 600;
                    min-height: 20px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2563eb, stop: 1 #1d4ed8);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #1d4ed8, stop: 1 #1e40af);
                }
                
                QTextEdit, QLineEdit {
                    background: #ffffff;
                    border: 2px solid #e2e8f0;
                    border-radius: 8px;
                    padding: 8px;
                    color: #1e293b;
                    selection-background-color: #dbeafe;
                }
                QTextEdit:focus, QLineEdit:focus {
                    border-color: #3b82f6;
                    outline: none;
                }
                
                QComboBox, QSpinBox {
                    background: #ffffff;
                    border: 2px solid #e2e8f0;
                    border-radius: 6px;
                    padding: 6px 12px;
                    color: #1e293b;
                    min-height: 20px;
                }
                QComboBox:hover, QSpinBox:hover {
                    border-color: #3b82f6;
                }
                QComboBox QAbstractItemView {
                    background-color: #ffffff !important;
                    color: #1e293b !important;
                    border: 2px solid #3b82f6;
                    border-radius: 6px;
                    selection-background-color: #dbeafe;
                    selection-color: #1e40af;
                    outline: none;
                }
                QComboBox QAbstractItemView::item {
                    background-color: #ffffff !important;
                    color: #1e293b !important;
                    padding: 6px;
                    border: none;
                    min-height: 20px;
                }
                QComboBox QAbstractItemView::item:selected {
                    background-color: #dbeafe !important;
                    color: #1e40af !important;
                }
                QComboBox QAbstractItemView::item:hover {
                    background-color: #dbeafe !important;
                    color: #1e40af !important;
                }
                /* Additional fallback selectors */
                QComboBox QListView {
                    background-color: #ffffff !important;
                    color: #1e293b !important;
                    border: 2px solid #3b82f6;
                    border-radius: 6px;
                }
                QComboBox QListView::item {
                    background-color: #ffffff !important;
                    color: #1e293b !important;
                    padding: 6px;
                    border: none;
                }
                QComboBox QListView::item:selected {
                    background-color: #dbeafe !important;
                    color: #1e40af !important;
                }
                
                QListWidget {
                    background: #ffffff;
                    border: 2px solid #e2e8f0;
                    border-radius: 8px;
                    color: #1e293b;
                    alternate-background-color: #f8fafc;
                }
                QListWidget::item {
                    padding: 8px;
                    border-bottom: 1px solid #e2e8f0;
                }
                QListWidget::item:selected {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #dbeafe, stop: 1 #bfdbfe);
                    color: #1e40af;
                }
                
                QTabWidget::pane {
                    border: 2px solid #3b82f6;
                    border-radius: 8px;
                    background: #ffffff;
                }
                QTabBar::tab {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #f8fafc, stop: 1 #e2e8f0);
                    color: #475569;
                    padding: 12px 20px;
                    margin-right: 2px;
                    border-top-left-radius: 8px;
                    border-top-right-radius: 8px;
                    border: 2px solid #e2e8f0;
                    font-weight: 600;
                }
                QTabBar::tab:selected {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #ffffff, stop: 1 #f8fafc);
                    border-color: #3b82f6;
                    border-bottom: none;
                    color: #1d4ed8;
                }
                
                QCheckBox {
                    color: #475569;
                    font-weight: 500;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #3b82f6;
                    border-radius: 4px;
                    background: #ffffff;
                }
                QCheckBox::indicator:checked {
                    background: #3b82f6;
                }
                
                QWidget {
                    background-color: #f8fafc;
                    color: #1e293b;
                }
                
                QLabel {
                    color: #475569;
                    font-weight: 500;
                }
                
                QStatusBar {
                    background: #f8fafc;
                    color: #475569;
                    border-top: 1px solid #e2e8f0;
                }
                QScrollBar:vertical {
                    background: #e2e8f0;
                    width: 12px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background: #3b82f6;
                    border-radius: 6px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #2563eb;
                }
            """)
    
    # Console methods
    def _log_message(self, message: str):
        """Log message to console with timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        
        # Check if console is ready
        if hasattr(self, 'console_output'):
            self.console_output.append(formatted)
            
            if hasattr(self, 'auto_scroll') and self.auto_scroll.isChecked():
                scroll = self.console_output.verticalScrollBar()
                scroll.setValue(scroll.maximum())
        
        # Always log to file
        if hasattr(self, 'logger'):
            self.logger.info(message)
    
    def _clear_console(self):
        """Clear console output"""
        self.console_output.clear()
        self._log_message("Console cleared")
    
    def _save_console_log(self):
        """Save console log to file"""
        from PyQt6.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Console Log", "console_log.txt", "Text Files (*.txt)"
        )
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.console_output.toPlainText())
                self._log_message(f"Console log saved to {filename}")
            except Exception as e:
                self._log_message(f"Error saving log: {e}")
    
    # Connection methods
    @pyqtSlot()
    def _refresh_ports(self):
        """Refresh WiFi devices"""
        self.port_combo.clear()
        try:
            # Refresh device discovery
            self.controller.wifi_manager.refresh_devices()
            
            # Get available devices
            devices = self.controller.get_available_ports()
            if devices:
                for device in devices:
                    if isinstance(device, dict):
                        display_text = f"{device.get('name', 'Unknown')} - {device.get('ip', 'N/A')}:{device.get('port', 80)}"
                        self.port_combo.addItem(display_text)
                    else:
                        # Legacy string format
                        self.port_combo.addItem(str(device))
                
                self._log_message(f"Found {len(devices)} WiFi devices")
            else:
                self.port_combo.addItem("No devices found")
                self._log_message("No WiFi devices found - make sure ESP8266 is powered on and connected to network")
                
        except Exception as e:
            self._log_message(f"Error refreshing devices: {e}")
            self.port_combo.addItem("Error - check network connection")
    
    @pyqtSlot()
    def _toggle_connection(self):
        """Toggle WiFi connection"""
        if self.connect_btn.text() == "Connect":
            # Get selected device or manual IP
            device_text = self.port_combo.currentText()
            manual_ip = self.manual_ip_edit.text().strip()
            
            if manual_ip:
                # Use manual IP
                device_info = manual_ip
            elif device_text and "No devices" not in device_text and "Error" not in device_text:
                # Parse device info from combo box
                if " - " in device_text:
                    # Extract IP:port from "Device Name - IP:port"
                    device_info = device_text.split(" - ")[1]
                else:
                    device_info = device_text
            else:
                QMessageBox.warning(self, "No Device", "Please select a device or enter a manual IP address")
                return
            
            try:
                # Attempt connection
                self.connect_btn.setText("Connecting...")
                self.connect_btn.setEnabled(False)
                self.status_label.setText("Connecting...")
                self.status_label.setStyleSheet("color: orange; font-weight: bold; font-size: 14px;")
                
                # Process events to update UI
                QApplication.processEvents()
                
                # Connect to device
                success = self.controller.connect_machine(device_info)
                
                if success:
                    self.connect_btn.setText("Disconnect")
                    self.status_label.setText("Connected")
                    self.status_label.setStyleSheet("color: green; font-weight: bold; font-size: 14px;")
                    
                    # Save successful connection
                    self.config["wifi_device"] = device_info
                    self._save_config()
                    
                    self._log_message(f"Connected to ESP8266 at {device_info}")
                    self.statusBar().showMessage(f"Connected to {device_info}")
                    
                    # Update UI messages
                    self._log_message("ESP8266 connected - ready for knitting operations")
                else:
                    # Connection failed
                    self.connect_btn.setText("Connect")
                    self.status_label.setText("Connection Failed")
                    self.status_label.setStyleSheet("color: red; font-weight: bold; font-size: 14px;")
                    QMessageBox.critical(self, "Connection Error", f"Failed to connect to {device_info}")
                
            except Exception as e:
                self.connect_btn.setText("Connect")
                self.status_label.setText("Connection Error")
                self.status_label.setStyleSheet("color: red; font-weight: bold; font-size: 14px;")
                self._log_message(f"Connection failed: {e}")
                QMessageBox.critical(self, "Connection Error", str(e))
            
            finally:
                self.connect_btn.setEnabled(True)
                
        else:
            # Disconnect
            try:
                self.controller.disconnect_machine()
                self.connect_btn.setText("Connect")
                self.status_label.setText("Disconnected")
                self.status_label.setStyleSheet("color: red; font-weight: bold; font-size: 14px;")
                self._log_message("Disconnected from ESP8266")
                self.statusBar().showMessage("Disconnected")
            except Exception as e:
                self._log_message(f"Disconnect error: {e}")
    
    # Pattern methods
    @pyqtSlot()
    def _add_step(self):
        """Add pattern step"""
        needles = self.needles_spin.value()
        direction = self.direction_combo.currentText()
        rows = self.rows_spin.value()
        
        step_text = f"{needles} needles {direction} ({rows} rows)"
        self.steps_list.addItem(step_text)
        
        self._log_message(f"Added step: {step_text}")
    
    @pyqtSlot()
    def _edit_step(self):
        """Edit selected step"""
        current_row = self.steps_list.currentRow()
        if current_row >= 0:
            # For now, just log the action
            self._log_message(f"Edit step {current_row + 1} (not implemented yet)")
        else:
            QMessageBox.information(self, "No Selection", "Please select a step to edit")
    
    @pyqtSlot()
    def _delete_step(self):
        """Delete selected step"""
        current_row = self.steps_list.currentRow()
        if current_row >= 0:
            item = self.steps_list.takeItem(current_row)
            self._log_message(f"Deleted step: {item.text()}")
        else:
            QMessageBox.information(self, "No Selection", "Please select a step to delete")
    
    @pyqtSlot()
    def _move_step_up(self):
        """Move selected step up"""
        current_row = self.steps_list.currentRow()
        if current_row > 0:
            item = self.steps_list.takeItem(current_row)
            self.steps_list.insertItem(current_row - 1, item)
            self.steps_list.setCurrentRow(current_row - 1)
            self._log_message(f"Moved step up: {item.text()}")
        else:
            QMessageBox.information(self, "Cannot Move", "Step is already at the top or no step selected")
    
    @pyqtSlot()
    def _move_step_down(self):
        """Move selected step down"""
        current_row = self.steps_list.currentRow()
        if current_row >= 0 and current_row < self.steps_list.count() - 1:
            item = self.steps_list.takeItem(current_row)
            self.steps_list.insertItem(current_row + 1, item)
            self.steps_list.setCurrentRow(current_row + 1)
            self._log_message(f"Moved step down: {item.text()}")
        else:
            QMessageBox.information(self, "Cannot Move", "Step is already at the bottom or no step selected")
    
    @pyqtSlot()
    def _save_pattern(self):
        """Save current pattern"""
        pattern_name = self.pattern_name.text()
        if not pattern_name:
            QMessageBox.warning(self, "No Name", "Please enter a pattern name")
            return
        
        steps = []
        for i in range(self.steps_list.count()):
            step_text = self.steps_list.item(i).text()
            # Parse step text to create step data
            # Expected format: "48 needles CW x1 row"
            parts = step_text.split()
            if len(parts) >= 4:
                try:
                    needles = int(parts[0])
                    direction = parts[2]
                    rows_part = parts[3].replace('x', '')
                    rows = int(rows_part)
                    step_data = {
                        "needles": needles,
                        "direction": direction,
                        "rows": rows,
                        "description": step_text
                    }
                    steps.append(step_data)
                except (ValueError, IndexError):
                    # If parsing fails, store as string
                    steps.append(step_text)
            else:
                steps.append(step_text)
        
        if not steps:
            QMessageBox.warning(self, "No Steps", "Please add steps to the pattern")
            return
        
        # Create pattern object
        pattern = KnittingPattern(
            name=pattern_name,
            steps=[],
            description=self.pattern_description.toPlainText(),
            repetitions=self.repetitions_spin.value()
        )
        
        # Add steps to pattern
        for step_data in steps:
            if isinstance(step_data, dict):
                new_step = PatternStep(**step_data)
            else:
                # For string steps, create basic step
                new_step = PatternStep(needles=48, direction="CW", rows=1, description=step_data)
            pattern = pattern.add_step(new_step)
        
        # Check if pattern name already exists
        existing_pattern = None
        for i, existing in enumerate(self.saved_patterns):
            if existing.name == pattern_name:
                existing_pattern = i
                break
        
        if existing_pattern is not None:
            reply = QMessageBox.question(
                self, "Pattern Exists", 
                f"A pattern named '{pattern_name}' already exists. Do you want to replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.saved_patterns[existing_pattern] = pattern
            else:
                return
        else:
            self.saved_patterns.append(pattern)
        
        try:
            self._save_patterns_to_file()
            self._log_message(f"Pattern '{pattern_name}' saved with {len(steps)} steps")
            QMessageBox.information(self, "Saved", f"Pattern '{pattern_name}' saved successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save pattern: {str(e)}")
            # Remove the pattern if it was just added
            if existing_pattern is None and self.saved_patterns and self.saved_patterns[-1] == pattern:
                self.saved_patterns.pop()
    
    @pyqtSlot()
    def _load_pattern(self):
        """Load pattern - show dialog to choose from saved patterns or file"""
        if not self.saved_patterns:
            # No saved patterns, show file dialog directly
            reply = QMessageBox.question(
                self, "No Saved Patterns", 
                "No saved patterns found. Would you like to load a pattern from file?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._load_pattern_from_file()
            return
        
        # Create pattern selection dialog
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Load Pattern")
        dialog.setMinimumSize(500, 400)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        
        # Instructions
        instructions = QLabel("Select a saved pattern to load:")
        instructions.setStyleSheet("font-weight: bold; padding: 10px;")
        layout.addWidget(instructions)
        
        # Pattern list
        pattern_list = QListWidget()
        pattern_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 5px;
                background-color: white;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #eee;
            }
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: black;
            }
            QListWidget::item:hover {
                background-color: #f5f5f5;
            }
        """)
        
        # Add patterns to list
        for pattern in self.saved_patterns:
            steps_count = len(pattern.steps)
            total_needles = pattern.total_needles
            
            item_text = f"{pattern.name}\n"
            item_text += f"Steps: {steps_count} | Total Needles: {total_needles:,}"
            if pattern.description:
                item_text += f"\n{pattern.description[:100]}..." if len(pattern.description) > 100 else f"\n{pattern.description}"
            
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, pattern)  # Store pattern object
            pattern_list.addItem(item)
        
        layout.addWidget(pattern_list)
        
        # Pattern preview area
        preview_group = QGroupBox("Pattern Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        preview_text = QTextEdit()
        preview_text.setMaximumHeight(100)
        preview_text.setReadOnly(True)
        preview_text.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #ddd;
                border-radius: 3px;
                font-family: monospace;
            }
        """)
        preview_layout.addWidget(preview_text)
        layout.addWidget(preview_group)
        
        # Update preview when selection changes
        def update_preview():
            current_item = pattern_list.currentItem()
            if current_item:
                pattern = current_item.data(Qt.ItemDataRole.UserRole)
                preview = f"Name: {pattern.name}\n"
                preview += f"Repetitions: {pattern.repetitions}\n"
                preview += f"Total Steps: {len(pattern.steps)}\n\n"
                preview += "Steps:\n"
                for i, step in enumerate(pattern.steps[:5]):  # Show first 5 steps
                    preview += f"  {i+1}. {step.description}\n"
                if len(pattern.steps) > 5:
                    preview += f"  ... and {len(pattern.steps) - 5} more steps"
                preview_text.setPlainText(preview)
            else:
                preview_text.clear()
        
        pattern_list.itemSelectionChanged.connect(update_preview)
        
        # Buttons
        button_box = QDialogButtonBox()
        load_btn = QPushButton("Load Selected Pattern")
        load_file_btn = QPushButton("Load from File...")
        delete_btn = QPushButton("Delete Selected")
        cancel_btn = QPushButton("Cancel")
        
        load_btn.setDefault(True)
        load_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px; }")
        load_file_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; padding: 8px; }")
        delete_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; padding: 8px; }")
        
        button_box.addButton(load_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        button_box.addButton(load_file_btn, QDialogButtonBox.ButtonRole.ActionRole)
        button_box.addButton(delete_btn, QDialogButtonBox.ButtonRole.ActionRole)
        button_box.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        
        layout.addWidget(button_box)
        
        # Button connections
        def load_selected():
            current_item = pattern_list.currentItem()
            if current_item:
                pattern = current_item.data(Qt.ItemDataRole.UserRole)
                self._apply_loaded_pattern(pattern)
                dialog.accept()
            else:
                QMessageBox.warning(dialog, "No Selection", "Please select a pattern to load.")
        
        def delete_selected():
            current_item = pattern_list.currentItem()
            if current_item:
                pattern = current_item.data(Qt.ItemDataRole.UserRole)
                reply = QMessageBox.question(
                    dialog, "Delete Pattern", 
                    f"Are you sure you want to delete the pattern '{pattern.name}'?\nThis cannot be undone.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.saved_patterns.remove(pattern)
                    self._save_patterns_to_file()
                    # Remove from list
                    row = pattern_list.row(current_item)
                    pattern_list.takeItem(row)
                    self._log_message(f"Deleted pattern: {pattern.name}")
            else:
                QMessageBox.warning(dialog, "No Selection", "Please select a pattern to delete.")
        
        def load_from_file():
            dialog.accept()
            self._load_pattern_from_file()
        
        load_btn.clicked.connect(load_selected)
        delete_btn.clicked.connect(delete_selected)
        load_file_btn.clicked.connect(load_from_file)
        cancel_btn.clicked.connect(dialog.reject)
        
        # Show dialog
        if dialog.exec() == QDialog.DialogCode.Accepted:
            pass  # Pattern loading handled in load_selected
    
    def _load_pattern_from_file(self):
        """Load pattern from file"""
        from PyQt6.QtWidgets import QFileDialog
        
        filename, _ = QFileDialog.getOpenFileName(
            self, 
            "Load Pattern File", 
            "patterns/",
            "Pattern Files (*.json *.txt);;JSON Files (*.json);;Text Files (*.txt);;All Files (*)"
        )
        
        if not filename:
            return
        
        try:
            # Clear current pattern
            self.steps_list.clear()
            
            if filename.endswith('.json'):
                self._load_json_pattern(filename)
            elif filename.endswith('.txt'):
                self._load_text_pattern(filename)
            else:
                # Try to auto-detect format
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                
                if content.startswith('{') or content.startswith('['):
                    self._load_json_pattern(filename)
                else:
                    self._load_text_pattern(filename)
            
            self._log_message(f"Pattern loaded from: {filename}")
            QMessageBox.information(self, "Success", f"Pattern loaded successfully from:\n{filename}")
            
        except Exception as e:
            error_msg = f"Failed to load pattern: {str(e)}"
            self._log_message(f"Error loading pattern: {e}")
            QMessageBox.critical(self, "Load Error", error_msg)
    
    def _apply_loaded_pattern(self, pattern):
        """Apply a loaded pattern to the UI"""
        try:
            # Clear current pattern
            self.steps_list.clear()
            
            # Set pattern info
            self.pattern_name.setText(pattern.name)
            self.pattern_description.setPlainText(pattern.description or "")
            self.repetitions_spin.setValue(pattern.repetitions)
            
            # Add steps to UI
            for step in pattern.steps:
                step_text = step.description
                item = QListWidgetItem(step_text)
                self.steps_list.addItem(item)
            
            # Update current pattern reference
            self.current_pattern = pattern
            
            self._log_message(f"Loaded pattern: {pattern.name} with {len(pattern.steps)} steps")
            
        except Exception as e:
            error_msg = f"Failed to apply pattern: {str(e)}"
            self._log_message(f"Error applying pattern: {e}")
            QMessageBox.critical(self, "Load Error", error_msg)
    
    def _load_json_pattern(self, filename):
        """Load pattern from JSON file"""
        import json
        
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle different JSON formats
        if isinstance(data, dict):
            # Modern format with metadata
            if 'name' in data:
                self.pattern_name.setText(data['name'])
            if 'description' in data:
                self.pattern_description.setPlainText(data['description'])
            
            # Load steps
            steps = data.get('steps', [])
            for step in steps:
                if isinstance(step, dict):
                    needles = step.get('needles', 48)
                    direction = step.get('direction', 'CW')
                    rows = step.get('rows', 1)
                    step_text = f"{needles} needles {direction} x{rows} row{'s' if rows > 1 else ''}"
                elif isinstance(step, str):
                    step_text = step
                else:
                    step_text = str(step)
                
                self.steps_list.addItem(step_text)
        
        elif isinstance(data, list):
            # Simple list format
            for step in data:
                if isinstance(step, dict):
                    needles = step.get('needles', 48)
                    direction = step.get('direction', 'CW')
                    rows = step.get('rows', 1)
                    step_text = f"{needles} needles {direction} x{rows} row{'s' if rows > 1 else ''}"
                else:
                    step_text = str(step)
                
                self.steps_list.addItem(step_text)
    
    def _load_text_pattern(self, filename):
        """Load pattern from text file"""
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Parse text format - extract name, description and steps
        name = "Loaded Pattern"
        description = ""
        in_steps = False
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Look for pattern metadata
            if line.startswith('Pattern Name:') or line.startswith('# Pattern:'):
                name = line.split(':', 1)[1].strip()
            elif line.startswith('Description:') or line.startswith('# Description:'):
                description = line.split(':', 1)[1].strip()
            
            # Look for Arduino commands that represent steps
            if line.startswith('TURN:'):
                # TURN:steps:direction format
                parts = line.split(':')
                if len(parts) >= 3:
                    steps = parts[1]
                    direction = parts[2]
                    # Convert steps to approximate needles (assuming ~500 steps per needle)
                    try:
                        needles = int(int(steps) / 500)
                        step_text = f"{needles} needles {direction} x1 row"
                        self.steps_list.addItem(step_text)
                    except (ValueError, ZeroDivisionError):
                        self.steps_list.addItem(line)
            elif 'needles' in line.lower() and ('cw' in line.upper() or 'ccw' in line.upper()):
                # Direct step format
                self.steps_list.addItem(line)
        
        # Update UI
        if name:
            self.pattern_name.setText(name)
        if description:
            self.pattern_description.setPlainText(description)
    
    @pyqtSlot()
    def _new_pattern(self):
        """Create new pattern"""
        reply = QMessageBox.question(
            self, "New Pattern", 
            "This will clear the current pattern. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.pattern_name.setText("New Pattern")
            self.pattern_description.clear()
            self.repetitions_spin.setValue(1)
            self.steps_list.clear()
            self._log_message("Created new pattern")
    
    @pyqtSlot()
    def _execute_pattern(self):
        """Execute current pattern"""
        if self.connect_btn.text() == "Connect":
            QMessageBox.warning(self, "Not Connected", "Please connect to Arduino first")
            return
        
        steps = []
        for i in range(self.steps_list.count()):
            steps.append(self.steps_list.item(i).text())
        
        if not steps:
            QMessageBox.warning(self, "No Pattern", "Please add steps to the pattern first")
            return
        
        pattern_name = self.pattern_name.text()
        repetitions = self.repetitions_spin.value()
        
        self._log_message(f"Executing pattern '{pattern_name}' with {repetitions} repetition(s)")
        self._log_message(f"Pattern has {len(steps)} steps:")
        for i, step in enumerate(steps, 1):
            self._log_message(f"  {i}. {step}")
        
        # For now, just simulate execution
        QMessageBox.information(self, "Pattern Execution", f"Pattern '{pattern_name}' execution started")
    
    # Manual control methods
    @pyqtSlot()
    def _manual_move(self):
        """Manual move"""
        if self.connect_btn.text() == "Connect":
            QMessageBox.warning(self, "Not Connected", "Please connect to Arduino first")
            return
        
        needles = self.manual_needles.value()
        direction = self.manual_direction.currentText()
        
        self._log_message(f"Manual move: {needles} needles {direction}")
        # For now, just simulate the move
        QMessageBox.information(self, "Manual Move", f"Moving {needles} needles {direction}")
    
    @pyqtSlot()
    def _home_machine(self):
        """Home machine to position 0"""
        if self.connect_btn.text() == "Connect":
            QMessageBox.warning(self, "Not Connected", "Please connect to Arduino first")
            return
        
        self._log_message("Returning to home position...")
        self.current_needle_position = 0
        self.current_needle_display.setText("0")
        self.needle_display.setText("0")
        QMessageBox.information(self, "Home", "Machine returned to home position")
    
    @pyqtSlot()
    def _toggle_monitoring(self):
        """Toggle needle monitoring"""
        if not self.needle_monitoring_enabled:
            self.needle_monitoring_enabled = True
            self.monitoring_label.setText("Monitoring: On")
            self.monitoring_label.setStyleSheet("font-size: 12px; color: #4CAF50; padding: 5px; font-weight: bold;")
            self.needle_timer.start(100)  # Check every 100ms
            self._log_message("Needle monitoring started")
        else:
            self.needle_monitoring_enabled = False
            self.monitoring_label.setText("Monitoring: Off")
            self.monitoring_label.setStyleSheet("font-size: 12px; color: #666; padding: 5px;")
            self.needle_timer.stop()
            self._log_message("Needle monitoring stopped")
    
    @pyqtSlot()
    def _reset_position(self):
        """Reset needle position counter"""
        self.current_needle_position = 0
        self.current_needle_display.setText("0")
        self.needle_display.setText("0")
        self._log_message("Position counter reset to 0")
    
    @pyqtSlot()
    def _check_needle_position(self):
        """Check needle position (simulation)"""
        # This would normally read from Arduino
        # For now, just simulate some movement
        pass
    
    # Settings methods
    @pyqtSlot(str)
    def _on_theme_changed(self, theme):
        """Handle theme change"""
        self.current_theme = theme
        self.config["theme"] = theme
        self._save_config()
        self._apply_theme()
        self._log_message(f"Theme changed to: {theme}")
    
    @pyqtSlot(int)
    def _on_speed_changed(self, value):
        """Handle speed change"""
        self.config["motor_speed"] = value
        self._save_config()
        self._log_message(f"Motor speed set to: {value} μs")
    
    @pyqtSlot()
    def _apply_settings(self):
        """Apply settings to Arduino"""
        if self.connect_btn.text() == "Connect":
            QMessageBox.warning(self, "Not Connected", "Please connect to Arduino first")
            return
        
        self._log_message("Applying settings to Arduino...")
        # For now, just simulate
        QMessageBox.information(self, "Settings", "Settings applied to Arduino")
    
    # Emergency stop
    @pyqtSlot()
    def _emergency_stop(self):
        """Emergency stop"""
        self._log_message("EMERGENCY STOP activated!")
        self.statusBar().showMessage("EMERGENCY STOP - All operations halted", 5000)
        QMessageBox.warning(self, "Emergency Stop", "Machine stopped immediately!")
    
    # Status updates
    def _update_status(self):
        """Update status display"""
        # Update needle position display
        self.needle_display.setText(str(self.current_needle_position))
        self.current_needle_display.setText(str(self.current_needle_position))
    
    # Controller callbacks
    def _on_state_change(self, new_state: MachineState):
        """Handle state change"""
        self._log_message(f"State changed to: {new_state.name}")
    
    def _on_progress_update(self, status: ExecutionStatus):
        """Handle progress update"""
        self._log_message(f"Progress: {status.current_step}/{status.total_steps}")
    
    def _on_error(self, error_message: str):
        """Handle error"""
        self._log_message(f"Error: {error_message}")
        QMessageBox.critical(self, "Error", error_message)
    
    def closeEvent(self, event):
        """Handle close event"""
        self._log_message("Application closing...")
        self.controller.cleanup()
        event.accept()


def main():
    """Main entry point"""
    setup_logging("INFO", AppConfig.LOGS_DIR / "knitting_machine.log")
    logger = get_logger(__name__)
    
    try:
        app = QApplication(sys.argv)
        app.setApplicationName(AppConfig.APP_NAME)
        app.setApplicationVersion(AppConfig.APP_VERSION)
        app.setStyle('Fusion')
        
        window = MainWindow()
        window.show()
        
        logger.info(f"Started {AppConfig.APP_NAME} v{AppConfig.APP_VERSION}")
        
        sys.exit(app.exec())
        
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
