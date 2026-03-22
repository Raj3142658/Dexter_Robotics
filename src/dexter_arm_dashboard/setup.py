from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'dexter_arm_dashboard'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob(os.path.join('launch', '*launch.[pxy][yma]*'))),
        (os.path.join('share', package_name, 'config'), glob(os.path.join('config', '*.yaml'))),

    ],
    package_data={
        'dexter_arm_dashboard': ['resources/*', 'resources/**/*'],
    },
    install_requires=[
        'setuptools',
        'PyQt6',
        'PyQt6-QtMultimedia',
        'psutil',
        'pyyaml',
    ],
    zip_safe=True,
    maintainer='raj',
    maintainer_email='raj@todo.todo',
    description='HUD Dashboard interface for Dexter Arm robot control',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'dashboard = dexter_arm_dashboard.main:main',
        ],
    },
)
