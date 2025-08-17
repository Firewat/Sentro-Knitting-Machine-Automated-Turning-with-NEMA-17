#!/usr/bin/env python3
"""
Configuration Management for Sentro Knitting Machine
Centralized settings and constants
"""

import os
from pathlib import Path
from typing import Dict, Any


class AppConfig:
    """Application configuration constants and settings"""
    
    # Application metadata
    APP_NAME = "Sentro Knitting Machine Controller"
    APP_VERSION = "2.0.0"
    APP_AUTHOR = "Lasse Schulz"
    
    # Hardware settings
    DEFAULT_BAUDRATE = 9600
    SERIAL_TIMEOUT = 2.0
    COMMAND_CHUNK_SIZE = 16000
    MAX_RETRIES = 3
    
    # Machine specifications
    DEFAULT_NEEDLE_COUNT = 48
    MAX_NEEDLE_COUNT = 200
    MIN_NEEDLE_COUNT = 1
    
    # Performance settings
    UI_UPDATE_INTERVAL = 50  # milliseconds
    PROGRESS_UPDATE_THRESHOLD = 100  # steps
    
    # File paths
    BASE_DIR = Path(__file__).parent.parent
    PATTERNS_DIR = BASE_DIR / "patterns"
    CONFIG_DIR = BASE_DIR / "config"
    LOGS_DIR = BASE_DIR / "logs"
    
    # Pattern file settings
    PATTERN_FILE_EXTENSION = ".json"
    MAX_PATTERN_NAME_LENGTH = 50
    
    # UI settings
    WINDOW_MIN_WIDTH = 800
    WINDOW_MIN_HEIGHT = 600
    TABLE_ROW_HEIGHT = 30
    TABLE_COLUMN_WIDTH = 60
    
    @classmethod
    def ensure_directories(cls):
        """Ensure all required directories exist"""
        for directory in [cls.PATTERNS_DIR, cls.CONFIG_DIR, cls.LOGS_DIR]:
            directory.mkdir(parents=True, exist_ok=True)


class ThemeConfig:
    """UI Theme configurations"""
    
    THEMES = {
        "Light/Grey": {
            "primary": "#f0f0f0",
            "secondary": "#e0e0e03f", 
            "accent": "#4CAF50",
            "text": "#333333",
            "background": "#ffffff"
        },
        "Dark": {
            "primary": "#2b2b2b",
            "secondary": "#3c3c3c",
            "accent": "#64B5F6", 
            "text": "#ffffff",
            "background": "#1e1e1e"
        },
        "Pink/Rose": {
            "primary": "#f55f91",
            "secondary": "#f8bbd9",
            "accent": "#e91e63",
            "text": "#880e4f", 
            "background": "#fafafa"
        }
    }
    
    DEFAULT_THEME = "Light/Grey"


class SerialConfig:
    """Serial communication configuration"""
    
    COMMON_PORTS = [
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8"
    ]
    
    BAUDRATES = [9600, 19200, 38400, 57600, 115200]
    
    # Command timeouts in seconds
    COMMAND_TIMEOUT = 2.0
    RESPONSE_TIMEOUT = 1.0
    CONNECTION_TIMEOUT = 3.0


# Create directories on import
AppConfig.ensure_directories()
