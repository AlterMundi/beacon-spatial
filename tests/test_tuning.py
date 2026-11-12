"""Prevent drift between the tuned guitar, actual DSP and displayed bands."""
import ast
import re
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

def test_dsp_and_ui_use_guitar_harmonics():
    expected = [40.4 * n for n in (1, 2, 3, 4, 5, 6, 12, 18, 24, 30, 36, 42, 45)]
    sc = (ROOT / 'beacon.scd').read_text()
    actual = ast.literal_eval(re.search(r'var bpfFreqs = (\[[^;]+\]);', sc)[1])
    assert actual == pytest.approx(expected)
    tree = ast.parse((ROOT / 'webui.py').read_text())
    bands = next(ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'BANDS' for t in node.targets))
    assert [band['freq'] for band in bands[:-1]] == pytest.approx(expected[:-1])
    assert bands[-1]['freq'] == f'{expected[-1]:g}+'
    assert '13-band • 40.4Hz series' in (ROOT / 'webui.py').read_text()
