"""Synthetic smoke test: these are demo numbers, not model measurements."""
import argparse
import json
from pathlib import Path
import time
p = argparse.ArgumentParser()
p.add_argument('--output', required=True)
a = p.parse_args()
time.sleep(1)
Path(a.output).write_text(json.dumps({'dice_mean': 0.9, 'model_inference_mean_sec': 0.25}), encoding='utf-8')
print('Synthetic test metrics written')
