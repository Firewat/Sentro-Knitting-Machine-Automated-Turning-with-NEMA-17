"""
WiFi Communication Module for ESP8266 Knitting Machine

This module provides WiFi-based communication with the ESP8266 knitting machine,
replacing the previous serial communication system.

Features:
- Automatic device discovery via mDNS
- RESTful API communication  
- WebSocket real-time monitoring
- Connection management with auto-reconnection
- Multi-threading for non-blocking operations
- Comprehensive error handling and recovery
"""

import json
import time
import threading
import requests
from typing import Optional, Dict, Any, Callable, List
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer
import websocket
from zeroconf import ServiceBrowser, Zeroconf, ServiceListener
import socket


class DeviceDiscovery(ServiceListener, QObject):
    """Discovers ESP8266 knitting machines on the network using mDNS"""
    
    device_found = pyqtSignal(str, str, int)  # name, ip, port
    device_lost = pyqtSignal(str)  # name
    
    def __init__(self):
        super().__init__()
        self.zeroconf = None
        self.browser = None
        self.discovered_devices = {}
        
    def start_discovery(self):
        """Start discovering devices on the network"""
        try:
            self.zeroconf = Zeroconf()
            self.browser = ServiceBrowser(self.zeroconf, "_http._tcp.local.", self)
            print("Started device discovery...")
            return True
        except Exception as e:
            print(f"Failed to start device discovery: {e}")
            return False
    
    def stop_discovery(self):
        """Stop device discovery"""
        if self.browser:
            self.browser.cancel()
        if self.zeroconf:
            self.zeroconf.close()
        print("Stopped device discovery")
    
    def add_service(self, zeroconf, type, name):
        """Called when a new service is discovered"""
        try:
            info = zeroconf.get_service_info(type, name)
            if info and "knitting" in name.lower():
                device_name = name.split('.')[0]
                ip_address = socket.inet_ntoa(info.addresses[0])
                port = info.port
                
                self.discovered_devices[device_name] = {
                    'ip': ip_address,
                    'port': port,
                    'info': info
                }
                
                print(f"Found knitting machine: {device_name} at {ip_address}:{port}")
                self.device_found.emit(device_name, ip_address, port)
                
        except Exception as e:
            print(f"Error processing discovered service: {e}")
    
    def remove_service(self, zeroconf, type, name):
        """Called when a service is removed"""
        if "knitting" in name.lower():
            device_name = name.split('.')[0]
            if device_name in self.discovered_devices:
                del self.discovered_devices[device_name]
                self.device_lost.emit(device_name)
                print(f"Lost knitting machine: {device_name}")
    
    def update_service(self, zeroconf, type, name):
        """Called when a service is updated"""
        # Re-add the service to update info
        self.add_service(zeroconf, type, name)


