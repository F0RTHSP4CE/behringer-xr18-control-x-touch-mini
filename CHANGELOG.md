# Changelog

## 2026-06-11 — claude-sonnet-4-5 — Add bus and FX send mixing modes selectable via bottom-row buttons 9–13

### Added

- **Mixing modes** (`MixingMode` enum): `MASTER` (default), `BUS`, `FX`, `PROCESSING` (stub).
- **Button 9** (row 2, column 1) toggles bus-send mode (lights when active). Knobs 1–8
  control each channel's send level to the selected bus on the active layer page.
- **Button 10** (row 2, column 2) toggles FX-send mode (lights when active). Knobs 1–8
  control each channel's send level to the selected FX bus on the active layer page.
- **Buttons 11–13** act as a 3-bit binary bus selector in BUS mode (000 = bus 1 …
  101 = bus 6; turning on the middle bit while the MSB is on is forbidden to prevent
  invalid states 110/111).
- **Buttons 12–13** act as a 2-bit FX-bus selector in FX mode (00 = FX 1, 01 = FX 2,
  11 = FX 4; the state 10 is forbidden — pressing button 12 while button 13 is off is
  ignored, and turning button 13 off while button 12 is on also clears button 12).
- Pressing **9 and 10 together** (one while the other is lit) activates
  `PROCESSING` mode — a reserved stub for a future channel-processing (EQ, compressor,
  gate) mode.
- **State is preserved** when switching modes: the last selected bus/FX index and all
  send-level values are remembered.
- Knob **pan** (press-and-hold) is disabled while in `PROCESSING` mode (buttons 9 and 10 pressed simultaneously); pan remains fully functional in BUS and FX modes.
- Mute buttons (row 1, buttons 1–8) and the master fader always control the main mix
  regardless of the active mixing mode.
- Extended `xr18.py` with CC lanes 3–8 (`BUS_1_SEND`–`BUS_6_SEND`) and 9–12
  (`FX_1_SEND`–`FX_4_SEND`), new `XR18Client` / `XR18Listener` protocol methods
  `set_channel_bus_send`, `set_channel_fx_send`, `on_channel_bus_send`,
  `on_channel_fx_send`, and corresponding `DemoXR18Client` and `XR18MessageRouter`
  implementations.
