"""Read the encoder's summary.txt (platform, trace file, pattern method, ...)."""

import os
from typing import Dict


def parse_summary_file(filepath: str) -> Dict[str, str]:
    """Parses the key-value pairs from the summary.txt file, cleaning prefixes like '-'."""
    summary_data = {}
    if not os.path.exists(filepath):
        return summary_data
    try:
        with open(filepath, 'r') as f:
            for line in f:
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lstrip("-").strip()  # remove leading '-' and spaces
                    summary_data[key] = value.strip()
    except Exception:
        pass
    return summary_data
