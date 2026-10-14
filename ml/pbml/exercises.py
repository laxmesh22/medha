"""Exercise label set.

The 11 classes of Lee et al. 2024 (Table/Fig. order), used as the baseline label space. Our showcase
subset (frozen shoulder, camera + strap measurable) is marked. Clinical content for patients lives in
``content/exercises`` and needs physiotherapist approval. This module is only the ML label space.
"""

from __future__ import annotations

LEE2024_EXERCISES = [
    # id, Lee 2024 name, band?, in our frozen-shoulder showcase set?
    ("posterior_capsule_stretch", "Posterior capsule stretching", False, True),
    ("pec_minor_stretch", "Pectoralis minor stretching", False, False),
    ("pendulum", "Pendulum exercise", False, True),
    ("lawnmower", "Lawnmower exercise", False, False),
    ("abduction_band", "Shoulder abduction (band)", True, True),
    ("extension_band", "Shoulder extension (band)", True, False),
    ("er_band", "Shoulder external rotation (band)", True, True),
    ("ir_band", "Shoulder internal rotation (band)", True, True),
    ("er_sidelying", "Shoulder external rotation (side-lying)", False, False),
    ("prone_extension", "Prone shoulder extension", False, False),
    ("anterior_deltoid", "Anterior deltoid strengthening", False, True),
]

CLASS_IDS = [e[0] for e in LEE2024_EXERCISES]
SHOWCASE_IDS = [e[0] for e in LEE2024_EXERCISES if e[3]]

# Lee 2024 reported cross-identification between these two (their classes 6 and 7).
KNOWN_CONFUSION = ("extension_band", "er_band")
