#!/usr/bin/env python3
"""
Core Application Logic
Clean separation of business logic from UI
"""

from typing import Optional, List, Callable, Dict, Any
from dataclasses import dataclass
import time
import threading
from enum import Enum

from ..patterns.models import KnittingPattern, PatternStep, PatternManager
from ..hardware.wifi_manager import WiFiManager, CommandResult, CommandStatus
from ..utils.logger import get_logger


class MachineState(Enum):
    """Current machine state"""
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    EXECUTING = "executing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class ExecutionStatus:
    """Current pattern execution status"""
    current_step: int
    total_steps: int
    current_repetition: int
    total_repetitions: int
    needles_completed: int
    total_needles: int
    estimated_time_remaining: float
    errors: List[str]


class KnittingController:
    """Core application controller managing all business logic"""
    
    def __init__(self, patterns_dir: str, machine_needle_count: int = 48):
        self.logger = get_logger(__name__)
        
        # Core components
        self.wifi_manager = WiFiManager()
        self.pattern_manager = PatternManager(patterns_dir)
        
        # State
        self.machine_state = MachineState.DISCONNECTED
        self.current_pattern: Optional[KnittingPattern] = None
        self.execution_status: Optional[ExecutionStatus] = None
        self.machine_needle_count = machine_needle_count
        self.current_needle_position = 0
        
        # Callbacks for UI updates
        self.state_change_callback: Optional[Callable[[MachineState], None]] = None
        self.progress_callback: Optional[Callable[[ExecutionStatus], None]] = None
        self.error_callback: Optional[Callable[[str], None]] = None
        
        # Threading
        self._execution_thread: Optional[threading.Thread] = None
        self._stop_execution = threading.Event()
        
        self.logger.info("Knitting controller initialized")
    
    def set_callbacks(self, 
                     state_callback: Optional[Callable[[MachineState], None]] = None,
                     progress_callback: Optional[Callable[[ExecutionStatus], None]] = None,
                     error_callback: Optional[Callable[[str], None]] = None):
        """Set UI callback functions"""
        self.state_change_callback = state_callback
        self.progress_callback = progress_callback  
        self.error_callback = error_callback
    
    def connect_machine(self, device_info: str, baudrate: int = None) -> bool:
        """Connect to knitting machine via WiFi"""
        try:
            success = self.wifi_manager.connect(device_info, baudrate)
            if success:
                self._set_state(MachineState.CONNECTED)
                self.logger.info(f"Connected to machine at {device_info}")
            else:
                self._notify_error("Failed to connect to machine")
            return success
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            self._notify_error(f"Connection error: {e}")
            return False
    
    def disconnect_machine(self):
        """Disconnect from knitting machine"""
        try:
            self.stop_execution()
            self.wifi_manager.disconnect()
            self._set_state(MachineState.DISCONNECTED)
            self.logger.info("Disconnected from machine")
        except Exception as e:
            self.logger.error(f"Disconnection error: {e}")
    
    def load_pattern(self, name: str) -> bool:
        """Load a pattern from storage"""
        try:
            pattern = self.pattern_manager.load_pattern(name)
            if pattern:
                self.current_pattern = pattern
                self.logger.info(f"Loaded pattern: {name}")
                return True
            else:
                self._notify_error(f"Pattern '{name}' not found")
                return False
        except Exception as e:
            self.logger.error(f"Error loading pattern: {e}")
            self._notify_error(f"Error loading pattern: {e}")
            return False
    
    def save_pattern(self, pattern: KnittingPattern) -> bool:
        """Save a pattern to storage"""
        try:
            success = self.pattern_manager.save_pattern(pattern)
            if success:
                self.logger.info(f"Saved pattern: {pattern.name}")
            else:
                self._notify_error("Failed to save pattern")
            return success
        except Exception as e:
            self.logger.error(f"Error saving pattern: {e}")
            self._notify_error(f"Error saving pattern: {e}")
            return False
    
    def execute_pattern(self, pattern: KnittingPattern) -> bool:
        """Execute a knitting pattern"""
        if self.machine_state != MachineState.CONNECTED:
            self._notify_error("Machine not connected")
            return False
        
        if not pattern.steps:
            self._notify_error("Pattern has no steps")
            return False
        
        try:
            self.current_pattern = pattern
            self._stop_execution.clear()
            self._execution_thread = threading.Thread(
                target=self._execute_pattern_thread,
                args=(pattern,),
                daemon=True
            )
            self._execution_thread.start()
            return True
        except Exception as e:
            self.logger.error(f"Error starting pattern execution: {e}")
            self._notify_error(f"Error starting pattern execution: {e}")
            return False
    
    def stop_execution(self):
        """Stop current pattern execution"""
        self._stop_execution.set()
        self.wifi_manager.emergency_stop()
        
        if self._execution_thread and self._execution_thread.is_alive():
            self._execution_thread.join(timeout=2.0)
        
        if self.machine_state in [MachineState.EXECUTING, MachineState.PAUSED]:
            self._set_state(MachineState.CONNECTED)
        
        self.logger.info("Pattern execution stopped")
    
    def move_to_needle(self, target_needle: int) -> bool:
        """Move to specific needle position"""
        if self.machine_state not in [MachineState.CONNECTED, MachineState.STOPPED]:
            return False
        
        try:
            steps_needed = self._calculate_steps_to_needle(target_needle)
            if steps_needed == 0:
                return True
            
            direction = "CW" if steps_needed > 0 else "CCW" 
            command = f"M{abs(steps_needed)}_{direction}"
            
            def move_callback(result: CommandResult):
                if result.status == CommandStatus.COMPLETED:
                    self.current_needle_position = target_needle
                    self.logger.info(f"Moved to needle {target_needle}")
                else:
                    self._notify_error(f"Move failed: {result.error}")
            
            return self.wifi_manager.send_command(command, move_callback)
        except Exception as e:
            self.logger.error(f"Error moving to needle: {e}")
            self._notify_error(f"Error moving to needle: {e}")
            return False
    
    def home_machine(self) -> bool:
        """Return machine to home position (needle 0)"""
        return self.move_to_needle(0)
    
    def get_available_ports(self) -> List[str]:
        """Get available WiFi devices"""
        return self.wifi_manager.get_available_ports()
    
    def get_machine_status(self) -> Dict[str, Any]:
        """Get comprehensive machine status"""
        wifi_status = self.wifi_manager.device_status
        connection_info = self.wifi_manager.get_connection_info()
        return {
            "state": self.machine_state.value,
            "connected": self.wifi_manager.connected,
            "host": connection_info.get("host", "N/A"),
            "port": connection_info.get("port", "N/A"),
            "current_needle": self.current_needle_position,
            "total_needles": self.machine_needle_count,
            "queue_size": self.wifi_manager.get_queue_size(),
            "current_pattern": self.current_pattern.name if self.current_pattern else None,
            "execution_status": self.execution_status
        }
    
    def _execute_pattern_thread(self, pattern: KnittingPattern):
        """Execute pattern in background thread"""
        try:
            self._set_state(MachineState.EXECUTING)
            
            # Initialize execution status
            total_needles = pattern.total_needles
            self.execution_status = ExecutionStatus(
                current_step=0,
                total_steps=len(pattern.steps) * pattern.repetitions,
                current_repetition=0,
                total_repetitions=pattern.repetitions,
                needles_completed=0,
                total_needles=total_needles,
                estimated_time_remaining=0.0,
                errors=[]
            )
            
            start_time = time.time()
            completed_steps = 0
            
            # Execute pattern repetitions
            for rep in range(pattern.repetitions):
                if self._stop_execution.is_set():
                    break
                
                self.execution_status.current_repetition = rep + 1
                
                # Execute each step
                for step_idx, step in enumerate(pattern.steps):
                    if self._stop_execution.is_set():
                        break
                    
                    self.execution_status.current_step = completed_steps + 1
                    
                    # Execute step
                    success = self._execute_step(step)
                    if not success:
                        error_msg = f"Step {step_idx + 1} failed in repetition {rep + 1}"
                        self.execution_status.errors.append(error_msg)
                        self._notify_error(error_msg)
                        continue
                    
                    # Update progress
                    completed_steps += 1
                    self.execution_status.needles_completed += step.total_needles
                    
                    # Estimate remaining time
                    elapsed = time.time() - start_time
                    if completed_steps > 0:
                        avg_time_per_step = elapsed / completed_steps
                        remaining_steps = self.execution_status.total_steps - completed_steps
                        self.execution_status.estimated_time_remaining = avg_time_per_step * remaining_steps
                    
                    # Notify progress
                    if self.progress_callback:
                        self.progress_callback(self.execution_status)
                    
                    time.sleep(0.1)  # Brief pause between steps
            
            # Execution complete
            if not self._stop_execution.is_set():
                self._set_state(MachineState.CONNECTED)
                self.logger.info("Pattern execution completed")
            
        except Exception as e:
            self.logger.error(f"Pattern execution error: {e}")
            self._notify_error(f"Pattern execution error: {e}")
            self._set_state(MachineState.ERROR)
    
    def _execute_step(self, step: PatternStep) -> bool:
        """Execute a single pattern step"""
        try:
            # Calculate total needles to move
            total_needles = step.total_needles
            command = f"M{total_needles}_{step.direction}"
            
            # Send command and wait for completion
            result_received = threading.Event()
            execution_result = None
            
            def step_callback(result: CommandResult):
                nonlocal execution_result
                execution_result = result
                result_received.set()
            
            if not self.wifi_manager.send_command(command, step_callback):
                return False
            
            # Wait for completion or timeout
            if not result_received.wait(timeout=30.0):
                return False
            
            return execution_result.status == CommandStatus.COMPLETED
            
        except Exception as e:
            self.logger.error(f"Step execution error: {e}")
            return False
    
    def _calculate_steps_to_needle(self, target_needle: int) -> int:
        """Calculate steps needed to reach target needle"""
        current = self.current_needle_position
        target = target_needle % self.machine_needle_count
        
        # Calculate shortest path
        clockwise = (target - current) % self.machine_needle_count
        counterclockwise = (current - target) % self.machine_needle_count
        
        if clockwise <= counterclockwise:
            return clockwise
        else:
            return -counterclockwise
    
    def _set_state(self, new_state: MachineState):
        """Update machine state and notify UI"""
        if self.machine_state != new_state:
            self.machine_state = new_state
            self.logger.info(f"Machine state changed to: {new_state.value}")
            if self.state_change_callback:
                self.state_change_callback(new_state)
    
    def _notify_error(self, error_message: str):
        """Notify UI of error"""
        self.logger.error(error_message)
        if self.error_callback:
            self.error_callback(error_message)
    
    def cleanup(self):
        """Clean up resources"""
        try:
            self.stop_execution()
            self.disconnect_machine()
            self.logger.info("Controller cleanup completed")
        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")
