// ========================================
// CONTINUATION OF knitting_machine_firmware.ino
// ========================================

void handleGetConfig() {
  DynamicJsonDocument doc(512);
  
  doc["max_speed"] = config.maxSpeed;
  doc["acceleration"] = config.acceleration;
  doc["steps_per_rev"] = config.stepsPerRevolution;
  doc["limit_switch"] = config.enableLimitSwitch;
  doc["buzzer"] = config.enableBuzzer;
  doc["device_name"] = config.deviceName;
  doc["websocket_interval"] = config.webSocketInterval;
  
  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}

void handleSetConfig() {
  if (!server.hasArg("plain")) {
    server.send(400, "text/plain", "Missing JSON body");
    return;
  }
  
  DynamicJsonDocument doc(512);
  DeserializationError error = deserializeJson(doc, server.arg("plain"));
  
  if (error) {
    server.send(400, "text/plain", "Invalid JSON");
    return;
  }
  
  // Update configuration
  if (doc.containsKey("max_speed")) config.maxSpeed = doc["max_speed"];
  if (doc.containsKey("acceleration")) config.acceleration = doc["acceleration"];
  if (doc.containsKey("steps_per_rev")) config.stepsPerRevolution = doc["steps_per_rev"];
  if (doc.containsKey("limit_switch")) config.enableLimitSwitch = doc["limit_switch"];
  if (doc.containsKey("buzzer")) config.enableBuzzer = doc["buzzer"];
  if (doc.containsKey("device_name")) config.deviceName = doc["device_name"].as<String>();
  if (doc.containsKey("websocket_interval")) config.webSocketInterval = doc["websocket_interval"];
  
  // Apply motor settings
  stepper.setMaxSpeed(config.maxSpeed);
  stepper.setAcceleration(config.acceleration);
  
  // Save configuration
  saveConfiguration();
  
  server.send(200, "text/plain", "Configuration updated");
  broadcastConfigUpdate();
}

void handleMotorMove() {
  if (!server.hasArg("plain")) {
    server.send(400, "text/plain", "Missing JSON body");
    return;
  }
  
  DynamicJsonDocument doc(256);
  DeserializationError error = deserializeJson(doc, server.arg("plain"));
  
  if (error) {
    server.send(400, "text/plain", "Invalid JSON");
    return;
  }
  
  if (!doc.containsKey("steps")) {
    server.send(400, "text/plain", "Missing 'steps' parameter");
    return;
  }
  
  long steps = doc["steps"];
  String direction = doc["direction"] | "CW";
  int speed = doc["speed"] | config.maxSpeed;
  
  // Validate parameters
  if (abs(steps) > 100000) {
    server.send(400, "text/plain", "Steps out of range");
    return;
  }
  
  // Apply direction
  if (direction == "CCW") {
    steps = -abs(steps);
  } else {
    steps = abs(steps);
  }
  
  // Set speed if provided
  if (speed != config.maxSpeed) {
    stepper.setMaxSpeed(speed);
    machineState.currentSpeed = speed;
  }
  
  // Execute move
  moveMotor(steps);
  
  DynamicJsonDocument response(128);
  response["status"] = "moving";
  response["steps"] = steps;
  response["direction"] = direction;
  response["speed"] = speed;
  
  String responseStr;
  serializeJson(response, responseStr);
  server.send(200, "application/json", responseStr);
}

void handleMotorStop() {
  stopMotor();
  server.send(200, "text/plain", "Motor stopped");
}

void handleMotorHome() {
  homeMotor();
  server.send(200, "text/plain", "Homing motor");
}

void handleMotorEnable() {
  stepper.enableOutputs();
  server.send(200, "text/plain", "Motor enabled");
  broadcastStatus();
}

void handleMotorDisable() {
  stepper.disableOutputs();
  server.send(200, "text/plain", "Motor disabled");
  broadcastStatus();
}

