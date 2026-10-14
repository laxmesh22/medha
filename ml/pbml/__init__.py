"""Physio Buddy ML: exercise recognition.

Baseline = exact reproduction of Lee K. et al. 2024, J NeuroEng Rehabil 21:42
(https://pmc.ncbi.nlm.nih.gov/articles/PMC10967210/): one wrist IMU @100 Hz, 24 statistical features
(min/max/mean/var of accel + gyro x/y/z) -> MLP 8-16-32-64-128 ReLU -> softmax over 11 exercises.
Their 92.5 % comes from a random 80:20 split; we also report leave-one-subject-out (LOSO).
"""
