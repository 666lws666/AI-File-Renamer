"""Retain current-vs-golden evidence without modifying any formal baseline."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.screenshots.m1_cases import CANONICAL_CASES
from PIL import Image, ImageChops

OUT = ROOT / 'tests/screenshots/qa-current/beginner-ui-polish/comparison'
GOLD = ROOT / 'tests/screenshots/golden/m1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    before = {p.name: digest(p) for p in GOLD.glob('*.png')}
    specs = [dict(case_id=c.case_id, filename=c.filename, width=c.width, height=c.height,
                  locale=c.locale) for c in CANONICAL_CASES]
    spec_path = OUT / 'cases.json'
    spec_path.write_text(json.dumps(specs), encoding='utf-8')
    env = dict(os.environ, M1_CASES_JSON=str(spec_path), M1_OUTPUT_DIR=str(OUT),
               QT_QPA_PLATFORM='windows')
    env.pop('UPDATE_GOLDENS', None)
    subprocess.run([sys.executable, str(ROOT / 'scripts/capture_m1_batch.py')],
                   cwd=ROOT, env=env, check=True)
    manifest = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
    assert len(manifest) == len(specs)
    assert all(e['assert_passed'] and not e['warnings'] for e in manifest)
    comparisons = []
    for c in CANONICAL_CASES:
        current = OUT / (c.case_id + '.png')
        baseline = GOLD / (c.filename + '.png')
        with Image.open(current) as ci, Image.open(baseline) as gi:
            assert ci.size == gi.size
            diff = ImageChops.difference(ci.convert('RGB'), gi.convert('RGB'))
            comparisons.append(dict(case_id=c.case_id, golden=baseline.name,
                                    current_sha256=digest(current), golden_sha256=digest(baseline),
                                    changed_bbox=diff.getbbox()))
    assert before == {p.name: digest(p) for p in GOLD.glob('*.png')}
    report = dict(cases=len(specs), unique_goldens=len(before), golden_unchanged=True,
                  comparisons=comparisons)
    (OUT / 'comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'comparisons'}))


if __name__ == '__main__':
    main()
