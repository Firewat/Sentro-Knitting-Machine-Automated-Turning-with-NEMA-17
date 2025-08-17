"""
Communication Module

Provides WiFi-based communication with ESP8266 knitting machines
"""

from .wifi_communicator import WiFiCommunicator, DeviceDiscovery, WebSocketClient

__all__ = ['WiFiCommunicator', 'DeviceDiscovery', 'WebSocketClient']
