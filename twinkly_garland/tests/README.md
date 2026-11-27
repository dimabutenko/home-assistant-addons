# Checks of the formula engine

Run from `twinkly_garland/`: `python tests/test_golden.py`, `python tests/test_live.py` and `python tests/test_theme.py` (numpy, fastapi deps of the add-on; no Home Assistant, no garland).

- `golden/examples_0_20_1.json`: the examples as shipped in 0.20.1 (the golden frames were taken from them; the shipped examples changed in 0.21.0).
- `golden/frames.npz`: frames of every example above and of `edge_cases.py` (wall and tree layout, three states of the inputs, five frames with the `prev()` feedback), computed by the scalar engine of 0.20.0 before it was removed. The test allows 2 steps of a colour channel.
- `golden/errors.json`: messages and lines of the formula mistakes (scalar engine, except two deliberate changes, see CHANGELOG 0.20.1).
- Adding a construct to the language: add it to `edge_cases.py` and extend the golden file only from a reference that is not the code under test (the scalar engine no longer exists: use the previous release or a hand-checked formula).
