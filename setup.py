# -*- coding:utf-8 -*-

from setuptools import setup


setup(
    name='cstug-to-dmlcz',
    version='0.0.1',
    author='Vít Novotný',
    author_email='witiko@mail.muni.cz',
    license='GPLv3',
    description='Converts CSTUG XML to DML-CZ XML',
    packages=['cstug_to_dmlcz'],
    package_dir={'cstug_to_dmlcz': 'cstug_to_dmlcz'},
    entry_points={
        'console_scripts': [
            'cstug-to-dmlcz=cstug_to_dmlcz.cstug_to_dmlcz:main',
        ],
    },
    setup_requires=[
        'setuptools',
    ],
    install_requires=[
        'lxml~=4.6.2',
        'click~=7.1.2',
        'PyPDF2~=1.26.0',
        'pycountry~=20.7.3',
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Topic :: Text Processing :: Markup :: XML',
        'Topic :: Utilities',
    ],
    zip_safe=True,
)
