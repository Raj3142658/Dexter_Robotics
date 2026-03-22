"""
Configuration Loader for Dexter Arm Dashboard
Loads and manages YAML configuration files.
"""

import yaml
import os
import shutil
from pathlib import Path
from ament_index_python.packages import get_package_share_directory

class ConfigLoader:
    """Loads configuration from YAML file."""
    
    def __init__(self, config_path=None):
        """
        Initialize configuration loader.
        Uses ~/.dexter_arm_dashboard/config/layout_config.yaml by default.
        """
        if config_path is None:
            # User config location
            user_dir = Path.home() / ".dexter_arm_dashboard" / "config"
            user_dir.mkdir(parents=True, exist_ok=True)
            self.config_path = user_dir / "layout_config.yaml"
            
            # If user config doesn't exist, copy from package share
            if not self.config_path.exists():
                try:
                    share_dir = Path(get_package_share_directory('dexter_arm_dashboard'))
                    default_config = share_dir / "config" / "layout_config.yaml"
                    
                    if default_config.exists():
                        shutil.copy(default_config, self.config_path)
                        print(f"[INFO] Initialized user config from {default_config}")
                    else:
                        print(f"[WARN] Default config not found at {default_config}")
                except Exception as e:
                    print(f"[WARN] Could not locate package share: {e}")
                    
        else:
            self.config_path = Path(config_path)
            
        self.config = self._load_config()
    
    def _load_config(self):
        """Load configuration from YAML file."""
        if not self.config_path.exists():
             # Return empty default if file still missing
             print(f"[WARN] Config file not found: {self.config_path}. Using empty defaults.")
             return {}
        
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f) or {}

    def reload_config(self):
        """Reload configuration from disk."""
        self.config = self._load_config()
    
    def get_workspace(self):
        """Get workspace directory path."""
        return self.config.get('workspace', '/home/raj/dexter_arm_ws')
    
    def get_microros_workspace(self):
        """Get micro-ROS workspace directory path."""
        return self.config.get('microros_workspace', '/home/raj/microros_ws')
    
    def get_esp32_config(self):
        """Get ESP32 port and baud rate."""
        return {
            'port': self.config.get('esp32_port', '/dev/ttyUSB0'),
            'baud': self.config.get('esp32_baud', 115200)
        }
    
    def get_button(self, button_name):
        """Get button configuration by name."""
        return self.config.get('buttons', {}).get(button_name)
    
    def get_combo(self, combo_name):
        """Get combo configuration by name."""
        return self.config.get('combos', {}).get(combo_name)
    
    def get_utility(self, utility_name):
        """Get utility configuration by name."""
        return self.config.get('utilities', {}).get(utility_name)
    
    def get_all_buttons(self):
        """Get all button configurations."""
        return self.config.get('buttons', {})
    
    def get_all_combos(self):
        """Get all combo configurations."""
        return self.config.get('combos', {})
    
    def get_all_utilities(self):
        """Get all utility configurations."""
        return self.config.get('utilities', {})

    def get_connectors(self):
        """Get all connector lines."""
        return self.config.get('connectors', [])

    def get_display_panels(self):
        """Get all display panels."""
        return self.config.get('display_panels', [])

    def get_layer_order(self):
        """Get layer ordering (front to back)."""
        return self.config.get(
            'layer_order',
            ["connectors", "layer_1", "display_panels", "layer_2", "layer_3", "video"]
        )

    def set_layer_order(self, layer_order):
        """Set layer ordering (front to back)."""
        self.config['layer_order'] = list(layer_order)
        self.save_config()

    def get_opacity_defaults(self):
        """Get default opacity settings."""
        return self.config.get(
            'opacity_defaults',
            {
                'shapes': 0.5,
                'panels': 0.5,
                'video': 0.7,
                'icons': 1.0,
                'connectors': 1.0
            }
        )

    def get_background_settings(self):
        """Get background settings."""
        return self.config.get(
            'background',
            {
                'type': 'video',
                'file': 'dashboard_bg.mp4',
                'opacity': 0.7,
                'aspect_ratio': '16:10',
                'fill': {
                    'mode': 'color',
                    'color': '#0A0E1A',
                    'color2': '#000000',
                    'image': ''
                }
            }
        )

    def set_background_settings(self, settings):
        """Set background settings."""
        self.config['background'] = dict(settings)
        self.save_config()

    def get_title_banner_settings(self):
        """Get title banner settings."""
        return self.config.get(
            'title_banner',
            {
                'title_text': 'DEXTER ARM',
                'subtitle_text': 'ROBOTIC MANIPULATION SYSTEM',
                'hover_text': '⚙ DEXTER ARM  ━━━━━━━━━━━━━━━━━━━━\n\n▸ Platform     ROS 2 Jazzy · Gazebo Harmonic\n▸ Simulation   MoveIt 2 · RViz2 · Gazebo Physics\n▸ Planning     OMPL · Servo · MoveGroup\n\n◈ Hardware     ESP32 Controller + micro-ROS Agent\n◈ Control      Real-time Joint via Serial/WiFi\n◈ Firmware     Flash & OTA Update Support\n\n◇ Dashboard    PyQt6 HUD Control Interface\n◇ Trajectory   FK/IK Workspace Generation\n◇ Monitor      System Process & Resource Tracking',
                'title_color': '#00F3FF',
                'font_family': 'Orbitron',
                'font_size': 24,
                'visible': True,
                'x': 0,
                'y': 0,
                'width': 1280,
                'height': 70
            }
        )

    def set_title_banner_settings(self, settings):
        """Set title banner settings."""
        self.config['title_banner'] = dict(settings)
        self.save_config()

    def set_opacity_defaults(self, defaults):
        """Set default opacity settings."""
        self.config['opacity_defaults'] = dict(defaults)
        self.save_config()

    def get_icon_groups(self):
        """Get all icon groups."""
        return self.config.get('icon_groups', [])

    def add_icon_group(self, group_data):
        """Add a new icon group."""
        if 'icon_groups' not in self.config:
            self.config['icon_groups'] = []
        self.config['icon_groups'].append(group_data)
        self.save_config()

    def update_icon_group(self, index, group_data):
        """Update an icon group by index."""
        if 'icon_groups' in self.config and 0 <= index < len(self.config['icon_groups']):
            self.config['icon_groups'][index] = group_data
            self.save_config()

    def remove_icon_group(self, index):
        """Remove an icon group by index."""
        if 'icon_groups' in self.config and 0 <= index < len(self.config['icon_groups']):
            self.config['icon_groups'].pop(index)
            self.save_config()

    def get_custom_icons(self):
        """Get custom icons list."""
        return self.config.get('custom_icons', [])

    def add_custom_icon(self, icon_data):
        """Add a new custom icon entry."""
        if 'custom_icons' not in self.config:
            self.config['custom_icons'] = []
        self.config['custom_icons'].append(icon_data)
        self.save_config()

    def remove_custom_icon(self, index):
        """Remove a custom icon by index and clean up all references."""
        if 'custom_icons' not in self.config or not (0 <= index < len(self.config['custom_icons'])):
            return
        icon = self.config['custom_icons'][index]
        icon_name = icon.get('name', '')

        # Remove from custom_icons list
        self.config['custom_icons'].pop(index)

        if icon_name:
            # Remove the top-level position entry saved by save_layout()
            self.config.pop(icon_name, None)

            # Remove corresponding button config entry
            if 'buttons' in self.config:
                self.config['buttons'].pop(icon_name, None)

            # Clean icon_groups: remove groups whose main_icon is this icon,
            # and strip it from the items list of any other group.
            if 'icon_groups' in self.config:
                updated_groups = []
                for group in self.config['icon_groups']:
                    if group.get('main_icon') == icon_name:
                        continue  # drop group whose main icon was deleted
                    # Remove from items / group_items
                    for key in ('items', 'group_items'):
                        if key in group:
                            group[key] = [
                                it for it in (group[key] or [])
                                if it != icon_name and it != f'icon:{icon_name}'
                            ]
                    updated_groups.append(group)
                self.config['icon_groups'] = updated_groups

        self.save_config()

    def add_connector(self, connector_data):
        """Add a new connector line."""
        if 'connectors' not in self.config:
            self.config['connectors'] = []
        self.config['connectors'].append(connector_data)
        self.save_config()

    def remove_connector(self, index):
        """Remove a connector line by index."""
        if 'connectors' in self.config and 0 <= index < len(self.config['connectors']):
            self.config['connectors'].pop(index)
            self.save_config()

    def add_display_panel(self, panel_data):
        """Add a new display panel."""
        if 'display_panels' not in self.config:
            self.config['display_panels'] = []
        self.config['display_panels'].append(panel_data)
        self.save_config()

    def remove_display_panel(self, index):
        """Remove a display panel by index."""
        if 'display_panels' in self.config and 0 <= index < len(self.config['display_panels']):
            self.config['display_panels'].pop(index)
            self.save_config()

    def update_connectors(self, connectors_list):
        """Update all connectors."""
        self.config['connectors'] = connectors_list
        self.save_config()

    def update_panels(self, panels_list):
        """Update all display panels."""
        self.config['display_panels'] = panels_list
        self.save_config()

    def save_config(self):
        """Save current configuration to YAML file."""
        try:
            with open(self.config_path, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)
            print(f"[INFO] Configuration saved to {self.config_path}")
        except Exception as e:
            print(f"[ERROR] Failed to save config: {e}")
    
    def get_edit_mode_enabled(self) -> bool:
        """Get whether Edit Mode (E key) is enabled. Defaults to True."""
        if 'settings' not in self.config:
            self.config['settings'] = {}
        return self.config['settings'].get('edit_mode_enabled', False)
    
    def set_edit_mode_enabled(self, enabled: bool):
        """Set whether Edit Mode (E key) is enabled and save to config."""
        if 'settings' not in self.config:
            self.config['settings'] = {}
        self.config['settings']['edit_mode_enabled'] = enabled
        self.save_config()
