import psutil
import datetime

class DataSourceManager:
    """
    Provides system data for DisplayPanels.
    Supported Sources:
    - Static: Returns provided value as-is.
    - CPU: Returns active CPU usage %.
    - RAM: Returns used RAM %.
    - Time: Returns current time (HH:MM:SS).
    - Launched Apps: Handled directly by DisplayPanel via launched_apps_provider callback.
    """

    @staticmethod
    def get_data(source_type: str, static_value: str = "") -> str:
        source = source_type.lower()

        if source == "static":
            return static_value

        elif source == "time":
            return datetime.datetime.now().strftime("%H:%M:%S")

        elif source == "cpu":
            # interval=None returns immediate value since last call (non-blocking)
            return f"{psutil.cpu_percent(interval=None)}%"

        elif source == "ram":
            return f"{psutil.virtual_memory().percent}%"

        # "launched apps" is handled in DisplayPanel directly via callback
        return "N/A"
