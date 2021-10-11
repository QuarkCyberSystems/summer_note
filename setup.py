# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

with open('requirements.txt') as f:
	install_requires = f.read().strip().split('\n')

# get version from __version__ variable in summer_note/__init__.py
from summer_note import __version__ as version

setup(
	name='summer_note',
	version=version,
	description='summer note',
	author='QCS',
	author_email='vivek@quarkcs.com',
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
