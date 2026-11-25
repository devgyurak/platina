"""Shell: turns engine Commands into I/O. The async runner (anyio) is the source; the sync
runner is generated from it and never edited by hand (design section 10.5).
"""
