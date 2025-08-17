/**
 * Sentro Knitting Machine ESP8266 Firmware
 * 
 * Professional-grade firmware for NodeMCU Lolin V3
 * Features:
 * - RESTful API for machine control
 * - WebSocket for real-time monitoring
 * - Pattern file upload and storage
 * - Offline pattern execution
 * - Multi-client connection support
 * - OTA update capability
 * - Robust error handling and recovery
 * 
 * Hardware:
 * - NodeMCU Lolin V3 (ESP8266)
 * - Stepper motor with driver
 * - Optional limit switches and sensors
 */

#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <WebSocketsServer.h>
#include <ESP8266mDNS.h>
#include <ArduinoJson.h>
#include <LittleFS.h>
#include <AccelStepper.h>
#include <WiFiManager.h>

// ========================================
// HARDWARE CONFIGURATION
// ========================================
#define STEP_PIN      4   // D2 - Step pulse pin
#define DIR_PIN       5   // D1 - Direction pin  
#define ENABLE_PIN    12  // D6 - Enable pin (active LOW)
#define LIMIT_PIN     13  // D7 - Limit switch (optional)
#define STATUS_LED    14  // D5 - Status LED
#define BUZZER_PIN    15  // D8 - Buzzer (optional)

// Motor configuration
#define MAX_SPEED     2000    // Maximum steps/second
#define MAX_ACCEL     1000    // Steps/second²
#define STEPS_PER_REV 200     // Motor steps per revolution
#define MICROSTEPS    16      // Driver microstep setting

// Network configuration
#define AP_NAME       "KnittingMachine"
#define AP_PASSWORD   "knitting123"
#define HOSTNAME      "knitting-machine"
#define WEB_PORT      80
#define WEBSOCKET_PORT 81

// File system paths
#define CONFIG_FILE   "/config.json"
#define PATTERNS_DIR  "/patterns/"
#define LOGS_DIR      "/logs/"

// ========================================
// GLOBAL OBJECTS
// ========================================
ESP8266WebServer server(WEB_PORT);
WebSocketsServer webSocket = WebSocketsServer(WEBSOCKET_PORT);
AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);

// ========================================
// STATE MANAGEMENT
// ========================================
struct MachineState {
  bool isConnected = false;
  bool isRunning = false;
  bool isPaused = false;
  bool isHomed = false;
  long currentPosition = 0;
  long targetPosition = 0;
  int currentSpeed = 500;
  String currentPattern = "";
  int patternStep = 0;
  int totalSteps = 0;
  String lastError = "";
  unsigned long lastHeartbeat = 0;
  int connectedClients = 0;
} machineState;

struct Configuration {
  int maxSpeed = 1500;
  int acceleration = 800;
  int stepsPerRevolution = 200 * MICROSTEPS;
  bool enableLimitSwitch = false;
  bool enableBuzzer = false;
  String deviceName = "Knitting Machine";
  int webSocketInterval = 100;  // Status update interval (ms)
} config;

// Pattern execution
struct PatternCommand {
  String type;        // "move", "pause", "speed", "direction"
  long value;         // Steps, speed, pause time
  String direction;   // "CW", "CCW"
  String description; // Human readable
};

std::vector<PatternCommand> currentPatternCommands;
unsigned long lastStatusUpdate = 0;
unsigned long lastHeartbeat = 0;

// ========================================
// SETUP FUNCTION
// ========================================
void setup() {
  Serial.begin(115200);
  Serial.println("\n=== Sentro Knitting Machine ESP8266 ===");
  Serial.println("Version: 1.0.0");
  
  // Initialize hardware
  initializeHardware();
  
  // Initialize file system
  if (!initializeFileSystem()) {
    Serial.println("ERROR: File system initialization failed!");
    indicateError();
    return;
  }
  
  // Load configuration
  loadConfiguration();
  
  // Initialize WiFi
  if (!initializeWiFi()) {
    Serial.println("ERROR: WiFi initialization failed!");
    indicateError();
    return;
  }
  
  // Initialize web services
  initializeWebServer();
  initializeWebSocket();
  
  // Initialize mDNS for auto-discovery
  if (MDNS.begin(HOSTNAME)) {
    MDNS.addService("http", "tcp", WEB_PORT);
    MDNS.addService("ws", "tcp", WEBSOCKET_PORT);
    Serial.printf("mDNS responder started: %s.local\n", HOSTNAME);
  }
  
  // Final setup
  stepper.setMaxSpeed(config.maxSpeed);
  stepper.setAcceleration(config.acceleration);
  stepper.setEnablePin(ENABLE_PIN);
  stepper.setPinsInverted(false, false, true); // Enable pin is active LOW
  stepper.enableOutputs();
  
  Serial.println("=== Setup Complete ===");
  Serial.printf("Web Server: http://%s.local:%d\n", HOSTNAME, WEB_PORT);
  Serial.printf("WebSocket: ws://%s.local:%d\n", HOSTNAME, WEBSOCKET_PORT);
  Serial.printf("IP Address: %s\n", WiFi.localIP().toString().c_str());
  
  // Indicate ready
  blinkStatusLED(3, 200);
  machineState.isConnected = true;
  machineState.lastHeartbeat = millis();
}

