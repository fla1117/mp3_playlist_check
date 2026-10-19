"""Entrypoint for python -m src.gui."""
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_DIR))

from src.gui.app import main

if __name__ == "__main__":
    main()
