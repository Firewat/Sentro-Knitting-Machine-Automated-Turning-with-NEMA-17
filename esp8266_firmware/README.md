# ESP8266 Knitting Machine Firmware

## Setup Instructions

### Arduino IDE Setup
1. Install Arduino IDE 2.0+
2. Add ESP8266 Board Manager URL:
   - File → Preferences → Additional Boards Manager URLs
   - Add: `https://arduino.esp8266.com/stable/package_esp8266com_index.json`
3. Install ESP8266 Board Package:
   - Tools → Board → Boards Manager
   - Search "ESP8266" and install

### Required Libraries
```
ESP8266WiFi - Built-in
ESP8266WebServer - Built-in
WebSocketsServer - Install via Library Manager
ArduinoJson - Install via Library Manager
AccelStepper - Install via Library Manager
LittleFS - Built-in
ESP8266mDNS - Built-in
```

### NodeMCU Lolin V3 Pinout
```
GPIO 4  (D2) - Step Pin
GPIO 5  (D1) - Direction Pin  
GPIO 12 (D6) - Enable Pin
GPIO 13 (D7) - Limit Switch (Optional)
GPIO 14 (D5) - LED Status
```

### Network Configuration
- Default Access Point: "KnittingMachine-XXXX"
- Default Password: "knitting123"
- Web Interface: http://192.168.4.1
- WebSocket: ws://192.168.4.1:81

## Architecture

### Communication Protocols
- **REST API**: Configuration, file operations, commands
- **WebSocket**: Real-time status, monitoring, control
- **mDNS**: Auto-discovery as "knitting-machine.local"

### File System Structure
```
/patterns/          - Uploaded pattern files
/config.json        - Machine configuration
/status.json        - Current status
/logs/              - Operation logs
```

### API Endpoints
```
GET  /api/status           - Current machine status
POST /api/motor/move       - Move motor steps
POST /api/motor/stop       - Emergency stop
POST /api/pattern/upload   - Upload pattern file
GET  /api/pattern/list     - List stored patterns
POST /api/pattern/start    - Start pattern execution
GET  /api/config           - Get configuration
POST /api/config           - Update configuration
```

### WebSocket Messages
```javascript
// Status Updates (ESP → Client)
{"type": "status", "position": 1250, "speed": 500, "state": "running"}
{"type": "pattern_progress", "step": 5, "total": 20, "percent": 25}
{"type": "error", "message": "Limit switch triggered"}

// Commands (Client → ESP)
{"type": "motor_move", "steps": 100, "direction": "CW"}
{"type": "emergency_stop"}
{"type": "pattern_start", "filename": "scarf.json"}
```

## Development Phases

### Phase 1: Core Functionality ✅
- [x] Web server setup
- [x] Basic motor control
- [x] WebSocket communication
- [x] Status monitoring

### Phase 2: Advanced Features
- [ ] Pattern file upload
- [ ] Offline execution
- [ ] Multi-client support
- [ ] Configuration management

### Phase 3: Production Features
- [ ] OTA updates
- [ ] Error recovery
- [ ] Logging system
- [ ] Performance optimization
