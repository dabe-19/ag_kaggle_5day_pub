"""ADK Agent entry point for packaging discovery."""

import os
import sys

# Ensure the parent directory (src/) is in sys.path so ag_kaggle_5day
# is importable in packaged environments.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ag_kaggle_5day.advisor_agent.agent import root_agent as root_agent
