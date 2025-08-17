#!/usr/bin/env python3
"""
WiFi Hardware Communication Layer
WiFi-based communication manager compatible with SerialManager interface
"""

import time
import threading
from typing import List, Optional, Callable, Dict, Any
from queue import Queue, Empty
from dataclasses import dataclass
from enum import Enum

from ..communication.wifi_communicator import WiFiCommunicator
from ..utils.logger import get_logger


class CommandStatus(Enum):
    """Command execution status (imported for compatibility)"""
    PENDING = "pending"
    EXECUTING = "executing"  
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass 
class CommandResult:
    """Result of a command execution (imported for compatibility)"""
    command: str
    status: CommandStatus
    response: str = ""
    error: str = ""
    execution_time: float = 0.0


class WiFiManager:
    """
    WiFi communication manager that provides the same interface as SerialManager
    
    This allows seamless replacement of serial communication with WiFi
    without changing the controller or UI code.
    """
    
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.wifi_comm: Optional[WiFiCommunicator] = None
        self.is_connected = False
        self.command_queue = Queue()
        self.response_callbacks: Dict[str, Callable] = {}
        self._stop_flag = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        
        # Device discovery
        self.discovered_devices = {}
        
        # Status tracking
        self._last_command_result: Optional[CommandResult] = None
        
        self.logger = get_logger(__name__)
        
        # Initialize WiFi communicator
        self._init_wifi_communicator()
    
    def _init_wifi_communicator(self):
        """Initialize WiFi communicator"""
        self.wifi_comm = WiFiCommunicator()
        
        # Connect signals
        self.wifi_comm.response_received.connect(self._on_response_received)
        self.wifi_comm.error_occurred.connect(self._on_error_occurred)
        self.wifi_comm.connection_status_changed.connect(self._on_connection_changed)
        self.wifi_comm.device_discovered.connect(self._on_device_discovered)
        
        # Start device discovery
        self.wifi_comm.start_device_discovery()
        
        self.logger.info("WiFiManager initialized")
    
    def _on_response_received(self, response: str):
        """Handle response from WiFi communicator"""
        if self._last_command_result:
            self._last_command_result.response = response
            self._last_command_result.status = CommandStatus.COMPLETED
            
            # Notify callbacks
            for callback in self.response_callbacks.values():
                try:
                    callback(self._last_command_result)
                except Exception as e:
                    self.logger.error(f"Callback error: {e}")
    
    def _on_error_occurred(self, error: str):
        """Handle error from WiFi communicator"""
        if self._last_command_result:
            self._last_command_result.error = error
            self._last_command_result.status = CommandStatus.FAILED
        
        self.logger.error(f"WiFi error: {error}")
    
    def _on_connection_changed(self, connected: bool):
        """Handle connection status change"""
        self.is_connected = connected
        self.logger.info(f"Connection status changed: {connected}")
    
    def _on_device_discovered(self, name: str, ip: str, port: int):
        """Handle discovered device"""
        self.discovered_devices[name] = {
            'ip': ip,
            'port': port,
            'name': name
        }
        self.logger.info(f"Discovered device: {name} at {ip}:{port}")
    
    # ========================================
    # INTERFACE METHODS (Compatible with SerialManager)
    # ========================================
    
    def get_available_ports(self) -> List[Dict[str, str]]:
        """Get available WiFi devices (replaces COM ports)"""
        devices = []
        for name, info in self.discovered_devices.items():
            devices.append({
                'port': f"{info['ip']}:{info['port']}",
                'description': f"Knitting Machine - {name}",
                'name': name,
                'ip': info['ip'],
                'port': info['port']
            })
        
        if not devices:
            # Return manual entry option
            devices.append({
                'port': 'manual',
                'description': 'Manual IP Entry',
                'name': 'manual',
                'ip': '',
                'port': 80
            })
        
        return devices
    
    def connect(self, device_info: str, baudrate: int = None) -> bool:
        """
        Connect to ESP8266 device
        
        Args:
            device_info: Either IP:port string or device name
            baudrate: Ignored for WiFi (compatibility with SerialManager)
        """
        try:
            # Parse device info
            if ':' in device_info:
                # Direct IP:port
                ip, port = device_info.split(':')
                port = int(port)
            elif device_info in self.discovered_devices:
                # Device name lookup
                info = self.discovered_devices[device_info]
                ip = info['ip']
                port = info['port']
            else:
                # Try as IP with default port
                ip = device_info
                port = 80
            
            # Connect to device
            if self.wifi_comm.connect_to_device(ip, port):
                self.is_connected = True
                
                # Start worker thread
                self._start_worker_thread()
                
                self.logger.info(f"Connected to {ip}:{port}")
                return True
            else:
                self.logger.error(f"Failed to connect to {ip}:{port}")
                return False
                
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from ESP8266 device"""
        try:
            # Stop worker thread
            self._stop_worker_thread()
            
            # Disconnect WiFi
            if self.wifi_comm:
                self.wifi_comm.disconnect_from_device()
            
            self.is_connected = False
            self.logger.info("Disconnected from device")
            
        except Exception as e:
            self.logger.error(f"Disconnect error: {e}")
    
    def send_command(self, command: str, callback: Optional[Callable] = None) -> CommandResult:
        """
        Send command to ESP8266
        
        Args:
            command: Command string
            callback: Optional callback for response
            
        Returns:
            CommandResult object
        """
        if not self.is_connected:
            return CommandResult(
                command=command,
                status=CommandStatus.FAILED,
                error="Not connected to device"
            )
        
        start_time = time.time()
        
        # Create command result
        result = CommandResult(
            command=command,
            status=CommandStatus.EXECUTING
        )
        
        self._last_command_result = result
        
        try:
            # Send command via WiFi
            if self.wifi_comm.send_command(command):
                result.status = CommandStatus.PENDING
                
                # Add callback if provided
                if callback:
                    callback_id = f"{command}_{int(time.time() * 1000)}"
                    self.response_callbacks[callback_id] = callback
                
                # Wait for response (with timeout)
                timeout_start = time.time()
                while (result.status == CommandStatus.PENDING and 
                       time.time() - timeout_start < self.timeout):
                    time.sleep(0.1)
                
                # Check final status
                if result.status == CommandStatus.PENDING:
                    result.status = CommandStatus.FAILED
                    result.error = "Command timeout"
                
            else:
                result.status = CommandStatus.FAILED
                result.error = "Failed to send command"
            
            result.execution_time = time.time() - start_time
            return result
            
        except Exception as e:
            result.status = CommandStatus.FAILED
            result.error = str(e)
            result.execution_time = time.time() - start_time
            return result
    
    def send_command_async(self, command: str, callback: Optional[Callable] = None):
        """Send command asynchronously"""
        def async_send():
            result = self.send_command(command, callback)
            if callback:
                callback(result)
        
        thread = threading.Thread(target=async_send)
        thread.daemon = True
        thread.start()
    
    def queue_command(self, command: str):
        """Queue command for execution"""
        self.command_queue.put(command)
    
    def clear_queue(self):
        """Clear command queue"""
        while not self.command_queue.empty():
            try:
                self.command_queue.get_nowait()
            except Empty:
                break
    
    def get_queue_size(self) -> int:
        """Get number of queued commands"""
        return self.command_queue.qsize()
    
    # ========================================
    # WORKER THREAD MANAGEMENT
    # ========================================
    
    def _start_worker_thread(self):
        """Start worker thread for processing commands"""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        
        self._stop_flag.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop)
        self._worker_thread.daemon = True
        self._worker_thread.start()
        
        self.logger.info("Worker thread started")
    
    def _stop_worker_thread(self):
        """Stop worker thread"""
        self._stop_flag.set()
        
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        
        self.logger.info("Worker thread stopped")
    
    def _worker_loop(self):
        """Main worker thread loop"""
        while not self._stop_flag.is_set():
            try:
                # Process queued commands
                try:
                    command = self.command_queue.get(timeout=1.0)
                    self.send_command(command)
                except Empty:
                    continue
                
            except Exception as e:
                self.logger.error(f"Worker thread error: {e}")
                time.sleep(1.0)
    
    # ========================================
    # PATTERN METHODS (WiFi-specific enhancements)
    # ========================================
    
    def upload_pattern(self, filename: str, pattern_data: dict) -> CommandResult:
        """Upload pattern to ESP8266"""
        if not self.is_connected:
            return CommandResult(
                command=f"upload_pattern:{filename}",
                status=CommandStatus.FAILED,
                error="Not connected to device"
            )
        
        start_time = time.time()
        
        try:
            if self.wifi_comm.upload_pattern(filename, pattern_data):
                return CommandResult(
                    command=f"upload_pattern:{filename}",
                    status=CommandStatus.COMPLETED,
                    response=f"Pattern {filename} uploaded successfully",
                    execution_time=time.time() - start_time
                )
            else:
                return CommandResult(
                    command=f"upload_pattern:{filename}",
                    status=CommandStatus.FAILED,
                    error="Pattern upload failed",
                    execution_time=time.time() - start_time
                )
                
        except Exception as e:
            return CommandResult(
                command=f"upload_pattern:{filename}",
                status=CommandStatus.FAILED,
                error=str(e),
                execution_time=time.time() - start_time
            )
    
    def start_pattern_execution(self, filename: str) -> CommandResult:
        """Start pattern execution on ESP8266"""
        if not self.is_connected:
            return CommandResult(
                command=f"start_pattern:{filename}",
                status=CommandStatus.FAILED,
                error="Not connected to device"
            )
        
        start_time = time.time()
        
        try:
            if self.wifi_comm.start_pattern(filename):
                return CommandResult(
                    command=f"start_pattern:{filename}",
                    status=CommandStatus.COMPLETED,
                    response=f"Pattern {filename} started",
                    execution_time=time.time() - start_time
                )
            else:
                return CommandResult(
                    command=f"start_pattern:{filename}",
                    status=CommandStatus.FAILED,
                    error="Pattern start failed",
                    execution_time=time.time() - start_time
                )
                
        except Exception as e:
            return CommandResult(
                command=f"start_pattern:{filename}",
                status=CommandStatus.FAILED,
                error=str(e),
                execution_time=time.time() - start_time
            )
    
    def pause_pattern_execution(self) -> CommandResult:
        """Pause pattern execution"""
        start_time = time.time()
        
        try:
            if self.wifi_comm.pause_pattern():
                return CommandResult(
                    command="pause_pattern",
                    status=CommandStatus.COMPLETED,
                    response="Pattern paused",
                    execution_time=time.time() - start_time
                )
            else:
                return CommandResult(
                    command="pause_pattern",
                    status=CommandStatus.FAILED,
                    error="Pattern pause failed",
                    execution_time=time.time() - start_time
                )
                
        except Exception as e:
            return CommandResult(
                command="pause_pattern",
                status=CommandStatus.FAILED,
                error=str(e),
                execution_time=time.time() - start_time
            )
    
    def resume_pattern_execution(self) -> CommandResult:
        """Resume pattern execution"""
        start_time = time.time()
        
        try:
            if self.wifi_comm.resume_pattern():
                return CommandResult(
                    command="resume_pattern",
                    status=CommandStatus.COMPLETED,
                    response="Pattern resumed",
                    execution_time=time.time() - start_time
                )
            else:
                return CommandResult(
                    command="resume_pattern",
                    status=CommandStatus.FAILED,
                    error="Pattern resume failed",
                    execution_time=time.time() - start_time
                )
                
        except Exception as e:
            return CommandResult(
                command="resume_pattern",
                status=CommandStatus.FAILED,
                error=str(e),
                execution_time=time.time() - start_time
            )
    
    def stop_pattern_execution(self) -> CommandResult:
        """Stop pattern execution"""
        start_time = time.time()
        
        try:
            if self.wifi_comm.stop_pattern():
                return CommandResult(
                    command="stop_pattern",
                    status=CommandStatus.COMPLETED,
                    response="Pattern stopped",
                    execution_time=time.time() - start_time
                )
            else:
                return CommandResult(
                    command="stop_pattern",
                    status=CommandStatus.FAILED,
                    error="Pattern stop failed",
                    execution_time=time.time() - start_time
                )
                
        except Exception as e:
            return CommandResult(
                command="stop_pattern",
                status=CommandStatus.FAILED,
                error=str(e),
                execution_time=time.time() - start_time
            )
    
    def get_remote_patterns(self) -> List[Dict]:
        """Get list of patterns stored on ESP8266"""
        if not self.is_connected:
            return []
        
        try:
            patterns = self.wifi_comm.get_pattern_list()
            return patterns if patterns else []
        except Exception as e:
            self.logger.error(f"Failed to get remote patterns: {e}")
            return []
    
    # ========================================
    # PROPERTIES AND STATUS
    # ========================================
    
    @property
    def connected(self) -> bool:
        """Check if connected to device"""
        return self.is_connected and self.wifi_comm and self.wifi_comm.is_connected
    
    @property
    def device_status(self) -> Dict[str, Any]:
        """Get current device status"""
        if self.wifi_comm:
            return self.wifi_comm.current_status
        return {}
    
    def get_connection_info(self) -> Dict[str, str]:
        """Get current connection information"""
        if self.connected and self.wifi_comm:
            return {
                'type': 'WiFi',
                'host': self.wifi_comm.host,
                'port': str(self.wifi_comm.port),
                'status': 'Connected'
            }
        return {
            'type': 'WiFi',
            'host': 'Not connected',
            'port': 'N/A',
            'status': 'Disconnected'
        }
    
    def refresh_devices(self):
        """Refresh device discovery"""
        if self.wifi_comm:
            self.wifi_comm.stop_device_discovery()
            time.sleep(1)
            self.wifi_comm.start_device_discovery()
    
    # ========================================
    # CLEANUP
    # ========================================
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            self.disconnect()
            
            if self.wifi_comm:
                self.wifi_comm.stop_device_discovery()
            
            self.logger.info("WiFiManager cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.cleanup()