class WebSocketClient(QThread):
    """WebSocket client for real-time communication with ESP8266"""
    
    # Signals
    status_received = pyqtSignal(dict)
    pattern_progress = pyqtSignal(dict)
    error_received = pyqtSignal(str)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    
    def __init__(self, host: str, port: int = 81):
        super().__init__()
        self.host = host
        self.port = port
        self.ws = None
        self.running = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 2  # seconds
        
    def run(self):
        """Main WebSocket thread loop"""
        self.running = True
        
        while self.running:
            try:
                self.connect_websocket()
                
                # Reset reconnect attempts on successful connection
                self.reconnect_attempts = 0
                
                # Keep connection alive
                while self.running and self.ws and self.ws.sock and self.ws.sock.connected:
                    # Send ping every 30 seconds
                    self.send_ping()
                    time.sleep(30)
                    
            except Exception as e:
                print(f"WebSocket error: {e}")
                self.error_received.emit(str(e))
                
                if self.running:
                    self.handle_reconnect()
                    
        print("WebSocket client stopped")
    
    def connect_websocket(self):
        """Establish WebSocket connection"""
        ws_url = f"ws://{self.host}:{self.port}/"
        print(f"Connecting to WebSocket: {ws_url}")
        
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        self.ws.run_forever()
    
    def on_open(self, ws):
        """Called when WebSocket connection opens"""
        print("WebSocket connected")
        self.connected.emit()
    
    def on_message(self, ws, message):
        """Called when WebSocket message is received"""
        try:
            data = json.loads(message)
            msg_type = data.get('type', '')
            
            if msg_type == 'status':
                self.status_received.emit(data)
            elif msg_type == 'pattern_progress':
                self.pattern_progress.emit(data)
            elif msg_type == 'error':
                self.error_received.emit(data.get('message', 'Unknown error'))
            elif msg_type == 'pong':
                # Heartbeat response
                pass
            else:
                print(f"Unknown message type: {msg_type}")
                
        except json.JSONDecodeError as e:
            print(f"Failed to parse WebSocket message: {e}")
    
    def on_error(self, ws, error):
        """Called when WebSocket error occurs"""
        print(f"WebSocket error: {error}")
        self.error_received.emit(str(error))
    
    def on_close(self, ws, close_status_code, close_msg):
        """Called when WebSocket connection closes"""
        print("WebSocket disconnected")
        self.disconnected.emit()
    
    def send_message(self, message: dict):
        """Send message via WebSocket"""
        if self.ws and self.ws.sock and self.ws.sock.connected:
            try:
                self.ws.send(json.dumps(message))
                return True
            except Exception as e:
                print(f"Failed to send WebSocket message: {e}")
                return False
        return False
    
    def send_ping(self):
        """Send ping to keep connection alive"""
        self.send_message({"type": "ping"})
    
    def handle_reconnect(self):
        """Handle WebSocket reconnection"""
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            print(f"Reconnecting WebSocket (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})...")
            time.sleep(self.reconnect_delay)
        else:
            print("Max reconnection attempts reached")
            self.running = False
    
    def stop(self):
        """Stop WebSocket client"""
        self.running = False
        if self.ws:
            self.ws.close()


