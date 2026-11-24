import sys
from pathlib import Path

# リポジトリ直下の SimpleSkypeBot.py を import できるようにします。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