void handlePatternUpload() {
  HTTPUpload& upload = server.upload();
  static File uploadFile;
  
  if (upload.status == UPLOAD_FILE_START) {
    String filename = String(PATTERNS_DIR) + upload.filename;
    Serial.printf("Upload start: %s\n", filename.c_str());
    
    uploadFile = LittleFS.open(filename, "w");
    if (!uploadFile) {
      Serial.println("Failed to open file for writing");
      return;
    }
  } else if (upload.status == UPLOAD_FILE_WRITE) {
    if (uploadFile) {
      uploadFile.write(upload.buf, upload.currentSize);
    }
  } else if (upload.status == UPLOAD_FILE_END) {
    if (uploadFile) {
      uploadFile.close();
      Serial.printf("Upload end: %s, size: %u\n", upload.filename.c_str(), upload.totalSize);
      
      // Validate uploaded pattern
      if (validatePattern(String(PATTERNS_DIR) + upload.filename)) {
        server.send(200, "text/plain", "Pattern uploaded successfully");
      } else {
        LittleFS.remove(String(PATTERNS_DIR) + upload.filename);
        server.send(400, "text/plain", "Invalid pattern file");
      }
    }
  }
}

void handlePatternList() {
  DynamicJsonDocument doc(1024);
  JsonArray patterns = doc.createNestedArray("patterns");
  
  Dir dir = LittleFS.openDir(PATTERNS_DIR);
  while (dir.next()) {
    JsonObject pattern = patterns.createNestedObject();
    pattern["filename"] = dir.fileName();
    pattern["size"] = dir.fileSize();
    
    // Try to read pattern metadata
    File file = LittleFS.open(String(PATTERNS_DIR) + dir.fileName(), "r");
    if (file) {
      DynamicJsonDocument patternDoc(512);
      DeserializationError error = deserializeJson(patternDoc, file);
      if (!error) {
        if (patternDoc.containsKey("name")) {
          pattern["name"] = patternDoc["name"];
        }
        if (patternDoc.containsKey("description")) {
          pattern["description"] = patternDoc["description"];
        }
        if (patternDoc.containsKey("steps")) {
          pattern["total_steps"] = patternDoc["steps"].size();
        }
      }
      file.close();
    }
  }
  
  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}

void handlePatternStart() {
  if (!server.hasArg("plain")) {
    server.send(400, "text/plain", "Missing JSON body");
    return;
  }
  
  DynamicJsonDocument doc(256);
  DeserializationError error = deserializeJson(doc, server.arg("plain"));
  
  if (error || !doc.containsKey("filename")) {
    server.send(400, "text/plain", "Invalid JSON or missing filename");
    return;
  }
  
  String filename = doc["filename"];
  if (startPattern(filename)) {
    server.send(200, "text/plain", "Pattern started");
  } else {
    server.send(400, "text/plain", "Failed to start pattern");
  }
}

void handlePatternPause() {
  pausePattern();
  server.send(200, "text/plain", "Pattern paused");
}

void handlePatternResume() {
  resumePattern();
  server.send(200, "text/plain", "Pattern resumed");
}

void handlePatternStop() {
  stopPattern();
  server.send(200, "text/plain", "Pattern stopped");
}

void handleSystemRestart() {
  server.send(200, "text/plain", "Restarting system...");
  delay(1000);
  ESP.restart();
}

void handleSystemReset() {
  server.send(200, "text/plain", "Resetting to factory defaults...");
  LittleFS.format();
  delay(1000);
  ESP.restart();
}

void handleNotFound() {
  String message = "File Not Found\n\n";
  message += "URI: " + server.uri() + "\n";
  message += "Method: " + (server.method() == HTTP_GET ? "GET" : "POST") + "\n";
  message += "Arguments: " + String(server.args()) + "\n";
  
  for (uint8_t i = 0; i < server.args(); i++) {
    message += " " + server.argName(i) + ": " + server.arg(i) + "\n";
  }
  
  server.send(404, "text/plain", message);
}

// ========================================
// WEBSOCKET HANDLERS
// ========================================
void webSocketEvent(uint8_t num, WStype_t type, uint8_t * payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      Serial.printf("[%u] Disconnected!\n", num);
      machineState.connectedClients--;
      break;
      
    case WStype_CONNECTED: {
      IPAddress ip = webSocket.remoteIP(num);
      Serial.printf("[%u] Connected from %d.%d.%d.%d\n", num, ip[0], ip[1], ip[2], ip[3]);
      machineState.connectedClients++;
      
      // Send current status to new client
      sendStatusToClient(num);
      break;
    }
    
    case WStype_TEXT: {
      Serial.printf("[%u] Received: %s\n", num, payload);
      handleWebSocketMessage(num, (char*)payload);
      break;
    }
    
    case WStype_BIN:
      Serial.printf("[%u] Received binary length: %u\n", num, length);
      break;
      
    case WStype_PING:
      machineState.lastHeartbeat = millis();
      break;
      
    case WStype_PONG:
      machineState.lastHeartbeat = millis();
      break;
      
    default:
      break;
  }
}

