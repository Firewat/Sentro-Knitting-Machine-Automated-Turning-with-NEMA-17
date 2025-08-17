#!/usr/bin/env python3
"""
Sentro Knitting Machine Controller - Main Entry Point
Professional, modular knitting machine control application
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import main application
from src.ui.main_window import main

if __name__ == "__main__":
    main()
