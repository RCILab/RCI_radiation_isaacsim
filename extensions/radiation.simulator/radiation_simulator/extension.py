from __future__ import annotations

import carb
import omni.ext

from radiation_simulator.api import clear, get_manager


class RadiationExtension(omni.ext.IExt):
    # Start the manager once so physics-step subscriptions are ready.
    def on_startup(self, ext_id):
        message = f"[radiation] startup: {ext_id}"
        print(message)
        carb.log_info(message)
        get_manager().startup()

    # Drop cached runtime state when the extension shuts down.
    def on_shutdown(self):
        clear()
        get_manager().shutdown()
        print("[radiation] shutdown")
        carb.log_info("[radiation] shutdown")