void handleWebSocketMessage(uint8_t clientNum, const char* message) {
  DynamicJsonDocument doc(512);
  DeserializationError error = deserializeJson(doc, message);
  
  if (error) {
    sendErrorToClient(clientNum, "Invalid JSON");
    return;
  }
  
  String type = doc["type"];
  machineState.lastHeartbeat = millis();
  
  if (type == "ping") {
    sendPongToClient(clientNum);
  }
  else if (type == "motor_move") {
    long steps = doc["steps"] | 0;
    String direction = doc["direction"] | "CW";
    int speed = doc["speed"] | config.maxSpeed;
    
    if (direction == "CCW") steps = -abs(steps);
    else steps = abs(steps);
    
    stepper.setMaxSpeed(speed);
    moveMotor(steps);
  }
  else if (type == "motor_stop") {
    stopMotor();
  }
  else if (type == "pattern_start") {
    String filename = doc["filename"];
    startPattern(filename);
  }
  else if (type == "pattern_pause") {
    pausePattern();
  }
  else if (type == "pattern_resume") {
    resumePattern();
  }
  else if (type == "pattern_stop") {
    stopPattern();
  }
  else if (type == "emergency_stop") {
    emergencyStop();
  }
  else {
    sendErrorToClient(clientNum, "Unknown command type");
  }
}

// ========================================
// WEBSOCKET UTILITIES
// ========================================
void broadcastStatus() {
  DynamicJsonDocument doc(512);
  
  doc["type"] = "status";
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
  doc["timestamp"] = millis();
  
  String message;
  serializeJson(doc, message);
  webSocket.broadcastTXT(message);
}

void sendStatusToClient(uint8_t clientNum) {
  DynamicJsonDocument doc(512);
  
  doc["type"] = "status";
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
  doc["uptime"] = millis();
  doc["free_heap"] = ESP.getFreeHeap();
  
  String message;
  serializeJson(doc, message);
  webSocket.sendTXT(clientNum, message);
}

void sendErrorToClient(uint8_t clientNum, const String& error) {
  DynamicJsonDocument doc(128);
  doc["type"] = "error";
  doc["message"] = error;
  
  String message;
  serializeJson(doc, message);
  webSocket.sendTXT(clientNum, message);
}

void sendPongToClient(uint8_t clientNum) {
  DynamicJsonDocument doc(64);
  doc["type"] = "pong";
  doc["timestamp"] = millis();
  
  String message;
  serializeJson(doc, message);
  webSocket.sendTXT(clientNum, message);
}

void broadcastConfigUpdate() {
  DynamicJsonDocument doc(256);
  doc["type"] = "config_update";
  doc["max_speed"] = config.maxSpeed;
  doc["acceleration"] = config.acceleration;
  
  String message;
  serializeJson(doc, message);
  webSocket.broadcastTXT(message);
}

void broadcastPatternProgress() {
  if (machineState.totalSteps > 0) {
    DynamicJsonDocument doc(128);
    doc["type"] = "pattern_progress";
    doc["step"] = machineState.patternStep;
    doc["total"] = machineState.totalSteps;
    doc["percent"] = (machineState.patternStep * 100) / machineState.totalSteps;
    
    String message;
    serializeJson(doc, message);
    webSocket.broadcastTXT(message);
  }
}

// ========================================
// MOTOR CONTROL FUNCTIONS
// ========================================
void moveMotor(long steps) {
  stepper.move(steps);
  machineState.targetPosition = stepper.targetPosition();
  Serial.printf("Moving motor: %ld steps to position %ld\n", steps, machineState.targetPosition);
}

void stopMotor() {
  stepper.stop();
  Serial.println("Motor stopped");
  broadcastStatus();
}

void emergencyStop() {
  stepper.stop();
  stepper.disableOutputs();
  machineState.isRunning = false;
  machineState.isPaused = false;
  machineState.lastError = "Emergency stop activated";
  
  Serial.println("EMERGENCY STOP!");
  
  // Alert sound if buzzer enabled
  if (config.enableBuzzer) {
    for (int i = 0; i < 3; i++) {
      digitalWrite(BUZZER_PIN, HIGH);
      delay(200);
      digitalWrite(BUZZER_PIN, LOW);
      delay(200);
    }
  }
  
  broadcastStatus();
}

