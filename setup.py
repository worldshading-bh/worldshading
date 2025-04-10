# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in worldshading/__init__.py
from worldshading import __version__ as version

setup(
	name="worldshading",
	version=version,
	description="Custom developments",
	author="Hilal Habeeb",
	author_email="it.development@worldshading.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
