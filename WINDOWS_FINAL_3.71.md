# Windows CMB DXF Viewer v3.71_FINAL

This integration changes Windows client code only. Server V4.1 and server-tools are unchanged.

- At Kakao levels L1-L3, enabled FIBER/COAX/CONDUIT LineString and MultiLineString parts render individually. Valid original coordinates are retained if snapping throws or returns invalid coordinates. The status includes actual rendered line totals and group totals.
- At L4 and above all network overlays are removed, including immediately on zoom change. Old asynchronous responses cannot restore them.
- Group OFF immediately detaches that group's overlays with setMap(null), makes no request, preserves other visible groups and invalidates pending loads. ON reloads. Redundant idle events do not cancel a forced reload.
- The map-viewer shares one CMBServerClient between its session guard, user/region administration, upload and server extraction. A refresh lock and access-token comparison ensure concurrent expired requests rotate the shared refresh token once.
- Upload region selection is disabled. The DXF filename stem must exactly equal the canonical server region id; aliases, suffixes and case differences are not accepted. Missing regions disable upload. Failed region refresh clears stale mappings and disables upload until a successful matching lookup.

Validation: run desktop/CadExcelConverter/run_checks.py with Python 3.12 and Node.js. The suite includes generated JavaScript execution with a Kakao adapter, concurrent refresh requests, actual App window wiring and upload region behavior, plus all existing DXF/Excel regressions. Synthetic tests do not establish production server availability or correctness of every real DXF drawing.

The Windows workflow builds main.py directly, runs the packaged executable with --build-smoke-test, validates Tcl/Tk and coordinate conversion, records source/executable SHA256 in BUILD_MANIFEST.json and publishes the ZIP only after those steps pass.

Release: https://github.com/ysjus2/cmb_test/releases/tag/v3.71_FINAL