void homeMotor() {
  if (config.enableLimitSwitch) {
    // Move towards limit switch
    stepper.setMaxSpeed(config.maxSpeed / 4); // Slow speed for homing
    
    while (digitalRead(LIMIT_PIN) == HIGH) {
      stepper.move(-100);
      while (stepper.distanceToGo() != 0) {
        stepper.run();
        delay(1);
      }
    }
    
    // Back off limit switch
    stepper.move(50);
    while (stepper.distanceToGo() != 0) {
      stepper.run();
      delay(1);
    }
    
    // Set home position
    stepper.setCurrentPosition(0);
    machineState.currentPosition = 0;
    machineState.isHomed = true;
    
    // Restore normal speed
    stepper.setMaxSpeed(config.maxSpeed);
    
    Serial.println("Motor homed");
  } else {
    // Manual homing - just set current position as home
    stepper.setCurrentPosition(0);
    machineState.currentPosition = 0;
    machineState.isHomed = true;
    Serial.println("Home position set manually");
  }
  
  broadcastStatus();
}

void onMoveComplete() {
  machineState.currentPosition = stepper.currentPosition();
  Serial.printf("Move complete - Position: %ld\n", machineState.currentPosition);
  
  // Continue pattern execution if running
  if (machineState.isRunning && !machineState.isPaused) {
    machineState.patternStep++;
    broadcastPatternProgress();
  }
  
  broadcastStatus();
}

// ========================================
// PATTERN EXECUTION
// ========================================
bool startPattern(const String& filename) {
  String filepath = String(PATTERNS_DIR) + filename;
  
  if (!LittleFS.exists(filepath)) {
    machineState.lastError = "Pattern file not found: " + filename;
    return false;
  }
  
  // Load pattern
  File file = LittleFS.open(filepath, "r");
  if (!file) {
    machineState.lastError = "Cannot open pattern file: " + filename;
    return false;
  }
  
  DynamicJsonDocument doc(2048);
  DeserializationError error = deserializeJson(doc, file);
  file.close();
  
  if (error) {
    machineState.lastError = "Invalid pattern JSON: " + filename;
    return false;
  }
  
  // Parse pattern commands
  currentPatternCommands.clear();
  JsonArray steps = doc["steps"];
  
  for (JsonObject step : steps) {
    PatternCommand cmd;
    cmd.type = step["type"] | "move";
    cmd.value = step["value"] | 0;
    cmd.direction = step["direction"] | "CW";
    cmd.description = step["description"] | "";
    
    currentPatternCommands.push_back(cmd);
  }
  
  // Start execution
  machineState.currentPattern = filename;
  machineState.patternStep = 0;
  machineState.totalSteps = currentPatternCommands.size();
  machineState.isRunning = true;
  machineState.isPaused = false;
  machineState.lastError = "";
  
  Serial.printf("Started pattern: %s (%d steps)\n", filename.c_str(), machineState.totalSteps);
  broadcastStatus();
  return true;
}

void executePatternStep() {
  if (machineState.patternStep >= currentPatternCommands.size()) {
    // Pattern complete
    stopPattern();
    return;
  }
  
  // Only execute if motor is not moving
  if (stepper.distanceToGo() != 0) {
    return;
  }
  
  PatternCommand& cmd = currentPatternCommands[machineState.patternStep];
  
  if (cmd.type == "move") {
    long steps = cmd.value;
    if (cmd.direction == "CCW") {
      steps = -abs(steps);
    } else {
      steps = abs(steps);
    }
    
    Serial.printf("Executing pattern step %d: Move %ld steps %s\n", 
                  machineState.patternStep, abs(steps), cmd.direction.c_str());
    moveMotor(steps);
  }
  else if (cmd.type == "pause") {
    Serial.printf("Executing pattern step %d: Pause %ld ms\n", 
                  machineState.patternStep, cmd.value);
    delay(cmd.value);
    machineState.patternStep++;
  }
  else if (cmd.type == "speed") {
    Serial.printf("Executing pattern step %d: Set speed %ld\n", 
                  machineState.patternStep, cmd.value);
    stepper.setMaxSpeed(cmd.value);
    machineState.currentSpeed = cmd.value;
    machineState.patternStep++;
  }
}

void pausePattern() {
  if (machineState.isRunning) {
    machineState.isPaused = true;
    Serial.println("Pattern paused");
    broadcastStatus();
  }
}