class WiFiCommunicator(QObject):
    """
    Main WiFi communication class that replaces SerialWorker
    
    This class provides the same interface as SerialWorker but uses
    WiFi communication with the ESP8266 instead of serial.
    """
    
    # Signals (same as SerialWorker for compatibility)
    response_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    progress_updated = pyqtSignal(int, int)
    operation_completed = pyqtSignal()
    connection_status_changed = pyqtSignal(bool)
    device_discovered = pyqtSignal(str, str, int)  # name, ip, port
    
    def __init__(self):
        super().__init__()
        
        # Connection settings
        self.host = None
        self.port = 80
        self.websocket_port = 81
        self.connected = False
        self.timeout = 10  # seconds
        
        # Components
        self.device_discovery = DeviceDiscovery()
        self.websocket_client = None
        self.heartbeat_timer = QTimer()
        
        # Status tracking
        self.last_status = {}
        self.pattern_running = False
        
        # Setup connections
        self.setup_connections()
    
    def setup_connections(self):
        """Setup signal connections"""
        # Device discovery
        self.device_discovery.device_found.connect(self.on_device_discovered)
        self.device_discovery.device_lost.connect(self.on_device_lost)
        
        # Heartbeat timer
        self.heartbeat_timer.timeout.connect(self.check_connection)
        
    def start_device_discovery(self):
        """Start discovering ESP8266 devices on network"""
        return self.device_discovery.start_discovery()
    
    def stop_device_discovery(self):
        """Stop device discovery"""
        self.device_discovery.stop_discovery()
    
    def on_device_discovered(self, name: str, ip: str, port: int):
        """Handle discovered device"""
        print(f"Discovered device: {name} at {ip}:{port}")
        self.device_discovered.emit(name, ip, port)
    
    def on_device_lost(self, name: str):
        """Handle lost device"""
        print(f"Lost device: {name}")
    
    def connect_to_device(self, host: str, port: int = 80) -> bool:
        """Connect to ESP8266 device"""
        self.host = host
        self.port = port
        
        print(f"Connecting to {host}:{port}")
        
        # Test HTTP connection
        if not self.test_http_connection():
            self.error_occurred.emit(f"Cannot connect to {host}:{port}")
            return False
        
        # Setup WebSocket connection
        self.setup_websocket_connection()
        
        # Start heartbeat
        self.heartbeat_timer.start(5000)  # Check every 5 seconds
        
        self.connected = True
        self.connection_status_changed.emit(True)
        print(f"Successfully connected to {host}:{port}")
        return True
    
    def disconnect_from_device(self):
        """Disconnect from ESP8266 device"""
        self.connected = False
        
        # Stop heartbeat
        self.heartbeat_timer.stop()
        
        # Close WebSocket
        if self.websocket_client:
            self.websocket_client.stop()
            self.websocket_client.wait(3000)  # Wait up to 3 seconds
            self.websocket_client = None
        
        self.connection_status_changed.emit(False)
        print("Disconnected from device")
    
    def test_http_connection(self) -> bool:
        """Test HTTP connection to ESP8266"""
        try:
            url = f"http://{self.host}:{self.port}/api/status"
            response = requests.get(url, timeout=self.timeout)
            return response.status_code == 200
        except Exception as e:
            print(f"HTTP connection test failed: {e}")
            return False
    
    def setup_websocket_connection(self):
        """Setup WebSocket connection for real-time communication"""
        if self.websocket_client:
            self.websocket_client.stop()
            self.websocket_client.wait(3000)
        
        self.websocket_client = WebSocketClient(self.host, self.websocket_port)
        
        # Connect WebSocket signals
        self.websocket_client.status_received.connect(self.on_status_received)
        self.websocket_client.pattern_progress.connect(self.on_pattern_progress)
        self.websocket_client.error_received.connect(self.on_websocket_error)
        self.websocket_client.connected.connect(self.on_websocket_connected)
        self.websocket_client.disconnected.connect(self.on_websocket_disconnected)
        
        # Start WebSocket client
        self.websocket_client.start()
    
    def on_status_received(self, status: dict):
        """Handle status updates from ESP8266"""
        self.last_status = status
        
        # Emit response for compatibility with existing code
        status_text = f"Position: {status.get('position', 0)}, "
        status_text += f"Running: {status.get('running', False)}, "
        status_text += f"Speed: {status.get('speed', 0)}"
        
        self.response_received.emit(status_text)
    
    def on_pattern_progress(self, progress: dict):
        """Handle pattern progress updates"""
        current = progress.get('step', 0)
        total = progress.get('total', 1)
        self.progress_updated.emit(current, total)
    
    def on_websocket_error(self, error: str):
        """Handle WebSocket errors"""
        self.error_occurred.emit(f"WebSocket error: {error}")
    
    def on_websocket_connected(self):
        """Handle WebSocket connection"""
        print("WebSocket connected")
    
    def on_websocket_disconnected(self):
        """Handle WebSocket disconnection"""
        print("WebSocket disconnected")
        if self.connected:
            # Try to reconnect
            self.setup_websocket_connection()
    
    def check_connection(self):
        """Check connection health"""
        if not self.connected:
            return
        
        try:
            url = f"http://{self.host}:{self.port}/api/status"
            response = requests.get(url, timeout=3)
            if response.status_code != 200:
                self.handle_connection_lost()
        except Exception:
            self.handle_connection_lost()
    
    def handle_connection_lost(self):
        """Handle lost connection"""
        print("Connection lost to ESP8266")
        self.connected = False
        self.connection_status_changed.emit(False)
        self.error_occurred.emit("Connection lost to knitting machine")
    
    # ========================================
    # API METHODS (Compatible with SerialWorker)
    # ========================================
    
    def send_command(self, command: str) -> bool:
        """
        Send command to ESP8266
        
        This method provides compatibility with the existing SerialWorker interface
        """
        if not self.connected:
            self.error_occurred.emit("Not connected to device")
            return False
        
        try:
            # Parse command and route to appropriate API endpoint
            return self.route_command(command)
            
        except Exception as e:
            self.error_occurred.emit(f"Command failed: {e}")
            return False
    
    def route_command(self, command: str) -> bool:
        """Route legacy serial commands to appropriate API calls"""
        command = command.strip()
        
        if command.startswith("MOVE"):
            return self.handle_move_command(command)
        elif command.startswith("SPEED"):
            return self.handle_speed_command(command)
        elif command.startswith("STOP"):
            return self.handle_stop_command()
        elif command.startswith("HOME"):
            return self.handle_home_command()
        elif command.startswith("STATUS"):
            return self.handle_status_command()
        else:
            # Send as custom command
            return self.send_custom_command(command)
    
    def handle_move_command(self, command: str) -> bool:
        """Handle MOVE command: MOVE 500 CW"""
        try:
            parts = command.split()
            steps = int(parts[1])
            direction = parts[2] if len(parts) > 2 else "CW"
            
            return self.move_motor(steps, direction)
        except Exception as e:
            self.error_occurred.emit(f"Invalid MOVE command: {e}")
            return False
    
    def handle_speed_command(self, command: str) -> bool:
        """Handle SPEED command: SPEED 1000"""
        try:
            parts = command.split()
            speed = int(parts[1])
            
            return self.set_motor_speed(speed)
        except Exception as e:
            self.error_occurred.emit(f"Invalid SPEED command: {e}")
            return False
    
    def handle_stop_command(self) -> bool:
        """Handle STOP command"""
        return self.stop_motor()
    
    def handle_home_command(self) -> bool:
        """Handle HOME command"""
        return self.home_motor()
    
    def handle_status_command(self) -> bool:
        """Handle STATUS command"""
        return self.get_status()
    
    # ========================================
    # HTTP API METHODS
    # ========================================
    
    def move_motor(self, steps: int, direction: str = "CW", speed: Optional[int] = None) -> bool:
        """Move motor with specified parameters"""
        try:
            url = f"http://{self.host}:{self.port}/api/motor/move"
            data = {
                "steps": steps,
                "direction": direction
            }
            if speed:
                data["speed"] = speed
            
            response = requests.post(url, json=data, timeout=self.timeout)
            
            if response.status_code == 200:
                self.response_received.emit(f"Moving {steps} steps {direction}")
                return True
            else:
                self.error_occurred.emit(f"Move failed: {response.text}")
                return False
                
        except Exception as e:
            self.error_occurred.emit(f"Move command failed: {e}")
            return False
    
    def stop_motor(self) -> bool:
        """Stop motor movement"""
        try:
            url = f"http://{self.host}:{self.port}/api/motor/stop"
            response = requests.post(url, timeout=self.timeout)
            
            if response.status_code == 200:
                self.response_received.emit("Motor stopped")
                return True
            else:
                self.error_occurred.emit(f"Stop failed: {response.text}")
                return False
                
        except Exception as e:
            self.error_occurred.emit(f"Stop command failed: {e}")
            return False
    
    def home_motor(self) -> bool:
        """Home the motor"""
        try:
            url = f"http://{self.host}:{self.port}/api/motor/home"
            response = requests.post(url, timeout=self.timeout)
            
            if response.status_code == 200:
                self.response_received.emit("Homing motor")
                return True
            else:
                self.error_occurred.emit(f"Home failed: {response.text}")
                return False
                
        except Exception as e:
            self.error_occurred.emit(f"Home command failed: {e}")
            return False
    
    def set_motor_speed(self, speed: int) -> bool:
        """Set motor speed via configuration update"""
        try:
            url = f"http://{self.host}:{self.port}/api/config"
            data = {"max_speed": speed}
            
            response = requests.post(url, json=data, timeout=self.timeout)
            
            if response.status_code == 200:
                self.response_received.emit(f"Speed set to {speed}")
                return True
            else:
                self.error_occurred.emit(f"Speed setting failed: {response.text}")
                return False
                
        except Exception as e:
            self.error_occurred.emit(f"Speed command failed: {e}")
            return False
    
    def get_status(self) -> bool:
        """Get current machine status"""
        try:
            url = f"http://{self.host}:{self.port}/api/status"
            response = requests.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                status = response.json()
                self.last_status = status
                
                status_text = f"Position: {status.get('position', 0)}, "
                status_text += f"Running: {status.get('running', False)}, "
                status_text += f"Speed: {status.get('speed', 0)}"
                
                self.response_received.emit(status_text)
                return True
            else:
                self.error_occurred.emit(f"Status request failed: {response.text}")
                return False
                
        except Exception as e:
            self.error_occurred.emit(f"Status command failed: {e}")
            return False
    
    def send_custom_command(self, command: str) -> bool:
        """Send custom command (fallback)"""
        # For now, just log the command
        self.response_received.emit(f"Custom command: {command}")
        return True
    
    # ========================================
    # PATTERN METHODS
    # ========================================
    
    def upload_pattern(self, filename: str, pattern_data: dict) -> bool:
        """Upload pattern to ESP8266"""
        try:
            url = f"http://{self.host}:{self.port}/api/pattern/upload"
            
            # Create file-like object from pattern data
            files = {
                'file': (filename, json.dumps(pattern_data, indent=2), 'application/json')
            }
            
            response = requests.post(url, files=files, timeout=self.timeout)
            
            if response.status_code == 200:
                self.response_received.emit(f"Pattern {filename} uploaded successfully")
                return True
            else:
                self.error_occurred.emit(f"Pattern upload failed: {response.text}")
                return False
                
        except Exception as e:
            self.error_occurred.emit(f"Pattern upload failed: {e}")
            return False
    
    def start_pattern(self, filename: str) -> bool:
        """Start pattern execution on ESP8266"""
        try:
            url = f"http://{self.host}:{self.port}/api/pattern/start"
            data = {"filename": filename}
            
            response = requests.post(url, json=data, timeout=self.timeout)
            
            if response.status_code == 200:
                self.pattern_running = True
                self.response_received.emit(f"Started pattern: {filename}")
                return True
            else:
                self.error_occurred.emit(f"Pattern start failed: {response.text}")
                return False
                
        except Exception as e:
            self.error_occurred.emit(f"Pattern start failed: {e}")
            return False
    
    def pause_pattern(self) -> bool:
        """Pause pattern execution"""
        try:
            url = f"http://{self.host}:{self.port}/api/pattern/pause"
            response = requests.post(url, timeout=self.timeout)
            
            if response.status_code == 200:
                self.response_received.emit("Pattern paused")
                return True
            else:
                self.error_occurred.emit(f"Pattern pause failed: {response.text}")
                return False
                
        except Exception as e:
            self.error_occurred.emit(f"Pattern pause failed: {e}")
            return False
    
    def resume_pattern(self) -> bool:
        """Resume pattern execution"""
        try:
            url = f"http://{self.host}:{self.port}/api/pattern/resume"
            response = requests.post(url, timeout=self.timeout)
            
            if response.status_code == 200:
                self.response_received.emit("Pattern resumed")
                return True
            else:
                self.error_occurred.emit(f"Pattern resume failed: {response.text}")
                return False
                
        except Exception as e:
            self.error_occurred.emit(f"Pattern resume failed: {e}")
            return False
    
    def stop_pattern(self) -> bool:
        """Stop pattern execution"""
        try:
            url = f"http://{self.host}:{self.port}/api/pattern/stop"
            response = requests.post(url, timeout=self.timeout)
            
            if response.status_code == 200:
                self.pattern_running = False
                self.response_received.emit("Pattern stopped")
                return True
            else:
                self.error_occurred.emit(f"Pattern stop failed: {response.text}")
                return False
                
        except Exception as e:
            self.error_occurred.emit(f"Pattern stop failed: {e}")
            return False
    
    def get_pattern_list(self) -> Optional[List[Dict]]:
        """Get list of patterns stored on ESP8266"""
        try:
            url = f"http://{self.host}:{self.port}/api/pattern/list"
            response = requests.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('patterns', [])
            else:
                self.error_occurred.emit(f"Pattern list request failed: {response.text}")
                return None
                
        except Exception as e:
            self.error_occurred.emit(f"Pattern list request failed: {e}")
            return None
    
    # ========================================
    # PROPERTIES
    # ========================================
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to device"""
        return self.connected
    
    @property
    def current_status(self) -> Dict[str, Any]:
        """Get current machine status"""
        return self.last_status
    
    @property
    def is_pattern_running(self) -> bool:
        """Check if pattern is currently running"""
        return self.pattern_running
