#!/usr/bin/env python3
"""
Pattern Management System
Clean, optimized pattern handling with proper data models
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import json
from pathlib import Path


@dataclass
class PatternStep:
    """Immutable pattern step with validation"""
    needles: int
    direction: str
    rows: int = 1
    description: str = ""
    
    def __post_init__(self):
        """Validate data after initialization"""
        if self.needles < 1:
            raise ValueError("Needles must be positive")
        if self.direction not in ["CW", "CCW"]:
            raise ValueError("Direction must be 'CW' or 'CCW'")
        if self.rows < 1:
            raise ValueError("Rows must be positive")
        if not self.description:
            self.description = f"{self.needles} needles × {self.rows} rows {self.direction}"
    
    @property
    def total_needles(self) -> int:
        """Calculate total needles for this step"""
        return self.needles * self.rows
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "needles": self.needles,
            "direction": self.direction,
            "rows": self.rows,
            "description": self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PatternStep':
        """Create from dictionary with backward compatibility"""
        rows = data.get("rows", data.get("repeat_count", 1))
        return cls(
            needles=data["needles"],
            direction=data["direction"],
            rows=rows,
            description=data.get("description", "")
        )


@dataclass 
class KnittingPattern:
    """Immutable knitting pattern with validation"""
    name: str
    steps: List[PatternStep]
    description: str = ""
    repetitions: int = 1
    
    def __post_init__(self):
        """Validate pattern after initialization"""
        if not self.name or len(self.name) > 50:
            raise ValueError("Pattern name must be 1-50 characters")
        if self.repetitions < 1:
            raise ValueError("Repetitions must be positive")
        if not isinstance(self.steps, list):
            raise ValueError("Steps must be a list")
    
    @property
    def total_needles(self) -> int:
        """Calculate total needles for entire pattern"""
        base_total = sum(step.total_needles for step in self.steps)
        return base_total * self.repetitions
    
    @property
    def step_count(self) -> int:
        """Get number of steps in pattern"""
        return len(self.steps)
    
    def add_step(self, step: PatternStep) -> 'KnittingPattern':
        """Return new pattern with added step (immutable)"""
        new_steps = self.steps + [step]
        return KnittingPattern(
            name=self.name,
            steps=new_steps,
            description=self.description,
            repetitions=self.repetitions
        )
    
    def remove_step(self, index: int) -> 'KnittingPattern':
        """Return new pattern with removed step (immutable)"""
        if not (0 <= index < len(self.steps)):
            raise IndexError("Step index out of range")
        new_steps = self.steps[:index] + self.steps[index+1:]
        return KnittingPattern(
            name=self.name,
            steps=new_steps,
            description=self.description,
            repetitions=self.repetitions
        )
    
    def with_repetitions(self, repetitions: int) -> 'KnittingPattern':
        """Return new pattern with updated repetitions"""
        return KnittingPattern(
            name=self.name,
            steps=self.steps,
            description=self.description,
            repetitions=repetitions
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "name": self.name,
            "description": self.description,
            "repetitions": self.repetitions,
            "steps": [step.to_dict() for step in self.steps]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KnittingPattern':
        """Create from dictionary"""
        steps = [PatternStep.from_dict(step_data) for step_data in data.get("steps", [])]
        return cls(
            name=data.get("name", "Unnamed Pattern"),
            description=data.get("description", ""),
            repetitions=data.get("repetitions", 1),
            steps=steps
        )
    
    @classmethod
    def empty(cls, name: str = "New Pattern") -> 'KnittingPattern':
        """Create empty pattern"""
        return cls(name=name, steps=[], description="", repetitions=1)


class PatternManager:
    """Manages pattern persistence and operations"""
    
    def __init__(self, patterns_dir: Path):
        self.patterns_dir = Path(patterns_dir)
        self.patterns_dir.mkdir(parents=True, exist_ok=True)
    
    def save_pattern(self, pattern: KnittingPattern) -> bool:
        """Save pattern to file"""
        try:
            filename = self._sanitize_filename(pattern.name)
            file_path = self.patterns_dir / f"{filename}.json"
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(pattern.to_dict(), f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving pattern: {e}")
            return False
    
    def load_pattern(self, name: str) -> Optional[KnittingPattern]:
        """Load pattern from file"""
        try:
            filename = self._sanitize_filename(name)
            file_path = self.patterns_dir / f"{filename}.json"
            
            if not file_path.exists():
                return None
                
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return KnittingPattern.from_dict(data)
        except Exception as e:
            print(f"Error loading pattern: {e}")
            return None
    
    def list_patterns(self) -> List[str]:
        """List all available patterns"""
        try:
            pattern_files = list(self.patterns_dir.glob("*.json"))
            return [f.stem for f in pattern_files]
        except Exception:
            return []
    
    def delete_pattern(self, name: str) -> bool:
        """Delete pattern file"""
        try:
            filename = self._sanitize_filename(name)
            file_path = self.patterns_dir / f"{filename}.json"
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            print(f"Error deleting pattern: {e}")
            return False
    
    def _sanitize_filename(self, name: str) -> str:
        """Create safe filename from pattern name"""
        # Remove invalid filename characters
        invalid_chars = '<>:"/\\|?*'
        filename = ''.join(c for c in name if c not in invalid_chars)
        return filename[:50]  # Limit length