void resumePattern() {
  if (machineState.isRunning && machineState.isPaused) {
    machineState.isPaused = false;
    Serial.println("Pattern resumed");
    broadcastStatus();
  }
}

void stopPattern() {
  machineState.isRunning = false;
  machineState.isPaused = false;
  machineState.currentPattern = "";
  machineState.patternStep = 0;
  machineState.totalSteps = 0;
  currentPatternCommands.clear();
  
  stopMotor();
  Serial.println("Pattern stopped");
  broadcastStatus();
}

// ========================================
// CONFIGURATION MANAGEMENT
// ========================================
void loadConfiguration() {
  if (!LittleFS.exists(CONFIG_FILE)) {
    Serial.println("Config file not found, using defaults");
    saveConfiguration(); // Create default config
    return;
  }
  
  File file = LittleFS.open(CONFIG_FILE, "r");
  if (!file) {
    Serial.println("Failed to open config file");
    return;
  }
  
  DynamicJsonDocument doc(512);
  DeserializationError error = deserializeJson(doc, file);
  file.close();
  
  if (error) {
    Serial.println("Failed to parse config file");
    return;
  }
  
  // Load configuration values
  config.maxSpeed = doc["max_speed"] | 1500;
  config.acceleration = doc["acceleration"] | 800;
  config.stepsPerRevolution = doc["steps_per_rev"] | (200 * 16);
  config.enableLimitSwitch = doc["limit_switch"] | false;
  config.enableBuzzer = doc["buzzer"] | false;
  config.deviceName = doc["device_name"] | "Knitting Machine";
  config.webSocketInterval = doc["websocket_interval"] | 100;
  
  Serial.println("Configuration loaded");
}

void saveConfiguration() {
  File file = LittleFS.open(CONFIG_FILE, "w");
  if (!file) {
    Serial.println("Failed to create config file");
    return;
  }
  
  DynamicJsonDocument doc(512);
  doc["max_speed"] = config.maxSpeed;
  doc["acceleration"] = config.acceleration;
  doc["steps_per_rev"] = config.stepsPerRevolution;
  doc["limit_switch"] = config.enableLimitSwitch;
  doc["buzzer"] = config.enableBuzzer;
  doc["device_name"] = config.deviceName;
  doc["websocket_interval"] = config.webSocketInterval;
  
  if (serializeJson(doc, file) == 0) {
    Serial.println("Failed to write config file");
  } else {
    Serial.println("Configuration saved");
  }
  
  file.close();
}

// ========================================
// UTILITY FUNCTIONS
// ========================================
bool validatePattern(const String& filepath) {
  File file = LittleFS.open(filepath, "r");
  if (!file) return false;
  
  DynamicJsonDocument doc(1024);
  DeserializationError error = deserializeJson(doc, file);
  file.close();
  
  if (error) return false;
  
  // Basic validation
  if (!doc.containsKey("steps")) return false;
  
  JsonArray steps = doc["steps"];
  if (steps.size() == 0) return false;
  
  // Validate each step
  for (JsonObject step : steps) {
    String type = step["type"] | "";
    if (type != "move" && type != "pause" && type != "speed") {
      return false;
    }
    
    if (!step.containsKey("value")) return false;
  }
  
  return true;
}

void blinkStatusLED(int times, int delayMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(STATUS_LED, HIGH);
    delay(delayMs);
    digitalWrite(STATUS_LED, LOW);
    delay(delayMs);
  }
}

void indicateError() {
  // Fast blinking for error indication
  for (int i = 0; i < 10; i++) {
    digitalWrite(STATUS_LED, HIGH);
    delay(100);
    digitalWrite(STATUS_LED, LOW);
    delay(100);
  }
}

void handleLimitSwitch() {
  emergencyStop();
  machineState.lastError = "Limit switch triggered";
  Serial.println("Limit switch triggered!");
}

void handleError() {
  Serial.printf("Error: %s\n", machineState.lastError.c_str());
  
  // Broadcast error
  DynamicJsonDocument doc(128);
  doc["type"] = "error";
  doc["message"] = machineState.lastError;
  
  String message;
  serializeJson(doc, message);
  webSocket.broadcastTXT(message);
  
  // Clear error after broadcasting
  machineState.lastError = "";
}

void handleClientDisconnect() {
  // If no clients connected and machine is running, pause for safety
  if (machineState.connectedClients == 0 && machineState.isRunning) {
    Serial.println("No clients connected, pausing for safety");
    pausePattern();
  }
}
