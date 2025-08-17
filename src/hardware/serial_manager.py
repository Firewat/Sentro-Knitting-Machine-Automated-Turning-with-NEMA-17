#!/usr/bin/env python3
"""
Hardware Communication Layer
Optimized, thread-safe Arduino communication
"""

import serial
import serial.tools.list_ports
import threading
import time
from typing import List, Optional, Callable, Dict, Any
from queue import Queue, Empty
from dataclasses import dataclass
from enum import Enum
import logging

from ..utils.logger import get_logger


class CommandStatus(Enum):
    """Command execution status"""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CommandResult:
    """Result of a command execution"""
    command: str
    status: CommandStatus
    response: str = ""
    error: str = ""
    execution_time: float = 0.0


class SerialManager:
    """Thread-safe serial communication manager"""
    
    def __init__(self, chunk_size: int = 16000, timeout: float = 2.0):
        self.chunk_size = chunk_size
        self.timeout = timeout
        self.serial_conn: Optional[serial.Serial] = None
        self.is_connected = False
        self.command_queue = Queue()
        self.response_callbacks: Dict[str, Callable] = {}
        self._stop_flag = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self.logger = get_logger(__name__)
    
    def connect(self, port: str, baudrate: int = 9600) -> bool:
        """Connect to Arduino with improved error handling"""
        with self._lock:
            try:
                if self.is_connected:
                    self.disconnect()
                
                self.serial_conn = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    timeout=self.timeout,
                    write_timeout=self.timeout
                )
                
                # Test connection
                time.sleep(2)  # Allow Arduino to reset
                self.serial_conn.write(b"TEST\\n")
                self.serial_conn.flush()
                
                self.is_connected = True
                self._start_worker()
                
                self.logger.info(f"Connected to Arduino on {port} at {baudrate} baud")
                return True
                
            except Exception as e:
                self.logger.error(f"Connection failed: {e}")
                self.is_connected = False
                if self.serial_conn:
                    try:
                        self.serial_conn.close()
                    except:
                        pass
                    self.serial_conn = None
                return False
    
    def disconnect(self):
        """Safely disconnect from Arduino"""
        with self._lock:
            if not self.is_connected:
                return
            
            self.is_connected = False
            self._stop_flag.set()
            
            # Wait for worker thread to finish
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=1.0)
            
            if self.serial_conn:
                try:
                    self.serial_conn.close()
                except:
                    pass
                self.serial_conn = None
            
            # Clear queue
            while not self.command_queue.empty():
                try:
                    self.command_queue.get_nowait()
                except Empty:
                    break
            
            self.logger.info("Disconnected from Arduino")
    
    def send_command(self, command: str, callback: Optional[Callable[[CommandResult], None]] = None) -> bool:
        """Queue command for execution"""
        if not self.is_connected:
            if callback:
                result = CommandResult(command, CommandStatus.FAILED, error="Not connected")
                callback(result)
            return False
        
        try:
            self.command_queue.put((command, callback), timeout=1.0)
            return True
        except:
            if callback:
                result = CommandResult(command, CommandStatus.FAILED, error="Queue full")
                callback(result)
            return False
    
    def send_commands_bulk(self, commands: List[str], 
                          progress_callback: Optional[Callable[[int, int], None]] = None) -> bool:
        """Send multiple commands with progress tracking"""
        if not commands or not self.is_connected:
            return False
        
        results = []
        completed = 0
        
        def command_callback(result: CommandResult):
            nonlocal completed
            results.append(result)
            completed += 1
            if progress_callback:
                progress_callback(completed, len(commands))
        
        # Queue all commands
        for command in commands:
            if not self.send_command(command, command_callback):
                return False
        
        return True
    
    def emergency_stop(self):
        """Immediately stop all operations"""
        with self._lock:
            if self.serial_conn and self.is_connected:
                try:
                    # Send emergency stop command
                    self.serial_conn.write(b"EMERGENCY_STOP\\n")
                    self.serial_conn.flush()
                except:
                    pass
            
            # Clear command queue
            while not self.command_queue.empty():
                try:
                    command, callback = self.command_queue.get_nowait()
                    if callback:
                        result = CommandResult(command, CommandStatus.CANCELLED)
                        callback(result)
                except Empty:
                    break
        
        self.logger.warning("Emergency stop executed")
    
    def _start_worker(self):
        """Start background worker thread"""
        self._stop_flag.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
    
    def _worker_loop(self):
        """Main worker thread loop"""
        while not self._stop_flag.is_set() and self.is_connected:
            try:
                # Get next command from queue
                command, callback = self.command_queue.get(timeout=0.1)
                
                # Execute command
                result = self._execute_command(command)
                
                # Call callback if provided
                if callback:
                    try:
                        callback(result)
                    except Exception as e:
                        self.logger.error(f"Callback error: {e}")
                
                self.command_queue.task_done()
                
            except Empty:
                continue  # No commands, keep waiting
            except Exception as e:
                self.logger.error(f"Worker thread error: {e}")
    
    def _execute_command(self, command: str) -> CommandResult:
        """Execute a single command with timing"""
        start_time = time.time()
        
        try:
            if not self.is_connected or not self.serial_conn:
                return CommandResult(command, CommandStatus.FAILED, error="Not connected")
            
            # Split large commands into chunks
            if len(command) > self.chunk_size:
                return self._execute_chunked_command(command, start_time)
            
            # Send command
            cmd_bytes = f"{command}\\n".encode('utf-8')
            self.serial_conn.write(cmd_bytes)
            self.serial_conn.flush()
            
            # Wait for response
            response = ""
            while True:
                if self.serial_conn.in_waiting > 0:
                    line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                    response += line + "\\n"
                    if "OK" in line or "DONE" in line:
                        break
                
                if time.time() - start_time > self.timeout:
                    return CommandResult(command, CommandStatus.FAILED, 
                                       error="Timeout", execution_time=time.time() - start_time)
                
                if self._stop_flag.is_set():
                    return CommandResult(command, CommandStatus.CANCELLED,
                                       execution_time=time.time() - start_time)
                
                time.sleep(0.01)
            
            execution_time = time.time() - start_time
            return CommandResult(command, CommandStatus.COMPLETED, 
                               response=response, execution_time=execution_time)
            
        except Exception as e:
            execution_time = time.time() - start_time
            return CommandResult(command, CommandStatus.FAILED, 
                               error=str(e), execution_time=execution_time)
    
    def _execute_chunked_command(self, command: str, start_time: float) -> CommandResult:
        """Execute large command in chunks"""
        try:
            chunks = [command[i:i+self.chunk_size] 
                     for i in range(0, len(command), self.chunk_size)]
            
            response = ""
            for i, chunk in enumerate(chunks):
                if self._stop_flag.is_set():
                    return CommandResult(command, CommandStatus.CANCELLED)
                
                # Send chunk with index
                chunk_cmd = f"CHUNK_{i}_{len(chunks)}:{chunk}"
                cmd_bytes = f"{chunk_cmd}\\n".encode('utf-8')
                self.serial_conn.write(cmd_bytes)
                self.serial_conn.flush()
                
                # Wait for chunk acknowledgment
                chunk_start = time.time()
                while True:
                    if self.serial_conn.in_waiting > 0:
                        line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                        response += line + "\\n"
                        if f"CHUNK_{i}_OK" in line:
                            break
                    
                    if time.time() - chunk_start > self.timeout:
                        return CommandResult(command, CommandStatus.FAILED,
                                           error=f"Chunk {i} timeout")
                    
                    time.sleep(0.01)
            
            execution_time = time.time() - start_time
            return CommandResult(command, CommandStatus.COMPLETED,
                               response=response, execution_time=execution_time)
            
        except Exception as e:
            execution_time = time.time() - start_time
            return CommandResult(command, CommandStatus.FAILED,
                               error=str(e), execution_time=execution_time)
    
    @staticmethod
    def get_available_ports() -> List[str]:
        """Get list of available serial ports"""
        try:
            ports = serial.tools.list_ports.comports()
            return [port.device for port in ports]
        except:
            return []
    
    def get_status(self) -> Dict[str, Any]:
        """Get current connection status"""
        return {
            "connected": self.is_connected,
            "port": getattr(self.serial_conn, 'port', None) if self.serial_conn else None,
            "baudrate": getattr(self.serial_conn, 'baudrate', None) if self.serial_conn else None,
            "queue_size": self.command_queue.qsize(),
            "worker_alive": self._worker_thread.is_alive() if self._worker_thread else False
        }
