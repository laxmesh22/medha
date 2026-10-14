"""Public datasets used to pre-train PB-MotionNet before (and alongside) the team's own recordings.

* ``spar``         - wrist IMU, 7 shoulder physio exercises, 20 subjects (IMU branch).
* ``intellirehab`` - Kinect v2 skeletons, patients + healthy, correct/incorrect labels (skeleton branch).
* ``rehab24``      - OptiTrack skeletons, 30 FPS, segmented reps with correctness labels (skeleton branch).

Download: ``hub/.venv/Scripts/python.exe ml/fetch_public.py`` (files go to ``ml/data/public/``, git-ignored).
Check each licence before redistributing anything derived from these (SPAR GPL-3.0, IntelliRehabDS CC BY 4.0,
REHAB24-6 non-commercial research only).
"""

from .common import PUBLIC_ROOT, SkeletonSequence, sequence_angles, to_skeleton3d  # noqa: F401