// ========================================
// MAIN LOOP
// ========================================
void loop() {
  // Handle web services
  server.handleClient();
  webSocket.loop();
  MDNS.update();
  
  // Handle motor movement
  if (stepper.distanceToGo() != 0) {
    stepper.run();
    machineState.currentPosition = stepper.currentPosition();
    
    // Check if move completed
    if (stepper.distanceToGo() == 0) {
      onMoveComplete();
    }
  }
  
  // Execute pattern if running
  if (machineState.isRunning && !machineState.isPaused) {
    executePatternStep();
  }
  
  // Send periodic status updates
  if (millis() - lastStatusUpdate > config.webSocketInterval) {
    broadcastStatus();
    lastStatusUpdate = millis();
  }
  
  // Check for disconnected clients
  if (millis() - machineState.lastHeartbeat > 30000) { // 30 second timeout
    handleClientDisconnect();
  }
  
  // Check limit switch
  if (config.enableLimitSwitch && digitalRead(LIMIT_PIN) == LOW) {
    handleLimitSwitch();
  }
  
  // Handle any errors
  if (!machineState.lastError.isEmpty()) {
    handleError();
  }
  
  delay(1); // Small delay for stability
}

// ========================================
// HARDWARE INITIALIZATION
// ========================================
void initializeHardware() {
  // Configure pins
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(ENABLE_PIN, OUTPUT);
  pinMode(STATUS_LED, OUTPUT);
  
  if (config.enableLimitSwitch) {
    pinMode(LIMIT_PIN, INPUT_PULLUP);
  }
  
  if (config.enableBuzzer) {
    pinMode(BUZZER_PIN, OUTPUT);
  }
  
  // Initial states
  digitalWrite(ENABLE_PIN, HIGH);  // Disable motor initially
  digitalWrite(STATUS_LED, LOW);
  
  Serial.println("Hardware initialized");
}

bool initializeFileSystem() {
  if (!LittleFS.begin()) {
    Serial.println("LittleFS mount failed, formatting...");
    if (!LittleFS.format()) {
      return false;
    }
    if (!LittleFS.begin()) {
      return false;
    }
  }
  
  // Create directory structure
  if (!LittleFS.exists(PATTERNS_DIR)) {
    LittleFS.mkdir(PATTERNS_DIR);
  }
  if (!LittleFS.exists(LOGS_DIR)) {
    LittleFS.mkdir(LOGS_DIR);
  }
  
  Serial.println("File system initialized");
  return true;
}

bool initializeWiFi() {
  WiFiManager wifiManager;
  
  // Set custom AP name and password
  wifiManager.setAPStaticIPConfig(IPAddress(192,168,4,1), IPAddress(192,168,4,1), IPAddress(255,255,255,0));
  
  // Try to connect to saved WiFi or create AP
  if (!wifiManager.autoConnect(AP_NAME, AP_PASSWORD)) {
    Serial.println("Failed to connect WiFi, restarting...");
    ESP.restart();
    return false;
  }
  
  Serial.printf("WiFi connected! IP: %s\n", WiFi.localIP().toString().c_str());
  return true;
}

// ========================================
// WEB SERVER SETUP
// ========================================
void initializeWebServer() {
  // Enable CORS for all origins
  server.enableCORS(true);
  
  // Serve static files
  server.serveStatic("/", LittleFS, "/www/");
  
  // API Routes
  server.on("/api/status", HTTP_GET, handleGetStatus);
  server.on("/api/config", HTTP_GET, handleGetConfig);
  server.on("/api/config", HTTP_POST, handleSetConfig);
  
  // Motor control
  server.on("/api/motor/move", HTTP_POST, handleMotorMove);
  server.on("/api/motor/stop", HTTP_POST, handleMotorStop);
  server.on("/api/motor/home", HTTP_POST, handleMotorHome);
  server.on("/api/motor/enable", HTTP_POST, handleMotorEnable);
  server.on("/api/motor/disable", HTTP_POST, handleMotorDisable);
  
  // Pattern management
  server.on("/api/pattern/upload", HTTP_POST, [](){
    server.send(200, "text/plain", "");
  }, handlePatternUpload);
  server.on("/api/pattern/list", HTTP_GET, handlePatternList);
  server.on("/api/pattern/start", HTTP_POST, handlePatternStart);
  server.on("/api/pattern/pause", HTTP_POST, handlePatternPause);
  server.on("/api/pattern/resume", HTTP_POST, handlePatternResume);
  server.on("/api/pattern/stop", HTTP_POST, handlePatternStop);
  
  // System
  server.on("/api/system/restart", HTTP_POST, handleSystemRestart);
  server.on("/api/system/reset", HTTP_POST, handleSystemReset);
  
  // 404 handler
  server.onNotFound(handleNotFound);
  
  server.begin();
  Serial.printf("Web server started on port %d\n", WEB_PORT);
}

void initializeWebSocket() {
  webSocket.begin();
  webSocket.onEvent(webSocketEvent);
  Serial.printf("WebSocket server started on port %d\n", WEBSOCKET_PORT);
}

// ========================================
// WEB SERVER HANDLERS
// ========================================
void handleGetStatus() {
  DynamicJsonDocument doc(1024);
  
  doc["connected"] = machineState.isConnected;
  doc["running"] = machineState.isRunning;
  doc["paused"] = machineState.isPaused;
  doc["homed"] = machineState.isHomed;
  doc["position"] = machineState.currentPosition;
  doc["target"] = machineState.targetPosition;
  doc["speed"] = machineState.currentSpeed;
  doc["pattern"] = machineState.currentPattern;
  doc["pattern_step"] = machineState.patternStep;
  doc["total_steps"] = machineState.totalSteps;
  doc["error"] = machineState.lastError;
  doc["uptime"] = millis();
  doc["free_heap"] = ESP.getFreeHeap();
  doc["clients"] = machineState.connectedClients;
  
  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}

// ... [Continuing with more handlers in next message due to length limit]
