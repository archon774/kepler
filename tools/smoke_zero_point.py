from pathlib import Path
from tools.claude_photometry_haiku_tool import resolve_zero_point_mag

class DummyHeader(dict):
    pass

print(resolve_zero_point_mag(Path('dummy.fits'), DummyHeader({'PHOT_M0': 17.2})))
print(resolve_zero_point_mag(Path('dummy.fits'), DummyHeader({'FILTER': 'R'})))
