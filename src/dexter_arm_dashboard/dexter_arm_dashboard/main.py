#!/usr/bin/env python3
"""
Dexter Arm Dashboard - Main Entry Point
Launches the HUD interface for robot control.
"""

import sys
from PyQt6.QtWidgets import QApplication
from dexter_arm_dashboard.dashboard_window import DashboardWindow


def main():
    """Main entry point for the dashboard application."""
    app = QApplication(sys.argv)
    
    # Set application properties
    app.setApplicationName("Dexter Arm Dashboard")
    app.setOrganizationName("Dexter Arm")
    
    # Create and show dashboard window
    dashboard = DashboardWindow()
    dashboard.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
