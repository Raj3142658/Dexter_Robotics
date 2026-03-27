from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'dexter_arm_trajectory'

setup(
    name=package_name,
    version='2.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'trajectories'), glob('trajectories/*')),
        (os.path.join('share', package_name, 'srv'), glob('srv/*.srv')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Raj',
    maintainer_email='raj@example.com',
    description='Teach-repeat trajectory system for Dexter Arm',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'trajectory_manager = dexter_arm_trajectory.trajectory_manager_node:main',
            'trajectory_gui = dexter_arm_trajectory.trajectory_teach_gui:main',
            'tcp_visualizer = dexter_arm_trajectory.tcp_visualizer_node:main',
            'shape_trajectory = dexter_arm_trajectory.shape_trajectory_node:main',
        ],
    },
)
