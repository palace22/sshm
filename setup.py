#!/usr/bin/env python3
"""
Setup script for SSH Manager.
Alternative to Poetry for simpler installations.
"""

from pathlib import Path

from setuptools import find_packages, setup

# Read the README file
readme_file = Path(__file__).parent / "README.md"
long_description = (
    readme_file.read_text(encoding="utf-8") if readme_file.exists() else ""
)

# Read version from package
version = "0.1.0"

setup(
    name="sshm",
    version=version,
    description="SSH CLI Manager - A modern tool to manage SSH connections",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="palace22",
    author_email="",
    url="https://github.com/palace22/sshm",
    project_urls={
        "Bug Tracker": "https://github.com/palace22/sshm/issues",
        "Source Code": "https://github.com/palace22/sshm",
    },
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "typer>=0.12.0",
        "paramiko>=3.4.0",
        "rich>=13.7.0",
        "pydantic>=2.5.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0.0",
            "black>=24.0.0",
            "isort>=5.13.0",
            "mypy>=1.8.0",
            "pre-commit>=3.6.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "sshm=sshm.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Internet",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Networking",
        "Topic :: Terminals",
        "Topic :: Utilities",
    ],
    python_requires=">=3.10",
    keywords=["ssh", "cli", "terminal", "manager", "config"],
    license="GPL-3.0-or-later",
)
